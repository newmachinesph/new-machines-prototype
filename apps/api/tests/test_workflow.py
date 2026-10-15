"""PackRunner end to end on the Temporal time-skipping test server, Postgres and the real definitions.

Every test needs the local Postgres (`db` fixture) and downloads the Temporal test server on first run.
"""

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg.types.json import Jsonb
from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.contrib.google_adk_agents import GoogleAdkPlugin
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from app import settings
from app.defs import registry
from app.defs.loader import load_bundle
from app.defs.snapshot import build_snapshot
from app.models.runs import Run
from app.runtime import adk_agent, projection, providers, receipt
from app.runtime.providers import SUBMIT_TOOL, FakeProvider, ModelTurn
from app.worker import activities
from app.worker.activities import PackActivities
from app.worker.workflow import PackRunner, RunInput

PACK = "order-payment-reconciliation"
INPUT = {
    "since": "2026-10-06",
    "until": "2026-10-12",
    "spreadsheet_id": "sandbox-reconciliation-sheet-00000001",
}
QUEUE = "test-packs"
WAIT_S = 30.0


@pytest.fixture
def runtime_env(db, monkeypatch):
    monkeypatch.setenv("NM_MODEL_ENV", "test")
    monkeypatch.setenv("NM_CONNECTOR_MODE", "sandbox")
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    return db


def _new_run(conn, edit=None, pack: str = PACK, input: dict = INPUT) -> tuple[str, dict]:
    """What the API does before starting the workflow (Task 6): pin a snapshot and insert the runs row.
    `edit(snapshot) -> snapshot` changes the pinned snapshot before the insert."""
    snapshot = build_snapshot(conn, pack, "org_demo", {}, set())
    if edit is not None:
        snapshot = edit(snapshot)
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    initial = projection.initial_projection(run_id, snapshot, input, "Demo buyer", 2500)
    conn.execute(
        "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input) "
        "VALUES (%s, 'org_demo', %s, 'RUNNING', %s, %s, %s)",
        (run_id, pack, Jsonb(snapshot), Jsonb(initial), Jsonb(input)),
    )
    conn.commit()
    return run_id, snapshot


async def _waiting(handle: WorkflowHandle, node_id: str) -> dict:
    """Poll the workflow query until it waits on a task at `node_id`."""
    for _ in range(int(WAIT_S / 0.1)):
        q = await handle.query(PackRunner.state)
        if q["waiting"] and q["waiting"]["node_id"] == node_id:
            return q["waiting"]
        if q["status"] in ("COMPLETED", "FAILED"):
            raise AssertionError(f"run ended with {q['status']} before waiting at {node_id}")
        await asyncio.sleep(0.1)
    raise AssertionError(f"run never waited at {node_id}")


def adk_plugins() -> list:
    """What `temporal_client.connect` gives production clients; a Worker built from the client inherits it."""
    return [GoogleAdkPlugin()]


async def _drive(provider, scenario, acts: PackActivities | None = None) -> str:
    """Run one PackRunner execution on a fresh time-skipping server; `scenario(env)` drives the signals."""
    adk_agent.warm_up()  # as build_worker does: keeps ADK's first-turn imports out of the workflow
    async with await WorkflowEnvironment.start_time_skipping(plugins=adk_plugins()) as env:
        with ThreadPoolExecutor(max_workers=8) as pool:
            acts = acts or PackActivities(provider=provider)
            async with Worker(
                env.client,
                task_queue=QUEUE,
                workflows=[PackRunner],
                activities=acts.all(),
                activity_executor=pool,
            ):
                return await scenario(env)


def _start(client, run_id: str, snapshot: dict, input: dict = INPUT):
    return client.start_workflow(
        PackRunner.run,
        RunInput(run_id=run_id, snapshot=snapshot, input=input),
        id=run_id,
        task_queue=QUEUE,
    )


def _assert_sealed(conn, run_id: str, snapshot: dict, status: str) -> None:
    """The receipt ends with its seal, and the chain (seal included) still verifies."""
    entries = _entries(conn, run_id)
    seal = entries[-1]
    assert seal["type"] == "receipt.sealed" and [e["type"] for e in entries].count("receipt.sealed") == 1
    assert seal["data"] == {
        "entry_count": len(entries) - 1,
        "versions": snapshot["versions"],
        "status": status,
    }
    ok, count, _ = receipt.verify(conn, run_id)
    assert ok is True and count == len(entries)


