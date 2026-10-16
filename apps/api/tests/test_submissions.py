"""Sub-project D, part 19: submitting a Studio agent or pack. The checks stop a bad submission before ops sees
it; a pack with a private agent is refused with the agents to submit first; the sandbox run decides when the
version reaches the queue; every read is the publisher's own."""

import pytest

from app import listing_checks, listings
from app.defs import owners, registry
from app.defs.model import Definition, path_for
from app.errors import ApiProblem
from tests.publishing_seed import add_listing, add_publisher, add_version, approve_and_list, defs_of
from tests.team_seed import _own, clone_agent
from tests.team_seed import clone_pack as _clone_pack
from tests.test_live_catalog import INPUT, _rows, ana, ben, live, starts  # noqa: F401

PACK = "order-payment-reconciliation"


def clone_pack(db, slug: str, org_id: str, name: str, title: str | None = None) -> str:
    """The platform pack copied as the org's own, as the Studio would save it: a connector's denied and error
    outcomes go to the FAILED end (a seed workflow leaves them to the runtime, which the builder refuses)."""
    key = _clone_pack(db, slug, org_id, name, title)
    workflow = registry.latest(db, "workflow", key).body
    failed = next(
        n["id"] for n in workflow["nodes"] if n["type"] == "end" and n["config"]["status"] == "FAILED"
    )
    nodes = [
        {**n, "routes": {"denied": failed, "error": failed, **n["routes"]}} if n["type"] == "connector" else n
        for n in workflow["nodes"]
    ]
    _own(db, org_id, "workflow", key, {**workflow, "nodes": nodes})
    db.commit()
    return key


def _base(user) -> str:
    return f"/v1/organizations/{user.org_id}/studio"


@pytest.fixture
def publisher(ana, db):  # noqa: F811
    add_publisher(db, ana.org_id, "Acme Labs")
    db.commit()
    return ana


def _submit(user, kind: str, key: str, **body):
    return user.post(f"{_base(user)}/{kind}s/{key}/submissions", json={"priceMinor": 250, **body})


def _bundle(db, version_id: str) -> list[dict]:
    [row] = _rows(db, "SELECT definitions FROM listing_versions WHERE id = %s", version_id)
    return row["definitions"]


def test_a_workspace_without_a_profile_cannot_submit(ana, db):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    db.commit()
    res = _submit(ana, "pack", key, input=INPUT)
    assert res.status_code == 409 and res.json()["code"] == "PUBLISHER_PROFILE_REQUIRED"


def test_members_cannot_submit(publisher, db):
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    db.execute("UPDATE org_members SET role = 'member' WHERE user_id = 'uid_ana'")
    db.commit()
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED"


def test_a_workspace_that_turned_publishing_off_cannot_submit(ana, db):  # noqa: F811
    add_publisher(db, ana.org_id, "Acme Labs", enabled=False)
    key = clone_pack(db, PACK, ana.org_id, "recon")
    res = _submit(ana, "pack", key, input=INPUT)
    assert res.status_code == 409 and res.json()["code"] == "PUBLISHER_PROFILE_REQUIRED"
    assert _rows(db, "SELECT 1 FROM listings") == []


def test_a_pack_starts_its_sandbox_check_and_waits_in_checking(publisher, starts, db):  # noqa: F811
    key = clone_pack(db, PACK, publisher.org_id, "recon", title="Acme recon")
    db.commit()
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 201, res.text
    detail = res.json()
    [version] = detail["versions"]
    assert (detail["name"], detail["status"], version["status"]) == ("Acme recon", "pending", "checking")
    checks = {c["name"]: c for c in version["checks"]}
    assert checks["definition"]["state"] == checks["agents"]["state"] == "passed"
    assert checks["sandbox"]["state"] == "running" and checks["sandbox"]["runId"] == starts.calls[-1][0]
    definitions = _bundle(db, version["id"])
    assert {(d["kind"], d["key"]) for d in definitions} >= {
        ("pack", key),
        ("workflow", key),
        ("contract", key),
    }
    assert all(d["kind"] != "agent" for d in definitions)
    again = _submit(publisher, "pack", key, input=INPUT)
    assert again.status_code == 409 and again.json()["code"] == "SUBMISSION_OPEN"
    assert len(starts.calls) == 1  # refused before a second sandbox run


def test_a_bundle_never_holds_a_platform_definition(publisher, starts, db):  # noqa: F811
    """The copy still uses the platform's agents, schemas and decision rules: none of them is in the bundle,
    as a platform definition in it would override that definition for every buyer."""
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    db.commit()
    pack = _submit(publisher, "pack", key, input=INPUT).json()
    called = _submit(publisher, "agent", agent, input={"note": "sample"}).json()
    for detail in (pack, called):
        definitions = _bundle(db, detail["latest"]["id"])
        assert definitions and all(owners.in_org(d["key"], publisher.org_id) for d in definitions)
    assert {(d["kind"], d["key"]) for d in _bundle(db, called["latest"]["id"])} == {("agent", agent)}


