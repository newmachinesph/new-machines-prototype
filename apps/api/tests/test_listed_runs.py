"""Sub-project D, part 16: a run of another workspace's listed pack pins the version the buyer added, pays the
pinned price up front within the monthly cap, and shows the fee on its receipt. Own runs and sandbox tests pay
nothing."""

import pytest
from psycopg.types.json import Jsonb

from app import fees, live_work, real_runs
from app.defs import registry
from app.defs.model import Definition, path_for
from tests.publishing_seed import add_listing, add_version, approve_and_list, defs_of
from tests.team_seed import TEAM_AGENT, clone_pack, invoice_nudges
from tests.test_live_catalog import INPUT, _add_run, _rows, ana, ben, live, starts  # noqa: F401

PACK = "order-payment-reconciliation"
APPS = ("shopify", "stripe", "googlesheets")


def _bundle(db, key: str) -> list[dict]:
    return defs_of(db, [("pack", key), ("workflow", key), ("contract", key)])


def _listed(db, org_id: str, price: int = 250) -> tuple[str, str, str]:
    """`org_id`'s copy of the seed pack, listed at its first version: (key, listing id, version id)."""
    key = clone_pack(db, PACK, org_id, "recon", title="Acme recon")
    listing = add_listing(db, "pack", key, org_id, name="Acme recon")
    version = add_version(db, listing, 1, _bundle(db, key), price_minor=price)
    approve_and_list(db, listing, version)
    db.commit()
    return key, listing, version


def _approve_v2(db, key: str, listing: str, price: int, **changes) -> str:
    v = registry.latest(db, "pack", key)
    d = Definition(
        kind="pack",
        key=key,
        body={**v.body, "name": "Acme recon two", **changes},
        files=dict(v.files),
        path=path_for("pack", key),
    )
    registry.publish(db, d, "test", "version two", source=registry.BUILDER)
    version = add_version(db, listing, 2, _bundle(db, key), price_minor=price)
    approve_and_list(db, listing, version)
    db.commit()
    return version


def _add(user, key: str) -> None:
    body = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    res = user.post(f"/v1/organizations/{user.org_id}/agent-installations", json=body)
    assert res.status_code == 201, res.text
    for app in APPS:
        assert user.connect(app).status_code == 200


def _start(user, key: str, budget: int = 1000):
    """A run of `key` with `budget`: the pack fee comes on top, within the hire's cap of 2000 a run."""
    return user.post("/v1/workflow-runs", json={"packSlug": key, "input": INPUT, "budgetMinor": budget})


def _fees(db) -> list[tuple]:
    return [
        tuple(r.values())
        for r in _rows(
            db,
            "SELECT run_id, kind, amount_minor, listing_version_id, buyer_org_id FROM fee_lines ORDER BY id",
        )
    ]


def test_a_buyers_run_pins_the_added_version_and_pays_its_price(ana, ben, db):  # noqa: F811
    key, listing, first = _listed(db, ana.org_id, price=250)
    _add(ben, key)
    _approve_v2(db, key, listing, price=400)  # ben has not updated: his runs stay on version 1
    res = _start(ben, key)
    assert res.status_code == 202, res.text
    run_id = res.json()["id"]
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", run_id)
    pinned = {(v["kind"], v["key"]): v["version"] for v in row["snapshot"]["versions"]}
    assert pinned[("pack", key)] == 1
    assert row["snapshot"]["fees"]["pack"]["unit_minor"] == 250
    assert _fees(db) == [(run_id, "pack_run", 250, first, ben.org_id)]
    receipt = ben.get(f"/v1/workflow-runs/{run_id}/receipt").json()
    assert [(f["name"], f["kind"], f["amount"]["amountMinor"]) for f in receipt["fees"]] == [
        ("Acme recon", "pack_run", 250)
    ]
    assert ana.get(f"/v1/workflow-runs/{run_id}/receipt").status_code == 404  # the publisher never reads it


