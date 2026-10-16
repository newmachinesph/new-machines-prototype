"""Sub-project C, part 8: "Test in sandbox" starts a real run of the org's own pack on sandbox data, without
adding the pack or connecting apps. The pause, the input schema and the monthly spend cap still apply."""

from app import ops_state, studio
from app.defs import owners
from app.runtime import drivers, gateway, projection
from tests.test_live_catalog import _rows, ana, ben, live, starts  # noqa: F401
from tests.test_studio_packs import AS_OF, _base, _create

LIVE_ONLY = "The Studio is part of the live workspace."


def _test(user, key: str, body: dict | None = None, org_id: str | None = None):
    return user.post(
        f"{_base(user, org_id)}/packs/{key}:test", json={"input": AS_OF} if body is None else body
    )


def test_a_sandbox_test_runs_the_pack_without_adding_it(db, ana, starts):  # noqa: F811
    key, _ = _create(ana)
    res = _test(ana, key)
    assert res.status_code == 202, res.text
    run = res.json()
    assert run["sandboxTest"] is True and run["packSlug"] == key
    assert "listingCheck" not in run  # the builder's own test is not a listing check
    assert starts.calls[-1][1:] == (ana.org_id, AS_OF)
    assert run["budget"]["amountMinor"] == 1500  # the pack's maximum
    [listed] = ana.get("/v1/workflow-runs").json()
    assert listed["sandboxTest"] is True
    assert ana.get(f"/v1/workflow-runs/{run['id']}").json()["sandboxTest"] is True
    [started] = _rows(
        db, "SELECT data FROM receipt_entries WHERE run_id = %s AND type = 'run.started'", run["id"]
    )
    assert started["data"]["sandbox_test"] is True
    assert _rows(db, "SELECT count(*) AS n FROM installations")[0]["n"] == 0


def test_a_sandbox_test_is_not_routed_through_the_orgs_connections(db, ana, starts):  # noqa: F811
    key, _ = _create(ana)
    assert ana.connect("stripe").status_code == 200  # a real connection the test must not reach
    run = _test(ana, key).json()
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", run["id"])
    snapshot = row["snapshot"]
    assert "routing" not in snapshot and "routes" not in snapshot
    # The snapshot pins sandbox data, so a worker in any connector mode answers from the sandbox driver.
    assert snapshot["connector_mode"] == "sandbox"
    stripe = snapshot["defs"]["connector"]["stripe"]["body"]
    assert isinstance(gateway.driver_of(snapshot, "stripe", stripe, "live"), drivers.SandboxDriver)
    assert gateway.runs_simulated(snapshot, "stripe.list_invoices", "live") is True
    receipt = ana.get(f"/v1/workflow-runs/{run['id']}/receipt").json()
    assert receipt["items"][0]["summary"].startswith("Sandbox test started")


def test_a_pinned_sandbox_mode_decides_the_driver_whatever_the_workers_mode():
    pinned = {"connector_mode": "sandbox"}
    assert isinstance(
        gateway.driver_of(pinned, "stripe", {"toolkit": "stripe"}, "live"), drivers.SandboxDriver
    )
    assert not isinstance(
        gateway.driver_of({}, "stripe", {"toolkit": "stripe"}, "live"), drivers.SandboxDriver
    )


def test_the_sandbox_test_label_survives_the_runs_events(db, ana, starts):  # noqa: F811
    key, _ = _create(ana)
    run = _test(ana, key).json()
    [row] = _rows(db, "SELECT projection FROM runs WHERE id = %s", run["id"])
    event = {
        "type": "run.failed",
        "at": "2026-10-13T10:00:00+00:00",
        "node_id": None,
        "data": {"reason": "x"},
    }
    folded = projection.apply_event(row["projection"], event)
    assert folded["status"] == "FAILED" and folded["sandboxTest"] is True


def test_the_budget_of_a_sandbox_test_is_honoured_up_to_the_packs_maximum(ana, starts):  # noqa: F811
    key, _ = _create(ana)
    res = _test(ana, key, {"input": AS_OF, "budgetMinor": 900})
    assert res.status_code == 202 and res.json()["budget"]["amountMinor"] == 900
    over = _test(ana, key, {"input": AS_OF, "budgetMinor": 2000})
    assert over.status_code == 422 and over.json()["code"] == "BUDGET_TOO_HIGH"
    assert len(starts.calls) == 1