def test_the_version_moves_to_review_when_its_sandbox_run_completes(publisher, starts, db):  # noqa: F811
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    db.commit()
    listing = _submit(publisher, "pack", key, input=INPUT).json()["id"]
    db.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = %s", (starts.calls[-1][0],))
    db.commit()
    detail = publisher.get(f"{_base(publisher)}/listings/{listing}").json()
    assert detail["latest"]["status"] == "in_review"


def test_a_failed_sandbox_check_frees_the_listing_for_a_new_version(publisher, starts, db):  # noqa: F811
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    db.commit()
    listing = _submit(publisher, "pack", key, input=INPUT).json()["id"]
    db.execute("UPDATE runs SET status = 'FAILED' WHERE id = %s", (starts.calls[-1][0],))
    db.commit()
    again = _submit(publisher, "pack", key, input=INPUT)
    assert again.status_code == 201, again.text
    statuses = [v["status"] for v in again.json()["versions"]]
    assert again.json()["id"] == listing and statuses == ["checking", "checks_failed"]


def test_a_completed_sandbox_test_of_the_same_version_is_reused(publisher, starts, db):  # noqa: F811
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    db.commit()
    test = publisher.post(f"{_base(publisher)}/packs/{key}:test", json={"input": INPUT})
    assert test.status_code == 202, test.text
    db.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = %s", (test.json()["id"],))
    db.commit()
    res = _submit(publisher, "pack", key, input={"since": "2026-01-01", "until": "2026-01-02"})
    assert res.status_code == 201, res.text
    assert res.json()["latest"]["status"] == "in_review" and len(starts.calls) == 1
    [run] = _rows(db, "SELECT input FROM runs WHERE id = %s", test.json()["id"])
    [version] = _rows(
        db, "SELECT check_input FROM listing_versions WHERE id = %s", res.json()["latest"]["id"]
    )
    assert version["check_input"] == run["input"]  # the input the reused test ran with, not the body's


def test_an_oversized_input_is_refused_on_every_path(publisher, starts, db):  # noqa: F811
    huge = {"note": "x" * 10_001}
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    test = publisher.post(f"{_base(publisher)}/packs/{key}:test", json={"input": INPUT})
    db.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = %s", (test.json()["id"],))
    db.commit()
    for kind, item in (("agent", agent), ("pack", key)):  # the pack's completed test would be reused
        res = _submit(publisher, kind, item, input=huge)
        assert res.status_code == 422 and res.json()["code"] == "INVALID_INPUT", res.text
    assert _rows(db, "SELECT 1 FROM listing_versions") == [] and len(starts.calls) == 1


def test_an_agent_check_may_have_a_budget_below_the_pack_floor(publisher, starts, db):  # noqa: F811
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    res = _submit(publisher, "agent", agent, input={"note": "sample"}, budgetMinor=50)
    assert res.status_code == 201, res.text
    [run] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", starts.calls[-1][0])
    assert run["snapshot"]["budget_minor"] == 50


def test_a_definition_saved_while_its_check_starts_is_not_recorded(publisher, starts, db, monkeypatch):  # noqa: F811
    from app import studio

    key = clone_pack(db, PACK, publisher.org_id, "recon")
    start = studio.sandbox_run

    def saved_meanwhile(actor, slug, body, **kwargs):
        pack = registry.latest(db, "pack", slug)
        _own(db, publisher.org_id, "pack", slug, {**pack.body, "outcome": "Saved again."})
        db.commit()
        return start(actor, slug, body, **kwargs)

    monkeypatch.setattr(studio, "sandbox_run", saved_meanwhile)
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 409 and res.json()["code"] == "VERSION_CONFLICT"
    assert _rows(db, "SELECT 1 FROM listing_versions") == []


def test_a_pack_may_use_the_orgs_own_listed_agent(publisher, starts, db):  # noqa: F811
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    listing = add_listing(db, "agent", agent, publisher.org_id, name="Matcher")
    approve_and_list(db, listing, add_version(db, listing, 1, defs_of(db, [("agent", agent)])))
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    pack = registry.latest(db, "pack", key)
    _own(db, publisher.org_id, "pack", key, {**pack.body, "agents": [*pack.body.get("agents", []), agent]})
    db.commit()
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 201, res.text
    checks = {c["name"]: c["state"] for c in res.json()["latest"]["checks"]}
    assert checks["agents"] == "passed"
    assert all(d["kind"] != "agent" for d in _bundle(db, res.json()["latest"]["id"]))


