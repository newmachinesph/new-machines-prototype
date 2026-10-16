"""Sub-project C, part 7: Studio packs. A team pack is built, saved as versions, exported and imported as
workflow.yaml, and added and run from the org's own marketplace, and only there."""

import threading
from pathlib import Path

from app import live_connections, real_runs, settings, studio
from app.auth import Actor
from app.defs import owners, registry
from app.errors import ApiProblem
from app.models.studio import BuilderIssue, PackDraft, SavePackRequest
from tests.team_seed import TEAM_AGENT, invoice_nudges
from tests.test_live_catalog import As, _rows, ana, ben, live, starts  # noqa: F401

AS_OF = {"as_of": "2026-10-13"}


def _base(user: As, org_id: str | None = None) -> str:
    return f"/v1/organizations/{org_id or user.org_id}/studio"


def _agent(user: As) -> str:
    body = TEAM_AGENT.model_dump(by_alias=True, exclude_none=True)
    res = user.post(f"{_base(user)}/agents", json=body)
    assert res.status_code == 201, res.text
    return res.json()["key"]


def _draft(agent: str, **changes) -> dict:
    return invoice_nudges(agent).model_copy(update=changes).model_dump(by_alias=True, exclude_none=True)


def _create(user: As) -> tuple[str, dict]:
    draft = _draft(_agent(user))
    res = user.post(f"{_base(user)}/packs", json=draft)
    assert res.status_code == 201, res.text
    return res.json()["key"], draft


def test_a_pack_is_created_and_read_back_as_its_draft(ana):  # noqa: F811
    key, draft = _create(ana)
    assert key == owners.org_key(ana.org_id, "invoice-nudges")
    pack = ana.get(f"{_base(ana)}/packs/{key}").json()
    assert (pack["version"], pack["added"]) == (1, False) and pack["draft"] == draft
    [listed] = ana.get(f"{_base(ana)}/packs").json()
    assert (listed["key"], listed["name"], listed["steps"], listed["added"]) == (
        key,
        "Invoice nudges",
        12,
        False,
    )
    [agent] = ana.get(f"{_base(ana)}/agents").json()
    assert agent["usedBy"] == ["Invoice nudges"]


def test_a_pack_with_problems_is_refused_naming_each_step(ana):  # noqa: F811
    draft = _draft(_agent(ana))
    draft["steps"][5]["routes"] = {"next": "send"}  # the writer step skips the approval
    check = ana.post(f"{_base(ana)}/packs:validate", json=draft).json()
    assert check["ok"] is False and {"send", "approve"} <= {i.get("step") for i in check["issues"]}
    res = ana.post(f"{_base(ana)}/packs", json=draft)
    assert res.status_code == 422 and res.json()["code"] == "INVALID_DEFINITION"
    assert "send" in {e["key"] for e in res.json()["errors"]}
    assert ana.get(f"{_base(ana)}/packs").json() == []


def test_a_validator_error_is_mapped_to_its_step(ana):  # noqa: F811
    draft = _draft(_agent(ana))
    draft["steps"][2]["config"]["inputs"]["as_of"] = "=input.as_of +"  # CEL that does not compile
    issues = ana.post(f"{_base(ana)}/packs:validate", json=draft).json()["issues"]
    assert [(i["step"], i["path"].split("/")[0]) for i in issues] == [("plan", "workflow")]