def test_the_publishers_own_run_pays_no_fee(ana, db):  # noqa: F811
    key, _, _ = _listed(db, ana.org_id)
    _add(ana, key)
    res = _start(ana, key)
    assert res.status_code == 202, res.text
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", res.json()["id"])
    assert row["snapshot"]["fees"] == {"pack": None, "agents": {}}
    assert _fees(db) == []


def test_a_sandbox_test_pays_no_fee(ana, db):  # noqa: F811
    key, _, _ = _listed(db, ana.org_id)
    res = ana.post(f"/v1/organizations/{ana.org_id}/studio/packs/{key}:test", json={"input": INPUT})
    assert res.status_code == 202, res.text
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", res.json()["id"])
    assert row["snapshot"]["fees"] == {"pack": None, "agents": {}} and _fees(db) == []


@pytest.mark.parametrize(("budget", "allowed"), [(1750, True), (1751, False)])
def test_the_per_run_cap_counts_the_pack_fee(ana, ben, db, budget, allowed):  # noqa: F811
    key, _, _ = _listed(db, ana.org_id, price=250)
    _add(ben, key)  # a cap of 2000 a run
    res = _start(ben, key, budget=budget)
    if allowed:
        assert res.status_code == 202, res.text
        return
    assert res.status_code == 409 and res.json()["code"] == "RUN_BUDGET_OVER_CAP", res.text
    assert "$2.50" in res.json()["detail"]
    assert _rows(db, "SELECT id FROM runs WHERE org_id = %s", ben.org_id) == [] and _fees(db) == []


def test_an_added_pack_says_the_most_a_run_may_be_given_at_the_held_fee(ana, ben, db):  # noqa: F811
    """The pack's runFee is the held version's price, not the newer one's, and runBudgetLimit is the most a
    start accepts: the per-run cap less that fee, within the contract's maximum."""
    key, listing, _ = _listed(db, ana.org_id, price=250)
    _add(ben, key)  # a cap of 2000 a run
    _approve_v2(db, key, listing, price=400)  # Ben still holds version 1, at 250
    detail = ben.get(f"/v1/workflow-packs/{key}").json()
    listed = next(p for p in ben.get("/v1/workflow-packs").json() if p["slug"] == key)
    for pack in (detail, listed):
        assert pack["runFee"]["amountMinor"] == 250
        assert pack["runBudgetLimit"]["amountMinor"] == 1750
    assert _start(ben, key, budget=1750).status_code == 202
    own = ana.get(f"/v1/workflow-packs/{key}").json()
    assert "runFee" not in own and "runBudgetLimit" not in own  # the publisher has not added it


def test_the_apps_checked_are_the_held_versions(ana, ben, db):  # noqa: F811
    key, listing, _ = _listed(db, ana.org_id)
    _add(ben, key)  # Ben holds version 1 and connected its three apps
    _approve_v2(db, key, listing, price=250, connectors=[*APPS, "gmail"])  # version 2 also needs Gmail
    res = _start(ben, key)
    assert res.status_code == 202, res.text


def test_an_app_only_the_held_version_needs_is_still_checked(ana, ben, db):  # noqa: F811
    key, listing, _ = _listed(db, ana.org_id)
    _add(ben, key)
    _approve_v2(db, key, listing, price=250, connectors=["shopify", "stripe"])  # version 2 drops Sheets
    db.execute("DELETE FROM connections WHERE org_id = %s AND app = 'googlesheets'", (ben.org_id,))
    db.commit()
    res = _start(ben, key)  # Ben's runs still pin version 1, which writes to Sheets
    assert res.status_code == 409 and res.json()["code"] == "APPS_NOT_CONNECTED", res.text
    assert _fees(db) == []


def _unlist(db, listing: str) -> None:
    """What `listings.move` commits when ops unlists."""
    db.execute("UPDATE listings SET status = 'unlisted' WHERE id = %s", (listing,))
    db.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing,))
    db.commit()


