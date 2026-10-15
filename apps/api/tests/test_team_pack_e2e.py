"""Sub-project C, part 9: a pack built in the Studio from the org's own agent runs end to end on PackRunner,
which is unchanged. The run pins its versions, runs the google_adk agent on the fake model, waits for a
person's review and an approval, saves Gmail drafts on sandbox data and seals its receipt. The same pack is
then driven on the snapshots the API makes for it: a Studio sandbox test, and an org-routed run of the pack
once added, whose grants are found by the pack's name (preflight #17)."""

import asyncio
from datetime import UTC, datetime

from app import live_catalog, live_connections, live_work, studio, temporal_client
from app.auth import Actor
from app.models.requests import InstallRequest, StartRunRequest
from app.models.runs import Run
from app.models.studio import SandboxRunRequest
from app.routers import tasks
from app.worker.workflow import PackRunner
from tests.live_seed import add_org
from tests.team_seed import TEAM_AGENT, invoice_nudges
from tests.test_workflow import (  # noqa: F401  (runtime_env is a fixture)
    _assert_sealed,
    _drive,
    _entries,
    _new_run,
    _run_row,
    _start,
    _tasks,
    _waiting,
    runtime_env,
)

ACTOR = Actor(user_id="uid_ana", org_id="org_demo", role="owner", email="ana@example.com", org_name="Demo Co")
INPUT = {"as_of": "2026-10-13"}
REFS = ["INV-0107", "INV-0098", "INV-0086"]  # the first three open invoices in the Stripe sandbox
PACK_NAME = "Invoice nudges"  # the name the org's connections know the pack's grants by


def _captured(monkeypatch) -> list[tuple[str, dict, dict]]:
    """What the API hands Temporal, `temporal_client.start_run(run_id, snapshot, input)`, captured so the
    test drives PackRunner with the very snapshot the API pinned."""
    calls: list[tuple[str, dict, dict]] = []
    monkeypatch.setattr(
        temporal_client, "start_run", lambda run_id, snap, inp: calls.append((run_id, snap, inp))
    )
    return calls


def _team_pack(conn) -> str:
    """The org (its row, for the spend check) and its pack built from its own agent; returns the pack key."""
    add_org(conn, ACTOR.org_id, ACTOR.org_name)
    conn.commit()
    agent = studio.create_agent(ACTOR, TEAM_AGENT)
    return studio.create_pack(ACTOR, invoice_nudges(agent.key)).key


async def _review_then_approve(env, run_id: str, snapshot: dict) -> str:
    handle = await _start(env.client, run_id, snapshot, INPUT)
    review = await _waiting(handle, "review")
    await handle.signal(PackRunner.human_result, args=[review["task_id"], "resolved", "Looks right.", []])
    approval = await _waiting(handle, "approve")
    await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "ana@example.com"])
    return await handle.result()


def _drafts(conn, run_id: str) -> list[dict]:
    calls = [e for e in _entries(conn, run_id) if e["type"] == "tool.call"]
    return [c["data"] for c in calls if c["data"]["tool_ref"] == "gmail.create_draft"]


def test_a_studio_pack_runs_through_review_and_approval_to_drafts(runtime_env):  # noqa: F811
    conn = runtime_env
    agent = studio.create_agent(ACTOR, TEAM_AGENT)
    pack = studio.create_pack(ACTOR, invoice_nudges(agent.key))
    run_id, snapshot = _new_run(conn, pack=pack.key, input=INPUT)
    pinned = {(v["kind"], v["key"]) for v in snapshot["versions"]}
    assert {
        ("pack", pack.key),
        ("workflow", pack.key),
        ("contract", pack.key),
        ("agent", agent.key),
        ("decision_rules", f"{pack.key}--check"),
        ("schema", "shared/agent-result"),
    } <= pinned
    assert snapshot["defs"]["agent"][agent.key]["body"]["runtime"]["adapter"] == "google_adk"

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot, INPUT)
        review = await _waiting(handle, "review")
        [task] = _tasks(conn, run_id)
        assert [i["ref"] for i in task["payload"]["show"]] == REFS
        row = {**task, "run_id": run_id, "run_title": pack.key, "created_at": datetime.now(UTC)}
        assert [r.id for r in tasks.real_task(row).records] == REFS
        await handle.signal(PackRunner.human_result, args=[review["task_id"], "resolved", "Looks right.", []])

        approval = await _waiting(handle, "approve")
        pending = next(t for t in _tasks(conn, run_id) if t["kind"] == "approval")
        assert pending["payload"]["summary"] == "Create 3 email drafts in Gmail"
        assert pending["payload"]["tool_ref"] == "gmail.create_draft" and pending["payload"]["mocked"] is True
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "ana@example.com"])
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"

    _assert_sealed(conn, run_id, snapshot, "COMPLETED")
    entries = _entries(conn, run_id)
    assert {e["node_id"] for e in entries if e["type"] == "model.usage"} == {"plan", "draft"}
    calls = [e for e in entries if e["type"] == "tool.call"]
    assert [c["data"]["tool_ref"] for c in calls if c["node_id"] == "invoices"] == ["stripe.list_invoices"]
    drafts = [c for c in calls if c["data"]["tool_ref"] == "gmail.create_draft"]
    assert len(drafts) == 3
    assert all(
        c["data"]["ok"] and c["data"]["policy"]["reason_codes"] == ["APPROVAL_GRANTED"] for c in drafts
    )
    finished = Run.model_validate(_run_row(conn, run_id)["projection"])
    assert finished.status == "COMPLETED" and finished.stages.verified == "done"
    result = finished.deliverable
    assert result.kind == "Result" and len(result.items) == 3
    assert result.summary == "3 drafts were prepared on sandbox data. Nothing was sent."