def test_a_pack_is_saved_as_new_versions(ana):  # noqa: F811
    key, draft = _create(ana)
    same = ana.post(f"{_base(ana)}/packs/{key}", json={"draft": draft, "baseVersion": 1})
    assert same.status_code == 200 and same.json()["version"] == 1
    edited = {**draft, "outcome": "Every open invoice gets a nudge."}
    saved = ana.post(f"{_base(ana)}/packs/{key}", json={"draft": edited, "baseVersion": 1})
    assert (
        saved.json()["version"] == 2
        and saved.json()["draft"]["outcome"] == "Every open invoice gets a nudge."
    )
    stale = ana.post(f"{_base(ana)}/packs/{key}", json={"draft": draft, "baseVersion": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"


def test_the_workflow_yaml_exports_and_imports_back_to_the_same_steps(ana):  # noqa: F811
    key, draft = _create(ana)
    exported = ana.get(f"{_base(ana)}/packs/{key}/workflow").json()["yaml"]
    assert f"workflow_id: {key}" in exported
    imported = ana.post(f"{_base(ana)}/workflow:import", json={"yaml": exported}).json()
    assert imported["issues"] == [] and imported["entryStep"] == "start"
    assert imported["steps"] == draft["steps"]


def test_a_workflow_using_platform_rules_imports_with_the_rules_inlined(ana):  # noqa: F811
    # overdue-invoices is the seed overdue pack's decision rules definition, visible to every org.
    text = (
        "kind: workflow\nkey: x\nentry_node_id: start\nnodes:\n"
        "  - {id: start, type: trigger, version: '1', config: {}, routes: {next: check}}\n"
        "  - {id: check, type: decision, version: '1', config: {rules: overdue-invoices}, "
        "routes: {nothing: done, human_review: done}}\n"
        "  - {id: done, type: end, version: '1', config: {status: COMPLETED}}\n"
    )
    imported = ana.post(f"{_base(ana)}/workflow:import", json={"yaml": text}).json()
    check = imported["steps"][1]
    assert check["config"] == {} and check["rules"]["question"] == "Are there overdue invoices to follow up?"


def test_unreadable_yaml_is_refused(ana):  # noqa: F811
    for text, detail in (("nodes: [", "YAML is not valid"), ("name: x\n", "The YAML has no nodes.")):
        res = ana.post(f"{_base(ana)}/workflow:import", json={"yaml": text})
        assert res.status_code == 422 and res.json()["code"] == "INVALID_YAML"
        assert res.json()["detail"].startswith(detail)
    broken = "nodes:\n  - {id: Start, type: trigger}\n  - just text\n"
    imported = ana.post(f"{_base(ana)}/workflow:import", json={"yaml": broken}).json()
    assert [i["path"] for i in imported["issues"]] == ["nodes[0]", "nodes[1]"]


def test_a_team_pack_is_added_and_run_from_its_own_marketplace_only(db, ana, ben, starts):  # noqa: F811
    key, _ = _create(ana)
    market = {p["slug"]: p for p in ana.get("/v1/workflow-packs").json()}
    assert market[key]["builtByTeam"] is True and market[key]["certified"] is False
    assert key not in {p["slug"] for p in ben.get("/v1/workflow-packs").json()}
    added = ana.post(
        f"/v1/organizations/{ana.org_id}/agent-installations", json={"packSlug": key, "capMinor": 2000}
    )
    assert added.status_code == 201, added.text
    assert ana.get(f"{_base(ana)}/packs/{key}").json()["added"] is True
    for app in ("stripe", "gmail"):
        assert ana.connect(app).status_code == 200
    run = ana.post("/v1/workflow-runs", json={"packSlug": key, "input": AS_OF, "budgetMinor": 1000})
    assert run.status_code == 202, run.text
    assert starts.calls[-1][1:] == (ana.org_id, AS_OF)
    assert _rows(db, "SELECT org_id, pack_slug FROM runs") == [{"org_id": ana.org_id, "pack_slug": key}]
    other = ben.post("/v1/workflow-runs", json={"packSlug": key, "input": AS_OF, "budgetMinor": 1000})
    assert other.status_code == 404


def test_another_org_never_sees_or_changes_an_orgs_packs(ana, ben):  # noqa: F811
    key, draft = _create(ana)
    assert ben.get(_base(ben, ana.org_id) + "/packs").status_code == 403
    assert ben.get(f"{_base(ben)}/packs").json() == []
    for path in (f"/packs/{key}", f"/packs/{key}/workflow"):
        assert ben.get(_base(ben) + path).status_code == 404
    assert ben.post(f"{_base(ben)}/packs/{key}", json={"draft": draft}).status_code == 404


def test_another_orgs_agent_key_is_missing_to_a_pack_draft(ana, ben):  # noqa: F811
    theirs = _agent(ana)
    check = ben.post(f"{_base(ben)}/packs:validate", json=_draft(theirs)).json()
    assert check["ok"] is False and [i["step"] for i in check["issues"]] == ["plan"]
    assert ben.post(f"{_base(ben)}/packs", json=_draft(theirs)).status_code == 422


# --- a pack the org has added keeps its connection grants in step with every save (preflight #5) ----------


def _grants(user: As) -> dict[str, set[tuple[str, str]]]:
    """{app key: {(install, capability)}} of the org's connections."""
    return {
        c["key"]: {(g["install"], g["capability"]) for g in c["grants"]}
        for c in user.get("/v1/connections").json()
    }


def _inbox_step() -> dict:
    """A connector step that reads Gmail: a tool the first version of the pack did not use."""
    return {
        "id": "inbox",
        "type": "connector",
        "config": {"tool": "gmail.list_threads", "args": {"query": "invoice", "max_results": 10}},
        "routes": {"ok": "invoices", "denied": "failed", "error": "failed"},
        "rules": None,
    }


def test_saving_an_added_pack_renames_its_grants_and_grants_its_new_tools(ana, db):  # noqa: F811
    key, draft = _create(ana)
    added = ana.post(
        f"/v1/organizations/{ana.org_id}/agent-installations", json={"packSlug": key, "capMinor": 2000}
    )
    assert added.status_code == 201, added.text
    for app in ("stripe", "gmail"):
        assert ana.connect(app).status_code == 200
    assert _grants(ana) == {
        "stripe": {("Invoice nudges", "invoices.read")},
        "gmail": {("Invoice nudges", "mail.write")},
    }
    revoke = {"app": "gmail", "install": "Invoice nudges", "capability": "mail.write"}
    assert ana.delete("/v1/grants", params=revoke).status_code == 204
    steps = [{**draft["steps"][0], "routes": {"next": "inbox"}}, _inbox_step(), *draft["steps"][1:]]
    renamed = {**draft, "name": "Invoice reminders", "steps": steps}
    saved = ana.post(f"{_base(ana)}/packs/{key}", json={"draft": renamed, "baseVersion": 1})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2 and saved.json()["draft"]["name"] == "Invoice reminders"
    # The grants follow the new name, the new tool is granted, and the revoked grant stays revoked under it.
    assert _grants(ana) == {
        "stripe": {("Invoice reminders", "invoices.read")},
        "gmail": {("Invoice reminders", "mail.read")},
    }
    gmail = next(c for c in ana.get("/v1/connections").json() if c["key"] == "gmail")
    assert [(r["install"], r["capability"]) for r in gmail["revoked"]] == [
        ("Invoice reminders", "mail.write")
    ]
    [row] = _rows(db, "SELECT pack_version FROM installations WHERE org_id = %s", ana.org_id)
    assert row == {"pack_version": 2}
    assert [p["name"] for p in ana.get("/v1/workflow-packs").json() if p["slug"] == key] == [
        "Invoice reminders"
    ]
    # An unchanged save, and a save of a pack the org has not added, leave the grants alone.
    same = ana.post(f"{_base(ana)}/packs/{key}", json={"draft": renamed, "baseVersion": 2})
    assert same.status_code == 200 and same.json()["version"] == 2
    assert _grants(ana)["stripe"] == {("Invoice reminders", "invoices.read")}


def test_a_pack_not_added_leaves_the_connections_alone(ana):  # noqa: F811
    ana.hire()
    assert ana.connect("stripe").status_code == 200
    key, draft = _create(ana)
    saved = ana.post(
        f"{_base(ana)}/packs/{key}", json={"draft": {**draft, "name": "Nudges"}, "baseVersion": 1}
    )
    assert saved.status_code == 200 and saved.json()["version"] == 2
    assert {g[0] for g in _grants(ana)["stripe"]} == {"Order & Payment Reconciliation"}


# --- a team agent's save carries into the packs that use it (final review I1) -----------------------------


def _agent_body(**changes) -> dict:
    return TEAM_AGENT.model_copy(update=changes).model_dump(by_alias=True, exclude_none=True)


def test_saving_a_team_agent_rebuilds_and_regrants_the_packs_that_use_it(ana, db):  # noqa: F811
    key, _ = _create(ana)
    agent = owners.org_key(ana.org_id, "invoice-helper")
    assert _add(ana, key).status_code == 201
    assert ana.connect("stripe").status_code == 200
    assert _grants(ana)["stripe"] == {("Invoice nudges", "invoices.read")}
    # The agent gains a tool whose capability the pack's contract did not cover.
    more = _agent_body(tools=["stripe.list_invoices", "stripe.list_charges"])
    saved = ana.post(f"{_base(ana)}/agents/{agent}", json={"draft": more, "baseVersion": 1})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2
    pack = ana.get(f"{_base(ana)}/packs/{key}").json()
    assert pack["version"] == 2 and pack["draft"]["name"] == "Invoice nudges"
    db.commit()
    contract = registry.latest(db, "contract", key).body
    assert contract["authorization"]["tool_capabilities"] == ["invoices.read", "mail.write", "payments.read"]
    assert _grants(ana)["stripe"] == {
        ("Invoice nudges", "invoices.read"),
        ("Invoice nudges", "payments.read"),
    }
    [row] = _rows(db, "SELECT pack_version FROM installations WHERE org_id = %s", ana.org_id)
    assert row == {"pack_version": 2}
    # A save that changes nothing the pack is built from leaves the pack at its version.
    reworded = {**more, "summary": "Plans one nudge per open invoice."}
    assert (
        ana.post(f"{_base(ana)}/agents/{agent}", json={"draft": reworded, "baseVersion": 2}).json()["version"]
        == 3
    )
    assert ana.get(f"{_base(ana)}/packs/{key}").json()["version"] == 2


def test_an_agent_save_that_would_break_a_pack_is_refused_naming_the_pack(ana, monkeypatch):  # noqa: F811
    key, _ = _create(ana)
    agent = owners.org_key(ana.org_id, "invoice-helper")
    broken = [BuilderIssue(step="plan", path="steps[2]", message="The step no longer fits the agent.")]
    monkeypatch.setattr(studio.build, "pack_issues", lambda *args, **kwargs: broken)
    more = _agent_body(tools=["stripe.list_invoices", "stripe.list_charges"])
    res = ana.post(f"{_base(ana)}/agents/{agent}", json={"draft": more, "baseVersion": 1})
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "INVALID_DEFINITION" and res.json()["detail"].startswith("Invoice nudges ")
    assert res.json()["errors"] == [
        {
            "kind": "pack",
            "key": "Invoice nudges",
            "path": "steps[2]",
            "message": "The step no longer fits the agent.",
        }
    ]
    # Nothing was published: neither the agent nor the pack.
    assert ana.get(f"{_base(ana)}/agents/{agent}").json()["version"] == 1
    assert ana.get(f"{_base(ana)}/packs/{key}").json()["version"] == 1


# --- importing a seed workflow ---------------------------------------------------------------------------


def test_a_seed_workflow_imports_with_its_failure_outcomes_routed_to_the_failed_end(ana):  # noqa: F811
    text = (Path(settings.defs_dir()) / "packs/order-payment-reconciliation/workflow.yaml").read_text("utf-8")
    imported = ana.post(f"{_base(ana)}/workflow:import", json={"yaml": text}).json()
    assert imported["issues"] == [] and imported["entryStep"] == "start"
    steps = {s["id"]: s for s in imported["steps"]}
    # The seed's connector nodes route only "next"; a step must route every outcome, so the failure ones go
    # to the workflow's FAILED end.
    assert steps["orders"]["routes"] == {"ok": "payments", "denied": "failed", "error": "failed"}
    assert steps["payments"]["routes"] == {"ok": "match", "denied": "failed", "error": "failed"}
    assert steps["failed"]["config"]["status"] == "FAILED"
    assert steps["check"]["config"] == {} and steps["check"]["rules"]["rules"]
    # A workflow without a FAILED end is imported as written: the builder's checks name what is missing.
    bare = (
        "nodes:\n"
        "  - {id: start, type: trigger, config: {}, routes: {next: orders}}\n"
        "  - {id: orders, type: connector, config: {tool: shopify.list_orders}, routes: {next: done}}\n"
        "  - {id: done, type: end, config: {status: COMPLETED}}\n"
    )
    imported = ana.post(f"{_base(ana)}/workflow:import", json={"yaml": bare}).json()
    assert imported["steps"][1]["routes"] == {"ok": "done"}


def test_odd_yaml_values_are_issues_not_errors(ana):  # noqa: F811
    odd = "nodes:\n  - {id: start, type: trigger, config: {}, routes: abc}\n"
    imported = ana.post(f"{_base(ana)}/workflow:import", json={"yaml": odd}).json()
    assert [i["path"] for i in imported["issues"]] == ["nodes[0]"]
    deep = "nodes: " + "[" * 10_000 + "]" * 10_000
    res = ana.post(f"{_base(ana)}/workflow:import", json={"yaml": deep})
    assert res.status_code == 422 and res.json()["code"] == "INVALID_YAML"
    assert res.json()["detail"] == "YAML is nested too deeply."


# --- fix round 1: names and races with saves ----------------------------------------------------------------


def _actor(user: As) -> Actor:
    me = user.get("/v1/me").json()
    return Actor(
        user_id="uid_ana", org_id=user.org_id, role="owner", email=me["email"], org_name=me["orgName"]
    )


def _add(user: As, key: str):
    return user.post(
        f"/v1/organizations/{user.org_id}/agent-installations", json={"packSlug": key, "capMinor": 2000}
    )


def _before_first(monkeypatch, module, name: str, action) -> None:
    """Run `action` once, right before the first call of `module.name` (a lock): another request that lands
    between a read and the lock that should have covered it."""
    original = getattr(module, name)
    pending = [action]

    def wrapper(*args, **kwargs):
        if pending:
            pending.pop()()
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)


def _renamed(draft: dict, name: str = "Invoice reminders") -> SavePackRequest:
    return SavePackRequest(draft=PackDraft.model_validate({**draft, "name": name}), base_version=1)


def test_validating_a_saved_pack_does_not_count_its_own_name(ana, ben):  # noqa: F811
    key, draft = _create(ana)
    check = ana.post(f"{_base(ana)}/packs:validate", params={"key": key}, json=draft).json()
    assert check == {"ok": True, "issues": []}
    as_new = ana.post(f"{_base(ana)}/packs:validate", json=draft).json()  # a second pack with that name
    assert [i["path"] for i in as_new["issues"]] == ["name"]
    theirs = ben.post(f"{_base(ben)}/packs:validate", params={"key": key}, json=draft)
    missing = ben.post(f"{_base(ben)}/packs:validate", params={"key": "nothing"}, json=draft)
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json()["detail"].replace(key, "") == missing.json()["detail"].replace("nothing", "")


def test_two_packs_created_at_once_with_the_same_name_get_one_refused(ana, monkeypatch):  # noqa: F811
    draft = _draft(_agent(ana))
    actor = _actor(ana)
    _before_first(
        monkeypatch, registry, "lock", lambda: studio.create_pack(actor, PackDraft.model_validate(draft))
    )
    res = ana.post(f"{_base(ana)}/packs", json=draft)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "INVALID_DEFINITION" and [e["path"] for e in res.json()["errors"]] == [
        "name"
    ]
    assert [p["key"] for p in ana.get(f"{_base(ana)}/packs").json()] == [
        owners.org_key(ana.org_id, "invoice-nudges")
    ]


def test_an_added_pack_with_a_run_in_progress_cannot_be_renamed(ana, db, starts):  # noqa: F811
    key, draft = _create(ana)
    assert _add(ana, key).status_code == 201
    for app in ("stripe", "gmail"):
        assert ana.connect(app).status_code == 200
    run = ana.post("/v1/workflow-runs", json={"packSlug": key, "input": AS_OF, "budgetMinor": 1000})
    assert run.status_code == 202, run.text
    renamed = {**draft, "name": "Invoice reminders"}
    res = ana.post(f"{_base(ana)}/packs/{key}", json={"draft": renamed, "baseVersion": 1})
    assert res.status_code == 409 and res.json()["code"] == "RUNS_IN_PROGRESS"
    assert res.json()["detail"] == "Finish or cancel the run of this pack in progress before renaming it."
    assert run.json()["id"] not in res.text
    assert ana.get(f"{_base(ana)}/packs/{key}").json()["version"] == 1
    assert _grants(ana)["stripe"] == {("Invoice nudges", "invoices.read")}
    # A save that keeps the name goes through meanwhile; the rename does once the run is over.
    edited = {**draft, "outcome": "Every open invoice gets a nudge."}
    saved = ana.post(f"{_base(ana)}/packs/{key}", json={"draft": edited, "baseVersion": 1})
    assert saved.status_code == 200 and saved.json()["version"] == 2
    db.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = %s", (run.json()["id"],))
    db.commit()
    # A sandbox test in progress does not hold the rename up: it never reads the grants.
    test = ana.post(f"{_base(ana)}/packs/{key}:test", json={"input": AS_OF})
    assert test.status_code == 202 and test.json()["sandboxTest"] is True
    saved = ana.post(
        f"{_base(ana)}/packs/{key}", json={"draft": {**edited, "name": "Invoice reminders"}, "baseVersion": 2}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 3
    assert _grants(ana)["stripe"] == {("Invoice reminders", "invoices.read")}


def test_a_run_starting_while_a_pack_is_renamed_is_counted(ana, starts, monkeypatch):  # noqa: F811
    """The start holds the installation (FOR SHARE) while it pins its snapshot, so a rename either waits for
    it and counts it, or lands first and the start pins the new name."""
    key, draft = _create(ana)
    assert _add(ana, key).status_code == 201
    for app in ("stripe", "gmail"):
        assert ana.connect(app).status_code == 200
    actor, outcome = _actor(ana), {}

    def rename() -> None:
        try:
            studio.save_pack(actor, key, _renamed(draft))
            outcome["code"] = "saved"
        except ApiProblem as problem:
            outcome["code"] = problem.code

    pin = real_runs.build_snapshot
    saver = threading.Thread(target=rename)

    def pin_while_renaming(conn, *args, **kwargs):
        monkeypatch.setattr(real_runs, "build_snapshot", pin)
        saver.start()
        saver.join(0.5)  # the rename reaches the installation row and waits there for the start
        return pin(conn, *args, **kwargs)

    monkeypatch.setattr(real_runs, "build_snapshot", pin_while_renaming)
    run = ana.post("/v1/workflow-runs", json={"packSlug": key, "input": AS_OF, "budgetMinor": 1000})
    assert run.status_code == 202, run.text
    saver.join(10)
    assert outcome == {"code": "RUNS_IN_PROGRESS"}
    assert ana.get(f"{_base(ana)}/packs/{key}").json()["draft"]["name"] == "Invoice nudges"
    assert _grants(ana)["stripe"] == {("Invoice nudges", "invoices.read")}


def test_a_connect_that_races_a_rename_grants_under_the_new_name(ana, monkeypatch):  # noqa: F811
    key, draft = _create(ana)
    assert _add(ana, key).status_code == 201
    actor = _actor(ana)
    _before_first(
        monkeypatch, live_connections, "_lock", lambda: studio.save_pack(actor, key, _renamed(draft))
    )
    assert ana.connect("stripe").status_code == 200
    assert _grants(ana)["stripe"] == {("Invoice reminders", "invoices.read")}


def test_allowing_a_grant_again_that_races_a_rename_restores_it_under_the_new_name(ana, monkeypatch):  # noqa: F811
    key, draft = _create(ana)
    assert _add(ana, key).status_code == 201
    assert ana.connect("gmail").status_code == 200
    revoke = {"app": "gmail", "install": "Invoice nudges", "capability": "mail.write"}
    assert ana.delete("/v1/grants", params=revoke).status_code == 204
    actor = _actor(ana)
    _before_first(
        monkeypatch, live_connections, "_lock", lambda: studio.save_pack(actor, key, _renamed(draft))
    )
    allowed = ana.post("/v1/grants", params={**revoke, "install": "Invoice reminders"})
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["revoked"] == []
    assert _grants(ana)["gmail"] == {("Invoice reminders", "mail.write")}


def test_adding_a_pack_that_races_a_save_pins_the_saved_version(ana, db, monkeypatch):  # noqa: F811
    key, draft = _create(ana)
    assert ana.connect("stripe").status_code == 200
    actor = _actor(ana)
    _before_first(monkeypatch, registry, "lock", lambda: studio.save_pack(actor, key, _renamed(draft)))
    assert _add(ana, key).status_code == 201
    [row] = _rows(db, "SELECT pack_version FROM installations WHERE org_id = %s", ana.org_id)
    assert row == {"pack_version": 2}
    assert _grants(ana)["stripe"] == {("Invoice reminders", "invoices.read")}