def test_a_publishers_listing_check_never_pays_for_its_own_listed_agent(publisher, starts, db):  # noqa: F811
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    listing = add_listing(db, "agent", agent, publisher.org_id, name="Matcher")
    version = add_version(db, listing, 1, defs_of(db, [("agent", agent)]), price_minor=30)
    approve_and_list(db, listing, version)
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    pack = registry.latest(db, "pack", key)
    _own(db, publisher.org_id, "pack", key, {**pack.body, "agents": [*pack.body.get("agents", []), agent]})
    db.commit()
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 201, res.text
    [run] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", starts.calls[-1][0])
    assert ("agent", agent) in {(v["kind"], v["key"]) for v in run["snapshot"]["versions"]}
    assert run["snapshot"]["fees"] == {"pack": None, "agents": {}}


def test_a_pack_with_a_private_agent_names_the_agents_to_submit_first(publisher, db):
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    pack = registry.latest(db, "pack", key)  # the pack now lists the org's private agent
    _own(db, publisher.org_id, "pack", key, {**pack.body, "agents": [*pack.body.get("agents", []), agent]})
    db.commit()
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 422 and res.json()["code"] == "PRIVATE_AGENTS"
    assert res.json()["detail"] == "These agents need to be listed first: Matcher (not submitted)."
    assert _rows(db, "SELECT 1 FROM listing_versions") == []


def test_a_pack_that_cannot_be_put_together_says_what_to_fix(db, monkeypatch):
    def missing(*_args, **_kwargs):
        raise LookupError("agent/x is not available")

    monkeypatch.setattr(listing_checks, "build_snapshot", missing)
    with pytest.raises(ApiProblem) as refused:
        listing_checks._pack_checks(db, "org_x", "org-x--p")
    assert refused.value.code == "PACK_UNAVAILABLE"
    assert "save the pack again" in refused.value.detail


def test_a_private_agent_already_in_review_is_named_as_in_review(publisher, db):
    """An agent waiting for review needs listing, not another submission: the refusal says which is which."""
    waiting = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    listing = add_listing(db, "agent", waiting, publisher.org_id, name="Matcher")
    add_version(db, listing, 1, defs_of(db, [("agent", waiting)]))  # in review
    fresh = clone_agent(db, "finance-agent", publisher.org_id, "helper", title="Helper")
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    pack = registry.latest(db, "pack", key)
    agents = [*pack.body.get("agents", []), waiting, fresh]
    _own(db, publisher.org_id, "pack", key, {**pack.body, "agents": agents})
    db.commit()
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 422 and res.json()["code"] == "PRIVATE_AGENTS"
    detail = res.json()["detail"]
    assert detail == "These agents need to be listed first: Helper (not submitted), Matcher (in review)."
    assert "Submit these agents" not in detail


def test_a_private_agent_whose_listing_never_had_a_version_reads_as_not_submitted(publisher, db):
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    add_listing(db, "agent", agent, publisher.org_id, name="Matcher")  # a listing, but nothing sent yet
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    pack = registry.latest(db, "pack", key)
    _own(db, publisher.org_id, "pack", key, {**pack.body, "agents": [*pack.body.get("agents", []), agent]})
    db.commit()
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 422 and res.json()["code"] == "PRIVATE_AGENTS"
    assert res.json()["detail"] == "These agents need to be listed first: Matcher (not submitted)."


def test_an_agent_is_checked_by_a_sandbox_call_that_is_never_saved(publisher, starts, db):  # noqa: F811
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    db.commit()
    res = _submit(publisher, "agent", agent, priceMinor=30, input={"note": "sample"})
    assert res.status_code == 201, res.text
    run_id, org, _ = starts.calls[-1]
    assert org == publisher.org_id
    [run] = _rows(db, "SELECT pack_slug, snapshot, projection FROM runs WHERE id = %s", run_id)
    assert run["projection"].get("sandboxTest") is True
    assert run["snapshot"]["fees"] == {"pack": None, "agents": {}}  # the publisher's own check is free
    check = run["pack_slug"]
    assert registry.latest(db, "pack", check) is None  # the check pack is never published
    assert {(v["kind"], v["key"]) for v in run["snapshot"]["versions"]} >= {("agent", agent)}


def test_invalid_definitions_are_refused_with_their_issues(publisher, db, monkeypatch):
    from app import studio

    key = clone_pack(db, PACK, publisher.org_id, "recon")
    db.commit()
    issue = studio.BuilderIssue(path="steps", message="A step has no route.")
    monkeypatch.setattr(studio, "_pack_issues", lambda *a, **k: [issue])
    res = _submit(publisher, "pack", key, input=INPUT)
    assert res.status_code == 422 and res.json()["code"] == "INVALID_DEFINITION"
    assert _rows(db, "SELECT 1 FROM listings") == []