def test_a_sandbox_test_runs_on_sandbox_data_whatever_the_workers_mode(runtime_env, monkeypatch):  # noqa: F811
    """ "Test in sandbox": the pack is not added and no app is connected; the snapshot the API pins carries no
    routing and the sandbox connector mode, so a worker in live mode still answers every call from sandbox
    data and labels the approval as simulated."""
    conn = runtime_env
    starts = _captured(monkeypatch)
    key = _team_pack(conn)
    run = studio.sandbox_run(ACTOR, key, SandboxRunRequest(input=INPUT))
    [(run_id, snapshot, inp)] = starts
    assert run_id == run.id and inp == INPUT and run.sandbox_test is True
    assert snapshot["connector_mode"] == "sandbox" and "routing" not in snapshot
    monkeypatch.setenv("NM_CONNECTOR_MODE", "live")

    async def scenario(env):
        return await _review_then_approve(env, run_id, snapshot)

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"

    _assert_sealed(conn, run_id, snapshot, "COMPLETED")
    approval = next(t for t in _tasks(conn, run_id) if t["kind"] == "approval")
    assert approval["payload"]["mocked"] is True
    calls = [e["data"] for e in _entries(conn, run_id) if e["type"] == "tool.call"]
    assert calls and all(c["mocked"] is True and c["ok"] for c in calls)
    drafts = _drafts(conn, run_id)
    assert len(drafts) == 3 and all(d["policy"]["reason_codes"] == ["APPROVAL_GRANTED"] for d in drafts)
    finished = Run.model_validate(_run_row(conn, run_id)["projection"])
    assert finished.status == "COMPLETED" and finished.sandbox_test is True


def test_an_added_team_pack_runs_through_the_orgs_connections_and_their_grants(runtime_env, monkeypatch):  # noqa: F811
    """The production path of an added team pack: the run is routed through the org's connections, which
    grant the pack by its name; the Gmail writes run once approved, and once that grant is revoked the next
    run's approval is refused before anyone is asked (GRANT_REVOKED) and no draft is written."""
    conn = runtime_env
    starts = _captured(monkeypatch)
    key = _team_pack(conn)
    live_catalog.install(ACTOR, InstallRequest(pack_slug=key, cap_minor=2000))
    for app in ("stripe", "gmail"):
        live_connections.connect_sandbox(ACTOR.org_id, ACTOR.user_id, app, ACTOR.role)
    request = StartRunRequest(pack_slug=key, input=INPUT, budget_minor=1000)
    run = live_work.start_run(request, ACTOR)
    [(run_id, snapshot, _)] = starts
    assert run_id == run.id and snapshot["routing"] == "org" and "connector_mode" not in snapshot
    assert run.sandbox_test is None
    monkeypatch.setenv("NM_CONNECTOR_MODE", "live")  # the connections, not the worker's mode, decide

    async def scenario(env):
        return await _review_then_approve(env, run_id, snapshot)

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"

    _assert_sealed(conn, run_id, snapshot, "COMPLETED")
    drafts = _drafts(conn, run_id)
    assert len(drafts) == 3
    assert all(
        d["ok"] and d["mocked"] and d["policy"]["reason_codes"] == ["APPROVAL_GRANTED"] for d in drafts
    )

    live_connections.revoke_grant(ACTOR.org_id, "gmail", PACK_NAME, "mail.write")
    again = live_work.start_run(request, ACTOR)
    run_id2, snapshot2, _ = starts[-1]
    assert run_id2 == again.id

    async def refused(env):
        handle = await _start(env.client, run_id2, snapshot2, INPUT)
        review = await _waiting(handle, "review")
        await handle.signal(PackRunner.human_result, args=[review["task_id"], "resolved", "Looks right.", []])
        return await handle.result()

    assert asyncio.run(_drive(None, refused)) == "FAILED"

    _assert_sealed(conn, run_id2, snapshot2, "FAILED")
    entries = _entries(conn, run_id2)
    [refusal] = [e for e in entries if e["type"] == "node.failed" and e["node_id"] == "approve"]
    assert refusal["data"]["reason_codes"] == ["GRANT_REVOKED"]
    assert _drafts(conn, run_id2) == []
    assert not [t for t in _tasks(conn, run_id2) if t["kind"] == "approval"]