def _unlisted_after_the_pin(db, monkeypatch, listing: str) -> None:
    """The unlist commits after the run pinned its versions and before it plans its fees."""
    real = real_runs.build_snapshot

    def racing(*args, **kwargs):
        snapshot = real(*args, **kwargs)
        _unlist(db, listing)
        return snapshot

    monkeypatch.setattr(real_runs, "build_snapshot", racing)


def test_a_pack_unlisted_mid_start_never_runs_free(ana, ben, db, monkeypatch):  # noqa: F811
    key, listing, _ = _listed(db, ana.org_id, price=250)
    _add(ben, key)
    _unlisted_after_the_pin(db, monkeypatch, listing)
    res = _start(ben, key)
    assert res.status_code == 409 and res.json()["code"] == "PACK_UNAVAILABLE", res.text
    assert _rows(db, "SELECT id FROM runs WHERE org_id = %s", ben.org_id) == [] and _fees(db) == []


def _bens_pack_with_anas_agent(ana, ben, db, price: int = 30) -> tuple[str, str, str]:  # noqa: F811
    """Ana lists her team agent at `price` a call; Ben's own pack calls it: (agent, agent listing, pack)."""
    res = ana.post(f"/v1/organizations/{ana.org_id}/studio/agents", json=TEAM_AGENT.model_dump(by_alias=True))
    assert res.status_code == 201, res.text
    agent = res.json()["key"]
    listing = add_listing(db, "agent", agent, ana.org_id, name="Invoice helper")
    version = add_version(db, listing, 1, defs_of(db, [("agent", agent)]), price_minor=price)
    approve_and_list(db, listing, version)
    db.commit()
    draft = invoice_nudges(agent).model_dump(by_alias=True, exclude_none=True)
    saved = ben.post(f"/v1/organizations/{ben.org_id}/studio/packs", json=draft)
    assert saved.status_code == 201, saved.text
    return agent, listing, saved.json()["key"]


def _sandbox_test(user, key: str):
    body = {"input": {"as_of": "2026-10-01"}, "budgetMinor": 500}
    return user.post(f"/v1/organizations/{user.org_id}/studio/packs/{key}:test", json=body)


def test_a_buyers_sandbox_test_pays_for_another_workspaces_agent(ana, ben, db):  # noqa: F811
    agent, listing, key = _bens_pack_with_anas_agent(ana, ben, db, price=30)
    res = _sandbox_test(ben, key)
    assert res.status_code == 202, res.text
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", res.json()["id"])
    plan = row["snapshot"]["fees"]
    assert plan["pack"] is None and set(plan["agents"]) == {agent}
    assert (plan["agents"][agent]["listing_id"], plan["agents"][agent]["unit_minor"]) == (listing, 30)
    assert _fees(db) == []  # charged per call, when the agent step runs


def test_an_agent_unlisted_mid_start_never_runs_free(ana, ben, db, monkeypatch):  # noqa: F811
    _, listing, key = _bens_pack_with_anas_agent(ana, ben, db)
    _unlisted_after_the_pin(db, monkeypatch, listing)
    res = _sandbox_test(ben, key)
    assert res.status_code == 409 and res.json()["code"] == "PACK_UNAVAILABLE", res.text
    assert _rows(db, "SELECT id FROM runs WHERE org_id = %s", ben.org_id) == [] and _fees(db) == []


@pytest.mark.parametrize(("fee", "allowed"), [(500, True), (600, False)])
def test_the_cap_counts_the_pack_fee_up_front(ana, ben, db, fee, allowed):  # noqa: F811
    key, _, _ = _listed(db, ana.org_id, price=fee)
    _add(ben, key)
    _add_run(db, ben.org_id, "run_old", spent=2000)  # the default monthly cap is 2500
    db.commit()
    res = _start(ben, key)
    if allowed:
        assert res.status_code == 202, res.text
        return
    assert res.status_code == 409 and res.json()["code"] == "SPEND_CAP"
    assert "publisher fee of $6.00" in res.json()["detail"]
    assert _fees(db) == []