def _entries(conn, run_id: str) -> list[dict]:
    conn.commit()  # end any snapshot of an earlier transaction
    return conn.execute(
        "SELECT seq, type, node_id, data FROM receipt_entries WHERE run_id = %s ORDER BY seq", (run_id,)
    ).fetchall()


def _run_row(conn, run_id: str) -> dict:
    conn.commit()
    return conn.execute("SELECT status, projection FROM runs WHERE id = %s", (run_id,)).fetchone()


def _tasks(conn, run_id: str) -> list[dict]:
    conn.commit()
    return conn.execute(
        "SELECT id, node_id, kind, status, payload, result, decided_by FROM run_tasks WHERE run_id = %s "
        "ORDER BY created_at",
        (run_id,),
    ).fetchall()


def _nodes(p: dict) -> dict:
    return {n["id"]: n for n in p["nodes"]}


def _sandbox(connector: str, tool: str) -> dict:
    path = settings.defs_dir() / "connectors" / "sandbox" / connector / f"{tool}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _turn(content: list[dict], input_tokens: int = 1200) -> ModelTurn:
    return ModelTurn(
        content=content, stop_reason="tool_use", input_tokens=input_tokens, output_tokens=300, model="fake"
    )


# --- snapshot ---------------------------------------------------------------------------------------


def test_build_snapshot_pins_the_pack_and_what_it_references(runtime_env):
    snap = build_snapshot(runtime_env, PACK, "org_acme", {"stripe": {"read": "deny"}}, {"shopify"})
    defs = snap["defs"]
    assert list(defs["pack"]) == [PACK] and list(defs["workflow"]) == [PACK]
    assert list(defs["contract"]) == [PACK]
    assert defs["contract"][PACK]["body"]["org_id"] == "org_acme"
    assert set(defs["agent"]) == {"finance-agent", "ops-agent"}
    assert set(defs["connector"]) == {"shopify", "stripe", "googlesheets"}
    assert set(defs["decision_rules"]) == {"recon-exceptions"}
    assert set(defs["memory_space"]) == {"retail-commerce"}
    assert set(defs["models"]) == {"default"}
    assert {f"{PACK}/{n}" for n in ("input", "match", "report", "output")} <= set(defs["schema"])
    assert defs["agent"]["finance-agent"]["files"]["instructions.md"]
    pinned = {(v["kind"], v["key"]): v for v in snap["versions"]}
    assert pinned[("workflow", PACK)]["version"] == 1 and pinned[("workflow", PACK)]["digest"]
    assert set(pinned) == {(k, key) for k, items in defs.items() for key in items}
    assert snap["org_id"] == "org_acme" and snap["overrides"] == {"stripe": {"read": "deny"}}
    assert snap["disabled"] == ["shopify"]
    json.dumps(snap)


def test_build_snapshot_unknown_pack_raises(runtime_env):
    with pytest.raises(LookupError):
        build_snapshot(runtime_env, "no-such-pack", "org_demo", {}, set())


# --- the workflow -----------------------------------------------------------------------------------