def test_listings_are_the_publishers_own(publisher, ben, starts, db):  # noqa: F811
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    db.commit()
    listing = _submit(publisher, "pack", key, input=INPUT).json()["id"]
    assert [row["id"] for row in publisher.get(f"{_base(publisher)}/listings").json()] == [listing]
    assert ben.get(f"{_base(ben)}/listings").json() == []
    assert ben.get(f"{_base(ben)}/listings/{listing}").status_code == 404
    denied = ben.get(f"{_base(publisher)}/listings")
    assert denied.status_code == 403 and denied.json()["code"] == "TENANT_SCOPE_DENIED"
    assert _submit(ben, "pack", key, input=INPUT).status_code in (403, 404, 409)  # never ana's pack
    assert listings.find(db, "pack", key)["publisher_org_id"] == publisher.org_id


def test_another_publisher_cannot_submit_a_workspaces_pack(publisher, ben, starts, db):  # noqa: F811
    key = clone_pack(db, PACK, publisher.org_id, "recon")
    add_publisher(db, ben.org_id, "Ben Labs")
    db.commit()
    res = _submit(ben, "pack", key, input=INPUT)
    assert res.status_code == 404 and res.json()["code"] == "NOT_FOUND"
    assert _rows(db, "SELECT 1 FROM listings") == [] and starts.calls == []


def test_the_agent_check_pack_passes_the_builders_and_the_validators_checks(publisher, db):
    from app import listing_checks, studio
    from app import studio_build as build
    from app.auth import Actor

    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    db.commit()
    actor = Actor(user_id="uid_ana", org_id=publisher.org_id, org_name="Acme")
    check = listing_checks.check_pack_key(publisher.org_id)
    ctx = studio._context(db, publisher.org_id)
    draft = listing_checks._check_draft(agent, "Matcher", listing_checks.CHECK_BUDGET_MINOR)
    issues = build.pack_issues(draft, ctx.tools, ctx.agents, set(ctx.spaces), set(ctx.schemas), names=[])
    unsaved = listing_checks._unsaved(actor, agent, "Matcher", listing_checks.CHECK_BUDGET_MINOR)
    assert issues == [] and studio._validator_issues(ctx.bundle, list(unsaved.values()), check) == []
    assert all(owners.in_org(key, publisher.org_id) for _, key in unsaved)


def test_an_agent_bundle_records_the_schema_versions_the_check_run_pinned(publisher, starts, db, monkeypatch):  # noqa: F811
    org = publisher.org_id
    agent = clone_agent(db, "finance-agent", org, "matcher", title="Matcher")
    body = registry.latest(db, "agent", agent).body
    source = registry.latest(db, "schema", body["output_schema_ref"]).body
    schema = owners.org_key(org, "matcher-result")
    _own(db, org, "schema", schema, source)
    _own(
        db,
        org,
        "agent",
        agent,
        {**body, "output_schema_ref": schema},
        registry.latest(db, "agent", agent).files,
    )
    db.commit()
    real = listing_checks._sandbox_check

    def saved_meanwhile(*args):  # the schema is saved again as the check starts
        found = real(*args)
        again = Definition(
            kind="schema",
            key=schema,
            body={**source, "title": "Changed"},
            files={},
            path=path_for("schema", schema),
        )
        registry.publish(db, again, "test", "saved again", source=registry.BUILDER)
        db.commit()
        return found

    monkeypatch.setattr(listing_checks, "_sandbox_check", saved_meanwhile)
    res = _submit(publisher, "agent", agent, input={"note": "sample"})
    assert res.status_code == 201, res.text
    assert registry.latest(db, "schema", schema).version == 2
    held = {d["key"]: d["version"] for d in _bundle(db, res.json()["latest"]["id"])}
    assert held == {agent: 2, schema: 1}  # the agent was saved once to name the schema


def test_submission_runs_are_listing_checks_kept_in_spend(publisher, starts, db):  # noqa: F811
    key = clone_pack(db, PACK, publisher.org_id, "recon", title="Acme recon")
    agent = clone_agent(db, "finance-agent", publisher.org_id, "matcher", title="Matcher")
    db.commit()
    assert _submit(publisher, "pack", key, input=INPUT).status_code == 201
    assert _submit(publisher, "agent", agent, priceMinor=30, input={"note": "sample"}).status_code == 201
    started = {call[0] for call in starts.calls}
    assert len(started) == 2
    listed = {r["id"]: r for r in publisher.get("/v1/workflow-runs").json()}
    assert started <= set(listed)  # kept in the publisher's runs and spend, not hidden
    assert all(listed[r]["listingCheck"] is True and listed[r]["sandboxTest"] is True for r in started)
    for run_id in started:
        assert publisher.get(f"/v1/workflow-runs/{run_id}").json()["listingCheck"] is True