def test_an_unlisted_pack_cannot_start(ana, ben, db):  # noqa: F811
    key, listing, _ = _listed(db, ana.org_id)
    _add(ben, key)
    db.execute("UPDATE listings SET status = 'unlisted' WHERE id = %s", (listing,))
    db.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing,))
    db.commit()
    assert _start(ben, key).status_code in (404, 409)
    assert _fees(db) == []


def test_a_pin_without_an_approved_version_fails_clearly(ana, ben, db):  # noqa: F811
    key, _, _ = _listed(db, ana.org_id)
    _add(ben, key)
    v = registry.latest(db, "pack", key)
    d = Definition(
        kind="pack",
        key=key,
        body={**v.body, "name": "Acme recon draft"},
        files=dict(v.files),
        path=path_for("pack", key),
    )
    registry.publish(db, d, "test", "a draft", source=registry.BUILDER)
    # The installation holds a version no approved listing version exposes: never the draft, never version 1.
    db.execute(
        "UPDATE installations SET pack_version = 2 WHERE org_id = %s AND pack_slug = %s", (ben.org_id, key)
    )
    db.commit()
    res = _start(ben, key)
    assert res.status_code == 409 and res.json()["code"] == "PACK_UNAVAILABLE", res.text
    # The buyer is told why and what to do next, not just that it cannot run.
    assert "new runs cannot start" in res.json()["detail"]
    assert _rows(db, "SELECT id FROM runs WHERE org_id = %s", ben.org_id) == []
    assert _fees(db) == []


def _approve_again(db, key: str, listing: str, definitions: list[dict], price: int) -> str:
    """A newer approved decision at definition version 1, decided after every earlier one."""
    version = add_version(db, listing, 1, definitions, price_minor=price)
    approve_and_list(db, listing, version)
    db.execute(
        "UPDATE listing_versions SET decided_at = now() + interval '1 minute' WHERE id = %s", (version,)
    )
    db.commit()
    return version


def test_the_cap_and_the_charge_use_the_newest_decision_at_a_version(ana, ben, db):  # noqa: F811
    key, listing, _ = _listed(db, ana.org_id, price=600)
    newest = _approve_again(db, key, listing, _bundle(db, key), price=500)
    _add(ben, key)
    _add_run(
        db, ben.org_id, "run_old", spent=2000
    )  # 600 would take the month over the 2500 cap; 500 does not
    db.commit()
    res = _start(ben, key)
    assert res.status_code == 202, res.text
    run_id = res.json()["id"]
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", run_id)
    assert row["snapshot"]["fees"]["pack"]["unit_minor"] == 500
    assert _fees(db) == [(run_id, "pack_run", 500, newest, ben.org_id)]


def test_a_listing_of_a_key_its_publisher_does_not_own_charges_nothing(ana, ben, db):  # noqa: F811
    # Ben's workspace lists the platform's pack (written straight into the tables, past `listings.submit`).
    listing = add_listing(db, "pack", PACK, ben.org_id, name="Not Ben's")
    approve_and_list(db, listing, add_version(db, listing, 1, defs_of(db, [("pack", PACK)]), price_minor=300))
    db.commit()
    _add(ana, PACK)
    _add_run(db, ana.org_id, "run_old", spent=2400)  # a 300 fee would be refused by the cap
    db.commit()
    res = _start(ana, PACK)
    assert res.status_code == 202, res.text
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", res.json()["id"])
    assert row["snapshot"]["fees"] == {"pack": None, "agents": {}}
    assert _fees(db) == []


def test_a_pin_the_snapshot_cannot_honour_is_unavailable(ana, ben, db):  # noqa: F811
    key, _, version = _listed(db, ana.org_id)
    _add(ben, key)
    # The approved bundle names a workflow version the registry lacks: the pin fails in build_snapshot.
    bundle = [{**d, "version": 99} if d["kind"] == "workflow" else d for d in _bundle(db, key)]
    db.execute("UPDATE listing_versions SET definitions = %s WHERE id = %s", (Jsonb(bundle), version))
    db.commit()
    res = _start(ben, key)
    assert res.status_code == 409 and res.json()["code"] == "PACK_UNAVAILABLE", res.text
    assert _fees(db) == []