def test_happy_path_waits_for_review_and_approval_then_completes(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    resolutions = [{"order_id": "#1004", "resolution": "explained", "note": "Partial refund agreed."}]

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        review = await _waiting(handle, "review")
        row = _run_row(conn, run_id)
        assert _nodes(row["projection"])["review"]["status"] == "WAITING"
        assert row["status"] == "WAITING_FOR_HUMAN"
        [task] = _tasks(conn, run_id)
        assert task["id"] == review["task_id"] and task["kind"] == "human" and task["status"] == "open"
        assert task["payload"]["title"] == "Resolve order and payment mismatches"
        assert [m["order_id"] for m in task["payload"]["show"]] == ["#1004", "#1007"]
        await handle.signal(
            PackRunner.human_result, args=[review["task_id"], "resolved", "Checked both.", resolutions]
        )

        approval = await _waiting(handle, "approve_write")
        assert _run_row(conn, run_id)["status"] == "WAITING_FOR_EVENT"
        pending = next(t for t in _tasks(conn, run_id) if t["kind"] == "approval")
        # Sandbox mode: the approved Sheets write will use sandbox data, so the inbox labels it simulated.
        assert pending["payload"]["tool_ref"] == "googlesheets.append_rows"
        assert pending["payload"]["mocked"] is True
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"

    _assert_sealed(conn, run_id, snapshot, "COMPLETED")
    entries = _entries(conn, run_id)
    [decided] = [e for e in entries if e["type"] == "decision"]
    assert decided["data"]["policy"]["verdict"] == "REQUIRE_APPROVAL"
    assert decided["data"]["policy"]["reason_codes"] == ["MISMATCHES_FOUND"]
    sheets = [
        e for e in entries if e["type"] == "tool.call" and e["data"]["tool_ref"].startswith("googlesheets")
    ]
    assert len(sheets) == 1 and sheets[0]["data"]["policy"]["verdict"] == "PERMIT"
    assert sheets[0]["data"]["policy"]["reason_codes"] == ["APPROVAL_GRANTED"]
    [completed] = [e for e in entries if e["type"] == "run.completed"]
    assert len(completed["data"]["deliverable"]["rows"]) == 12 and completed["data"]["mocked"] is True
    usage = [e for e in entries if e["type"] == "model.usage"]
    assert {e["node_id"] for e in usage} == {"match", "report"}

    row = _run_row(conn, run_id)
    assert row["status"] == "COMPLETED"
    run = Run.model_validate(row["projection"])
    assert run.status == "COMPLETED"
    nodes = {n.id: n for n in run.nodes}
    calls = [c for n in run.nodes for c in (n.tool_calls or [])]
    assert len(calls) == 3 and all(c.mocked is True for c in calls)
    decision = nodes["check"].decision
    assert decision.verdict == "HUMAN_REVIEW" and decision.route == "human_review"
    assert decision.policy.ref == "recon-exceptions@v1" and decision.policy.actor == "rules"
    assert decision.policy.reason_codes == ["MISMATCHES_FOUND"]
    assert decision.policy.verdict == "REQUIRE_APPROVAL"
    assert run.spent.ai.amount_minor > 0
    assert {r.label: r.value for r in run.deliverable.rows}["Rows in the report"] == "12"
    assert run.stages.verified == "done"
    assert all(
        nodes[i].status == "COMPLETED" for i in ("start", "match", "review", "write", "verify", "done")
    )

    tasks = {t["kind"]: t for t in _tasks(conn, run_id)}
    assert tasks["human"]["status"] == "resolved" and tasks["human"]["result"]["resolutions"] == resolutions
    assert tasks["approval"]["status"] == "granted" and tasks["approval"]["decided_by"] == "buyer@demo"


def test_approval_denied_fails_without_writing(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        review = await _waiting(handle, "review")
        await handle.signal(PackRunner.human_result, args=[review["task_id"], "resolved", "Fine."])
        approval = await _waiting(handle, "approve_write")
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "denied", "buyer@demo"])
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "FAILED"
    entries = _entries(conn, run_id)
    assert not [e for e in entries if e["type"] == "tool.call" and "googlesheets" in e["data"]["tool_ref"]]
    assert [e["data"]["reason"] for e in entries if e["type"] == "run.failed"]
    row = _run_row(conn, run_id)
    assert row["status"] == "FAILED"
    nodes = _nodes(row["projection"])
    assert nodes["approve_write"]["status"] == "REJECTED" and nodes["write"]["status"] == "CREATED"
    _assert_sealed(conn, run_id, snapshot, "FAILED")