def test_a_sandbox_test_of_a_pack_without_a_budget_needs_one(ana, starts, monkeypatch):  # noqa: F811
    key, _ = _create(ana)
    monkeypatch.setattr(studio, "_test_budget", lambda conn, pack: 0)
    res = _test(ana, key)
    assert res.status_code == 422 and res.json()["code"] == "BUDGET_REQUIRED"
    assert res.json()["detail"] == "Set a budget for this test run."
    assert starts.calls == []
    assert _test(ana, key, {"input": AS_OF, "budgetMinor": 500}).status_code == 202


def test_a_normal_run_is_not_a_sandbox_test(db, ana, starts):  # noqa: F811
    key, _ = _create(ana)
    added = ana.post(
        f"/v1/organizations/{ana.org_id}/agent-installations", json={"packSlug": key, "capMinor": 2000}
    )
    assert added.status_code == 201, added.text
    for app in ("stripe", "gmail"):
        assert ana.connect(app).status_code == 200
    res = ana.post("/v1/workflow-runs", json={"packSlug": key, "input": AS_OF, "budgetMinor": 1000})
    assert res.status_code == 202, res.text
    run = res.json()
    assert "sandboxTest" not in run
    [listed] = ana.get("/v1/workflow-runs").json()
    assert "sandboxTest" not in listed
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", run["id"])
    assert "routing" in row["snapshot"]


def test_the_input_is_checked_against_the_packs_input_schema(ana, starts):  # noqa: F811
    key, _ = _create(ana)
    res = _test(ana, key, {"input": {}})
    assert res.status_code == 422 and res.json()["code"] == "INVALID_INPUT"
    assert starts.calls == []


def test_a_sandbox_test_respects_the_platform_pause(db, ana, starts):  # noqa: F811
    key, _ = _create(ana)
    ops_state.set_paused(db, True, "ops@example.com", "Incident")
    db.commit()
    res = _test(ana, key)
    assert res.status_code == 409 and res.json()["code"] == "PLATFORM_PAUSED"
    assert starts.calls == []


def test_a_sandbox_test_needs_sandbox_connectors(ana, starts, monkeypatch):  # noqa: F811
    key, _ = _create(ana)
    monkeypatch.setenv("NM_CONNECTOR_MODE", "live")
    res = _test(ana, key)
    assert res.status_code == 409 and res.json()["code"] == "SANDBOX_UNAVAILABLE"
    assert res.json()["detail"] == (
        "Test runs need the platform's sandbox connectors, which this deployment does not use."
    )
    assert starts.calls == []


def test_a_sandbox_test_respects_the_monthly_spend_cap(db, ana, starts):  # noqa: F811
    key, _ = _create(ana)
    db.execute("UPDATE orgs SET monthly_cap_minor = 0 WHERE id = %s", (ana.org_id,))
    db.commit()
    res = _test(ana, key)
    assert res.status_code == 409 and res.json()["code"] == "SPEND_CAP"
    assert starts.calls == []


def test_only_the_owning_org_can_test_its_pack(ana, ben, starts):  # noqa: F811
    key, _ = _create(ana)
    theirs = _test(ben, key)
    assert theirs.status_code == 404
    missing = _test(ben, owners.org_key(ben.org_id, "no-such-pack"))
    assert missing.status_code == 404
    # Another org's pack and a missing one read the same, so a caller cannot probe for another org's keys.
    assert theirs.json()["code"] == missing.json()["code"] == "NOT_FOUND"
    assert theirs.json()["detail"].replace(key, "") == missing.json()["detail"].replace(
        owners.org_key(ben.org_id, "no-such-pack"), ""
    )
    assert _test(ben, key, org_id=ana.org_id).status_code == 403
    assert starts.calls == []


def test_a_reviewer_cannot_test_a_pack(db, ana, starts):  # noqa: F811
    key, _ = _create(ana)
    db.execute("UPDATE org_members SET role = 'reviewer' WHERE user_id = 'uid_ana'")
    db.commit()
    res = _test(ana, key)
    assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED"
    assert starts.calls == []


def test_the_demo_workspace_has_no_sandbox_tests(client):
    res = client.post("/v1/organizations/org_hp01/studio/packs/x--y:test", json={"input": {}})
    assert res.status_code == 404 and res.json()["detail"] == LIVE_ONLY