def test_an_unrelated_lookup_error_is_not_called_unavailable(ana, db, monkeypatch):  # noqa: F811
    _add(ana, PACK)

    def broken(*args, **kwargs):
        raise LookupError("a bug, not an unavailable pack")

    monkeypatch.setattr(fees, "pack_fee_minor", broken)
    with pytest.raises(LookupError, match="a bug"):  # a 500, never 409 PACK_UNAVAILABLE
        _start(ana, PACK)


def _hold(db, org_id: str, key: str, pack_version: int, listing_version: str | None) -> None:
    db.execute(
        "UPDATE installations SET pack_version = %s, listing_version_id = %s "
        "WHERE org_id = %s AND pack_slug = %s",
        (pack_version, listing_version, org_id, key),
    )
    db.commit()


def test_a_bundle_pinning_another_pack_version_than_the_hire_fails_clearly(ana, ben, db):  # noqa: F811
    key, listing, _ = _listed(db, ana.org_id)
    _add(ben, key)  # the hire holds pack version 1
    v = registry.latest(db, "pack", key)
    d = Definition(
        kind="pack",
        key=key,
        body={**v.body, "name": "Acme recon two"},
        files=dict(v.files),
        path=path_for("pack", key),
    )
    registry.publish(db, d, "test", "version two", source=registry.BUILDER)
    bad = _approve_again(
        db, key, listing, _bundle(db, key), price=250
    )  # at version 1, its bundle names pack 2
    _hold(db, ben.org_id, key, 1, bad)
    res = _start(ben, key)
    assert res.status_code == 409 and res.json()["code"] == "PACK_UNAVAILABLE", res.text
    assert _fees(db) == []


def test_an_installation_holding_no_listing_version_fails_closed(ana, ben, db):  # noqa: F811
    key, _, _ = _listed(db, ana.org_id)
    _add(ben, key)
    # No listing version held: never the newest approved one at its pack version, the run is refused.
    _hold(db, ben.org_id, key, 1, None)
    res = _start(ben, key)
    assert res.status_code == 409 and res.json()["code"] == "PACK_UNAVAILABLE", res.text
    assert _rows(db, "SELECT id FROM runs WHERE org_id = %s", ben.org_id) == [] and _fees(db) == []


@pytest.mark.parametrize("update", ["pack_version", "contract_only"])
def test_an_update_landing_mid_start_never_runs_free(ana, ben, db, monkeypatch, update):  # noqa: F811
    key, listing, _ = _listed(db, ana.org_id, price=250)
    _add(ben, key)
    if update == "pack_version":
        newer, pack_version, price = _approve_v2(db, key, listing, price=400), 2, 400
    else:
        newer, pack_version, price = _approve_again(db, key, listing, _bundle(db, key), price=500), 1, 500
    real = live_work._listed_terms

    def racing(*args, **kwargs):
        terms = real(*args, **kwargs)  # pins and fee read at the version held so far
        _hold(db, ben.org_id, key, pack_version, newer)  # an update commits before the run is inserted
        return terms

    monkeypatch.setattr(live_work, "_listed_terms", racing)
    res = _start(ben, key)
    assert res.status_code == 409 and res.json()["code"] == "PACK_UNAVAILABLE", res.text
    assert _rows(db, "SELECT id FROM runs WHERE org_id = %s", ben.org_id) == [] and _fees(db) == []
    monkeypatch.setattr(live_work, "_listed_terms", real)
    again = _start(ben, key)  # started again, the run pins and pays the version now held
    assert again.status_code == 202, again.text
    assert _fees(db) == [(again.json()["id"], "pack_run", price, newer, ben.org_id)]