def test_human_timeout_fails_the_run(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        await _waiting(handle, "review")
        return await handle.result()  # the time-skipping server jumps past the 24 h task timeout

    assert asyncio.run(_drive(None, scenario)) == "FAILED"
    [task] = _tasks(conn, run_id)
    assert task["status"] == "timeout" and task["decided_by"] is None
    _assert_sealed(conn, run_id, snapshot, "FAILED")
    row = _run_row(conn, run_id)
    assert row["status"] == "FAILED"
    assert _nodes(row["projection"])["review"]["status"] == "TIMED_OUT"
    assert not [e for e in _entries(conn, run_id) if e["node_id"] == "report"]


def _all_matched_script() -> dict:
    """finance-agent first calls a tool it was not offered, then submits a match with no mismatches."""
    inputs = {"orders": _sandbox("shopify", "list_orders"), "charges": _sandbox("stripe", "list_charges")}
    match = providers.fake_match(inputs)
    match["mismatches"] = []
    match["totals"]["mismatch_count"] = 0
    probe = {"type": "tool_use", "id": "toolu_1", "name": "shopify__list_orders", "input": {"limit": 5}}
    submit = {"type": "tool_use", "id": "toolu_2", "name": SUBMIT_TOOL, "input": match}
    return {"finance-agent": [_turn([probe]), _turn([submit])]}


def test_no_mismatches_skips_review_and_goes_to_approval(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        approval = await _waiting(handle, "approve_write")
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        return await handle.result()

    provider = FakeProvider(script=_all_matched_script())
    assert asyncio.run(_drive(provider, scenario)) == "COMPLETED"
    assert [t["kind"] for t in _tasks(conn, run_id)] == ["approval"]
    nodes = _nodes(_run_row(conn, run_id)["projection"])
    assert nodes["check"]["decision"]["verdict"] == "APPROVED"
    assert nodes["check"]["decision"]["policy"]["verdict"] == "PERMIT"
    assert nodes["check"]["decision"]["policy"]["reasonCodes"] == ["ALL_MATCHED"]
    assert nodes["review"]["status"] == "CREATED"
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")
    probes = [e for e in _entries(conn, run_id) if e["type"] == "tool.call" and e["node_id"] == "match"]
    assert len(probes) == 1 and probes[0]["data"]["policy"]["verdict"] == "DENY"
    assert probes[0]["data"]["policy"]["reason_codes"] == ["TOOL_NOT_OFFERED"]
    assert (
        len([e for e in _entries(conn, run_id) if e["type"] == "model.usage" and e["node_id"] == "match"])
        == 2
    )


def test_ai_spend_over_the_contract_budget_fails_the_run(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    match = _all_matched_script()["finance-agent"][1]
    # 10M input tokens at 400 minor units per million = 4000 > the 2500 budget.
    script = {"finance-agent": [_turn(match.content, input_tokens=10_000_000)]}

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        return await handle.result()

    assert asyncio.run(_drive(FakeProvider(script=script), scenario)) == "FAILED"
    [failed] = [e for e in _entries(conn, run_id) if e["type"] == "run.failed"]
    assert failed["data"]["reason"].startswith("BUDGET_EXCEEDED")
    assert _run_row(conn, run_id)["status"] == "FAILED"
    _assert_sealed(conn, run_id, snapshot, "FAILED")


def test_a_workflow_for_a_run_already_sealed_ends_without_recording_anything(runtime_env):
    """The API gave up starting this run and sealed it FAILED; a workflow that starts anyway must not run."""
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    failed = ("run:0:run.failed:0", "run.failed", None, {"reason": "The API gave up starting this run."})
    activities.record_events(conn, run_id, [failed])
    conn.commit()
    before = _entries(conn, run_id)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        with pytest.raises(WorkflowFailureError) as err:
            await handle.result()
        return err.value.cause

    cause = asyncio.run(_drive(providers.FakeProvider(), scenario))
    assert isinstance(cause, ApplicationError) and cause.type == activities.RUN_SEALED
    assert _entries(conn, run_id) == before
    assert _run_row(conn, run_id)["status"] == "FAILED"


def test_the_run_budget_caps_ai_spend_below_the_contract_maximum(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    snapshot = {**snapshot, "budget_minor": 1000}
    match = _all_matched_script()["finance-agent"][1]
    # 5M input tokens at 400 minor units per million = 2000: under the contract's 2500, over the run's 1000.
    script = {"finance-agent": [_turn(match.content, input_tokens=5_000_000)]}

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        return await handle.result()

    assert asyncio.run(_drive(FakeProvider(script=script), scenario)) == "FAILED"
    [failed] = [e for e in _entries(conn, run_id) if e["type"] == "run.failed"]
    assert failed["data"]["reason"].startswith("BUDGET_EXCEEDED")
    assert "budget of 1000 minor units" in failed["data"]["reason"]


def test_invalid_agent_output_fails_the_run_without_retrying(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    bad = {"type": "tool_use", "id": "toolu_1", "name": SUBMIT_TOOL, "input": {"matched": "nope"}}

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        return await handle.result()

    provider = FakeProvider(script={"finance-agent": [_turn([bad])]})
    assert asyncio.run(_drive(provider, scenario)) == "FAILED"
    entries = _entries(conn, run_id)
    [failed] = [e for e in entries if e["type"] == "node.failed"]
    assert failed["node_id"] == "match" and failed["data"]["error"].startswith("OutputInvalid")
    assert _nodes(_run_row(conn, run_id)["projection"])["match"]["status"] == "FAILED"
    assert [e["data"]["reason"] for e in entries if e["type"] == "run.failed"]


def test_a_signal_of_the_wrong_kind_never_blocks_the_right_one(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        review = await _waiting(handle, "review")
        # An approval aimed at the human task id first: ignored, and it must not swallow the real result.
        await handle.signal(PackRunner.approval, args=[review["task_id"], "denied", "someone"])
        await handle.signal(PackRunner.human_result, args=[review["task_id"], "resolved", "ok"])
        approval = await _waiting(handle, "approve_write")
        await handle.signal(PackRunner.human_result, args=[approval["task_id"], "rejected", "wrong kind"])
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"
    tasks = {t["kind"]: t for t in _tasks(conn, run_id)}
    assert tasks["human"]["status"] == "resolved" and tasks["approval"]["status"] == "granted"


def test_a_decision_the_api_recorded_wins_over_the_timer(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    stored = {"outcome": "resolved", "note": "Recorded by the API.", "resolutions": []}

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        review = await _waiting(handle, "review")
        # The API stored the decision but its signal never arrived; then the 24 h timer fires.
        conn.execute(
            "UPDATE run_tasks SET status = 'resolved', result = %s, decided_by = 'reviewer@demo', "
            "decided_at = now() WHERE id = %s",
            (Jsonb(stored), review["task_id"]),
        )
        conn.commit()
        await env.sleep(86400 + 60)
        approval = await _waiting(handle, "approve_write")
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"
    human = next(t for t in _tasks(conn, run_id) if t["kind"] == "human")
    assert human["status"] == "resolved" and human["decided_by"] == "reviewer@demo"
    assert human["result"] == stored
    closed = [
        e for e in _entries(conn, run_id) if e["type"] == "human.task" and e["data"]["status"] != "open"
    ]
    assert [(e["data"]["status"], e["data"]["decided_by"]) for e in closed] == [("resolved", "reviewer@demo")]
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")


def _network_review(conn, decided: bool) -> tuple[str, dict]:
    """Run the pack to its review and claim it through the network. Then either record a REVISION_REQUIRED
    review as the API does and signal it, or let the 24 h timer fire. Returns the run id and the human task's
    closing event."""
    run_id, snapshot = _new_run(conn)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        review = await _waiting(handle, "review")
        marks = {"claimed_by": "uid_stranger", "claimed_via": "network", "pay": 300}
        task = review["task_id"]
        conn.execute("UPDATE run_tasks SET payload = payload || %s WHERE id = %s", (Jsonb(marks), task))
        conn.commit()
        if not decided:
            return await handle.result()  # the time-skipping server jumps past the task timeout
        result = {
            "outcome": "resolved",
            "note": "Fix #1004.",
            "resolutions": [],
            "verdict": "REVISION_REQUIRED",
        }
        conn.execute(
            "UPDATE run_tasks SET status = 'resolved', result = %s, decided_by = 'uid_stranger', "
            "decided_at = now() WHERE id = %s",
            (Jsonb(result), task),
        )
        conn.commit()
        await handle.signal(PackRunner.human_result, args=[task, "resolved", "Fix #1004."])
        approval = await _waiting(handle, "approve_write")
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        return await handle.result()

    asyncio.run(_drive(None, scenario))
    entries = _entries(conn, run_id)
    [closed] = [e for e in entries if e["type"] == "human.task" and e["data"]["status"] != "open"]
    return run_id, closed


def test_a_network_review_reaches_the_buyer_s_timeline_anonymous_with_its_verdict_and_pay(runtime_env):
    conn = runtime_env
    run_id, closed = _network_review(conn, decided=True)
    assert "uid_stranger" not in json.dumps(closed["data"])
    assert closed["data"]["decided_by"] == "Network reviewer" and closed["data"]["cost_minor"] == 300
    p = _run_row(conn, run_id)["projection"]
    assert "uid_stranger" not in json.dumps(p["timeline"])
    resolved = [
        t for t in p["timeline"] if t.get("ref") == closed["data"]["task_id"] and t["actor"] == "human"
    ]
    assert [(t["who"], t["title"]) for t in resolved] == [("Network reviewer", "Sent back with corrections")]
    # The reviewer's note is on that line only, not repeated as the review step finishing.
    assert [t for t in p["timeline"] if "Fix #1004." in json.dumps(t)] == [resolved[0]]
    assert _nodes(p)["review"]["output"] == "Fix #1004."  # the step still carries it
    assert p["spent"]["human"]["amountMinor"] == 300  # the run's reviewer pay, counted once
    assert _nodes(p)["review"]["cost"]["amountMinor"] == 300


def test_a_network_claim_that_times_out_costs_the_buyer_nothing(runtime_env):
    conn = runtime_env
    run_id, closed = _network_review(conn, decided=False)
    assert closed["data"]["status"] == "timeout" and "cost_minor" not in closed["data"]
    assert "decided_by" not in closed["data"]
    assert _run_row(conn, run_id)["projection"]["spent"]["human"]["amountMinor"] == 0


def test_config_errors_reach_the_receipt_sanitized():
    with pytest.raises(ApplicationError) as caught, activities._config_errors():
        raise ValueError("bad value from https://backend.example.com/v3/x?api_key=secret " + "a" * 600)
    error = caught.value
    assert error.non_retryable is True and error.type == "ConfigError"
    assert "http" not in error.message and "secret" not in error.message
    assert len(error.message) <= activities.MAX_ERROR_CHARS


def test_decision_policy_verdict_follows_the_outcome():
    expected = {
        "APPROVED": "PERMIT",
        "HUMAN_REVIEW": "REQUIRE_APPROVAL",
        "ESCALATED": "REQUIRE_APPROVAL",
        "BLOCKED": "DENY",
        "REJECTED": "DENY",
    }
    assert {v: activities.policy_verdict(v) for v in expected} == expected


# --- worker entrypoint -------------------------------------------------------------------------------


def test_worker_connect_uses_api_key_and_tls_only_for_temporal_cloud(monkeypatch):
    from app.worker import __main__ as worker_main

    calls = []

    async def fake_connect(target, *, plugins, **kwargs):
        assert [type(p) for p in plugins] == [GoogleAdkPlugin]  # every client carries the ADK plugin
        calls.append((target, kwargs))
        return "client"

    monkeypatch.setattr(worker_main.Client, "connect", fake_connect)
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    monkeypatch.setenv("TEMPORAL_TARGET", "127.0.0.1:7243")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "default")
    assert asyncio.run(worker_main.connect()) == "client"
    assert calls[-1] == ("127.0.0.1:7243", {"namespace": "default"})

    monkeypatch.setenv("TEMPORAL_TARGET", "nm.abc12.tmprl.cloud:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "nm.abc12")
    with pytest.raises(RuntimeError):
        asyncio.run(worker_main.connect())
    monkeypatch.setenv("TEMPORAL_API_KEY", "test-key")
    asyncio.run(worker_main.connect())
    assert calls[-1] == (
        "nm.abc12.tmprl.cloud:7233",
        {"namespace": "nm.abc12", "api_key": "test-key", "tls": True},
    )


def test_worker_activity_concurrency_matches_threads_and_db_pool(monkeypatch):
    from app.worker import runtime as worker_main

    monkeypatch.delenv("NM_WORKER_CONCURRENCY", raising=False)
    monkeypatch.delenv("NM_DB_POOL_MAX", raising=False)
    captured = {}

    def fake_worker(client, **kwargs):
        captured.update(kwargs)
        return "worker"

    monkeypatch.setattr(worker_main, "Worker", fake_worker)
    with ThreadPoolExecutor(max_workers=worker_main.activity_threads()) as pool:
        assert worker_main.build_worker("client", pool) == "worker"
    assert captured["max_concurrent_activities"] == worker_main.activity_threads() == 8
    assert captured["activity_executor"]._max_workers == 8


# --- failures end the run cleanly ---------------------------------------------------------------------


async def _run_to_end(env, run_id: str, snapshot: dict) -> str:
    """Start the run and answer the review and the approval whenever it waits for them."""
    handle = await _start(env.client, run_id, snapshot)
    review = await _waiting(handle, "review")
    await handle.signal(PackRunner.human_result, args=[review["task_id"], "resolved", "Fine."])
    approval = await _waiting(handle, "approve_write")
    await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
    return await handle.result()


class _FlakyEnd(PackActivities):
    """run_node fails on the end node `failures` times (a database outage), then behaves."""

    def __init__(self, failures: int) -> None:
        super().__init__(provider=None)
        self.failures = failures
        self.calls = 0

    @activity.defn(name="run_node")
    def run_node(self, call: activities.NodeCall) -> dict:
        if call.node_id == "done":
            self.calls += 1
            if self.calls <= self.failures:
                raise RuntimeError("connection to the database was lost")
        return super().run_node(call)


class _FlakyProvider(FakeProvider):
    """The model provider is rate limited for the first `failures` calls."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.calls = 0

    def call(self, **kwargs) -> ModelTurn:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("429 rate limited")
        return super().call(**kwargs)


def test_a_missing_entry_node_fails_the_run_instead_of_looping(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    workflow = snapshot["defs"]["workflow"][PACK]
    snapshot = {
        **snapshot,
        "defs": {
            **snapshot["defs"],
            "workflow": {PACK: {**workflow, "body": {**workflow["body"], "entry_node_id": "nowhere"}}},
        },
    }

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "FAILED"
    [failed] = [e for e in _entries(conn, run_id) if e["type"] == "run.failed"]
    assert failed["data"]["reason"] == "NO_NODE: entry node 'nowhere' does not exist"
    assert _run_row(conn, run_id)["status"] == "FAILED"
    _assert_sealed(conn, run_id, snapshot, "FAILED")


def test_bookkeeping_steps_outlast_a_database_blip(runtime_env):
    """More failures than the side-effect policy's three attempts: the end step still completes the run."""
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    acts = _FlakyEnd(failures=4)

    async def scenario(env):
        return await _run_to_end(env, run_id, snapshot)

    assert asyncio.run(_drive(None, scenario, acts)) == "COMPLETED"
    assert acts.calls == 5
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")


def test_an_end_step_that_never_succeeds_still_fails_and_seals_the_run(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    acts = _FlakyEnd(failures=10**6)

    async def scenario(env):
        return await _run_to_end(env, run_id, snapshot)

    assert asyncio.run(_drive(None, scenario, acts)) == "FAILED"
    [failed] = [e for e in _entries(conn, run_id) if e["type"] == "run.failed"]
    assert failed["node_id"] == "done" and "the done step" in failed["data"]["reason"]
    assert _run_row(conn, run_id)["status"] == "FAILED"
    _assert_sealed(conn, run_id, snapshot, "FAILED")


def test_model_calls_ride_out_a_burst_of_rate_limits(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    provider = _FlakyProvider(failures=4)  # more than the old three attempts, fewer than six

    async def scenario(env):
        return await _run_to_end(env, run_id, snapshot)

    assert asyncio.run(_drive(provider, scenario)) == "COMPLETED"
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")


# --- agent adapters ------------------------------------------------------------------------------------

ADK_IDENTITY = "Your internal name is"  # ADK appends this to the instruction it sends the model


class _RecordingProvider(FakeProvider):
    """The fake provider, keeping each system prompt and conversation the model received."""

    def __init__(self, script: dict | None = None) -> None:
        super().__init__(script=script)
        self.systems: list[str] = []
        self.conversations: list[list[dict]] = []

    def call(self, **kwargs) -> ModelTurn:
        self.systems.append(kwargs["system"])
        self.conversations.append(kwargs["messages"])
        return super().call(**kwargs)


def _hosted(snapshot: dict) -> dict:
    """A snapshot pinned before google_adk existed: every agent body says adapter: hosted."""
    agents = {
        key: {**d, "body": {**d["body"], "runtime": {**d["body"]["runtime"], "adapter": "hosted"}}}
        for key, d in snapshot["defs"]["agent"].items()
    }
    return {**snapshot, "defs": {**snapshot["defs"], "agent": agents}}


def test_agents_run_through_google_adk(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    assert {d["body"]["runtime"]["adapter"] for d in snapshot["defs"]["agent"].values()} == {"google_adk"}
    provider = _RecordingProvider()

    async def scenario(env):
        status = await _run_to_end(env, run_id, snapshot)
        # ADK's ids and clocks come from the workflow (GoogleAdkPlugin), so the run replays deterministically.
        history = await env.client.get_workflow_handle(run_id).fetch_history()
        await Replayer(workflows=[PackRunner], plugins=adk_plugins()).replay_workflow(history)
        return status

    assert asyncio.run(_drive(provider, scenario)) == "COMPLETED"
    assert provider.systems and all(ADK_IDENTITY in s for s in provider.systems)
    assert {s.splitlines()[0] for s in provider.systems} == {"agent:finance-agent", "agent:ops-agent"}
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")


def test_a_run_pinned_to_the_hosted_adapter_still_completes(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn, edit=_hosted)
    assert snapshot["defs"]["agent"]["finance-agent"]["body"]["runtime"]["adapter"] == "hosted"
    provider = _RecordingProvider()

    async def scenario(env):
        return await _run_to_end(env, run_id, snapshot)

    assert asyncio.run(_drive(provider, scenario)) == "COMPLETED"
    assert provider.systems and not any(ADK_IDENTITY in s for s in provider.systems)
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")


def test_an_agent_that_never_submits_fails_with_turns_exhausted(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn)
    chatter = _turn([{"type": "text", "text": "Still looking at the orders."}])

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        return await handle.result()

    assert asyncio.run(_drive(FakeProvider(script={"finance-agent": [chatter]}), scenario)) == "FAILED"
    entries = _entries(conn, run_id)
    [failed] = [e for e in entries if e["type"] == "run.failed"]
    assert failed["data"]["reason"].startswith("TURNS_EXHAUSTED")
    usage = [e for e in entries if e["type"] == "model.usage" and e["node_id"] == "match"]
    assert len(usage) == snapshot["defs"]["agent"]["finance-agent"]["body"]["runtime"]["max_turns"]
    assert _nodes(_run_row(conn, run_id)["projection"])["match"]["status"] == "FAILED"
    _assert_sealed(conn, run_id, snapshot, "FAILED")


def _finance_with_tools(snapshot: dict) -> dict:
    """finance-agent is offered shopify.list_orders and stripe.list_charges (the contract grants orders.read
    and payments.read)."""
    finance = snapshot["defs"]["agent"]["finance-agent"]
    runtime = {**finance["body"]["runtime"], "tools": ["shopify.list_orders", "stripe.list_charges"]}
    agents = {
        **snapshot["defs"]["agent"],
        "finance-agent": {**finance, "body": {**finance["body"], "runtime": runtime}},
    }
    return {**snapshot, "defs": {**snapshot["defs"], "agent": agents}}


def test_an_adk_agent_calls_offered_tools_through_the_gateway(runtime_env):
    conn = runtime_env
    run_id, snapshot = _new_run(conn, edit=_finance_with_tools)
    granted = snapshot["defs"]["contract"][PACK]["body"]["authorization"]["tool_capabilities"]
    assert {"orders.read", "payments.read"} <= set(granted)
    orders = {"type": "tool_use", "id": "toolu_orders", "name": "shopify__list_orders", "input": {"limit": 5}}
    charges = {"type": "tool_use", "id": "toolu_charges", "name": "stripe__list_charges", "input": {}}
    submit = _all_matched_script()["finance-agent"][1]
    provider = _RecordingProvider(script={"finance-agent": [_turn([orders, charges]), submit]})

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        approval = await _waiting(handle, "approve_write")
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        return await handle.result()

    assert asyncio.run(_drive(provider, scenario)) == "COMPLETED"
    calls = [e for e in _entries(conn, run_id) if e["type"] == "tool.call" and e["node_id"] == "match"]
    # ADK runs a turn's tool calls concurrently, so the receipt holds them in completion order.
    assert sorted((e["data"]["id"], e["data"]["tool_ref"]) for e in calls) == [
        ("toolu_charges", "stripe.list_charges"),
        ("toolu_orders", "shopify.list_orders"),
    ]
    assert all(e["data"]["policy"]["verdict"] == "PERMIT" and e["data"]["ok"] for e in calls)
    finance = [
        c for s, c in zip(provider.systems, provider.conversations, strict=True) if "finance-agent" in s
    ]
    assert len(finance) == 2
    assert finance[1][-2] == {"role": "assistant", "content": [orders, charges]}
    assert finance[1][-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_orders",
                "content": json.dumps(_sandbox("shopify", "list_orders"), ensure_ascii=False),
                "is_error": False,
            },
            {
                "type": "tool_result",
                "tool_use_id": "toolu_charges",
                "content": json.dumps(_sandbox("stripe", "list_charges"), ensure_ascii=False),
                "is_error": False,
            },
        ],
    }
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")
