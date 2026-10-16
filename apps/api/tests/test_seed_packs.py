"""The seed packs (overdue invoice follow-up, refund triage) and the runtime features they need:
connector-node `for_each`, shared schemas and the generic reviewer item."""

import asyncio
import json
from datetime import UTC, datetime
from functools import cache

import pytest
from jsonschema import Draft202012Validator
from temporalio.exceptions import ApplicationError

from app import db, settings
from app.defs.loader import load_bundle
from app.models.runs import Run
from app.routers import tasks
from app.runtime import agent, gateway, providers
from app.runtime.drivers import ToolResult
from app.worker import activities
from app.worker.activities import NodeCall
from app.worker.workflow import PackRunner
from tests.test_tool_results import _seal
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

AS_OF = "2026-10-13"

# --- connector for_each ------------------------------------------------------------------------------


def _permit() -> gateway.PolicyDecision:
    return gateway.PolicyDecision(
        verdict=gateway.PERMIT, reason_codes=["APPROVAL_GRANTED"], ref="policy/default"
    )


def _deny() -> gateway.PolicyDecision:
    return gateway.PolicyDecision(
        verdict=gateway.DENY, reason_codes=["ACTION_CLASS_DENIED"], ref="policy/default"
    )


class StubGateway:
    """Records each call's args and answers from `answers` (one per call; the last repeats)."""

    def __init__(self, answers: list | None = None) -> None:
        self.calls: list[dict] = []
        self.approved: list[bool] = []
        self._answers = answers or [(_permit(), None)]

    def __call__(self, *, snapshot, tool_ref, args, approved, mode):
        self.calls.append(args)
        self.approved.append(approved)
        decision, result = self._answers[min(len(self.calls), len(self._answers)) - 1]
        if decision.verdict == gateway.PERMIT and result is None:
            result = ToolResult(ok=True, data={"id": f"r-{len(self.calls)}"}, mocked=True)
        return decision, result


def _call(drafts: list[dict], approved: bool = True) -> NodeCall:
    state = {
        "input": {},
        "memory": [],
        "nodes": {"draft": {"output": {"drafts": drafts}}},
        "approvals": {"send": True} if approved else {},
    }
    return NodeCall(run_id="run_x", snapshot={}, node_id="send", state=state, attempt=2)


@pytest.fixture
def stub(monkeypatch):
    def install(answers: list | None = None) -> StubGateway:
        fake = StubGateway(answers)
        monkeypatch.setattr(activities.gateway, "call_tool", fake)
        return fake

    return install


def _send_node(for_each: str = "=nodes.draft.output.drafts") -> dict:
    return {
        "id": "send",
        "type": "connector",
        "config": {
            "tool": "gmail.create_draft",
            "for_each": for_each,
            "args": {"recipient_email": "=item.to", "subject": "=item.subject", "body": "=item.body"},
        },
        "routes": {"ok": "verify", "denied": "failed", "error": "failed"},
    }


def _drafts(n: int) -> list[dict]:
    return [
        {"to": f"c{i}@example.com", "subject": f"S{i}", "body": f"B{i}", "ref": f"R{i}"} for i in range(n)
    ]


class ForEach:
    """PackRunner's for_each path with its activities run inline: `_act` calls the activity method and
    `_commit` records what each step would write, so the loop and the activities are tested together."""

    def __init__(self, monkeypatch, node: dict, drafts: list[dict], approved: bool = True) -> None:
        self.commits: list[tuple[int, list]] = []  # (step, [(type, data), ...]) per committed activity
        self.acts: list[tuple[str, bool]] = []  # (activity, side_effects) per activity run
        self.runner = PackRunner()
        self.runner._run_id = "run_x"
        self.runner._snapshot = {"defs": {"workflow": {"w": {"body": {"nodes": [node]}}}}}
        self.runner._state = {
            "input": {},
            "memory": [],
            "nodes": {"draft": {"output": {"drafts": drafts}}},
            "approvals": {"send": True} if approved else {},
        }
        acts = activities.PackActivities()

        async def act(method, arg, timeout=None, *, retry=None, side_effects=False):
            self.acts.append((method.__name__, side_effects))
            return getattr(acts, method.__name__)(arg)

        self.runner._act = act
        monkeypatch.setattr(
            activities, "_commit", lambda call, events, write=None: self.commits.append((call.step, events))
        )
        monkeypatch.setattr(activities, "_recorded_tool_call", lambda *_: activities.RecordedCall())  # no DB

    def run(self, attempt: int = 2) -> tuple:
        return asyncio.run(self.runner._for_each("send", attempt))

    def events(self) -> list:
        return [e for _, events in self.commits for e in events]

    def types(self) -> list[str]:
        return [t for t, _ in self.events()]


def test_for_each_calls_the_tool_once_per_item_with_item_bound_args(stub, monkeypatch):
    fake, flow = stub(), ForEach(monkeypatch, _send_node(), _drafts(3))
    output, route = flow.run()
    assert fake.calls == [
        {"recipient_email": f"c{i}@example.com", "subject": f"S{i}", "body": f"B{i}"} for i in range(3)
    ]
    assert fake.approved == [True, True, True]  # the node's one approval covers every item
    assert route == "ok"
    assert output == {"results": [{"id": "r-1"}, {"id": "r-2"}, {"id": "r-3"}]}
    calls = [d for t, d in flow.events() if t == "tool.call"]
    assert [c["id"] for c in calls] == ["tc_send_2_0", "tc_send_2_1", "tc_send_2_2"]
    assert flow.types() == ["node.started", "tool.call", "tool.call", "tool.call", "node.completed"]
    assert flow.events()[-1][1] == {"route": "ok", "summary": "Made 3 calls, one per item."}


def test_each_for_each_item_is_its_own_side_effecting_step(stub, monkeypatch):
    stub()
    flow = ForEach(monkeypatch, _send_node(), _drafts(3))
    flow.run()
    assert flow.acts == [
        ("plan_for_each", False),
        ("for_each_call", True),
        ("for_each_call", True),
        ("for_each_call", True),
        ("finish_for_each", False),
    ]
    # One commit per activity, each at its own step: every item's tool.call has its own event key.
    assert [[t for t, _ in events] for _, events in flow.commits] == [
        ["node.started"],
        ["tool.call"],
        ["tool.call"],
        ["tool.call"],
        ["node.completed"],
    ]
    steps = [step for step, _ in flow.commits]
    assert steps == sorted(set(steps))


def test_for_each_without_the_approval_asks_the_gateway_unapproved(stub, monkeypatch):
    fake = stub()
    ForEach(monkeypatch, _send_node(), _drafts(2), approved=False).run()
    assert fake.approved == [False, False]


def test_for_each_stops_at_the_first_denied_item(stub, monkeypatch):
    fake = stub([(_permit(), None), (_deny(), None)])
    flow = ForEach(monkeypatch, _send_node(), _drafts(3))
    assert flow.run() == (None, "denied")
    assert len(fake.calls) == 2
    assert flow.types() == ["node.started", "tool.call", "tool.call", "node.failed"]
    assert flow.events()[-1][1] == {"status": "BLOCKED", "route": "denied", "error": "ACTION_CLASS_DENIED"}


def test_for_each_stops_at_the_first_failed_item(stub, monkeypatch):
    failed = ToolResult(ok=False, data=None, mocked=True, error="quota exceeded")
    fake = stub([(_permit(), failed)])
    flow = ForEach(monkeypatch, _send_node(), _drafts(3))
    assert flow.run() == (None, "error")
    assert len(fake.calls) == 1
    assert flow.events()[-1] == ("node.failed", {"route": "error", "error": "quota exceeded"})


def test_for_each_over_fifty_items_fails_without_calling(stub, monkeypatch):
    fake = stub()
    flow = ForEach(monkeypatch, _send_node(), _drafts(51))
    assert flow.run() == (None, "error")
    assert fake.calls == []
    assert flow.types() == ["node.started", "node.failed"]
    data = flow.events()[-1][1]
    assert data["route"] == "error" and "50" in data["error"]


def test_for_each_that_is_not_a_list_fails_without_calling(stub, monkeypatch):
    fake = stub()
    flow = ForEach(monkeypatch, _send_node("=nodes.draft.output"), _drafts(1))
    assert flow.run() == (None, "error") and fake.calls == []


def test_a_cel_error_in_any_item_fails_before_any_call(stub, monkeypatch):
    fake = stub()
    drafts = _drafts(3)
    del drafts[2]["subject"]  # only the last item cannot resolve its args
    flow = ForEach(monkeypatch, _send_node(), drafts)
    with pytest.raises(ApplicationError) as err:
        flow.run()
    assert err.value.type == "CelError" and err.value.non_retryable
    assert fake.calls == [] and flow.commits == []


def test_for_each_over_no_items_makes_no_calls(stub, monkeypatch):
    fake = stub()
    flow = ForEach(monkeypatch, _send_node(), [])
    assert flow.run() == ({"results": []}, "ok") and fake.calls == []


def test_for_each_items_are_bound_only_while_their_args_resolve(stub, monkeypatch):
    stub()
    flow = ForEach(monkeypatch, _send_node(), _drafts(1))
    flow.run()
    assert "item" not in flow.runner._state


def test_a_connector_without_for_each_keeps_its_single_call(stub, monkeypatch):
    fake = stub()
    monkeypatch.setattr(activities, "_recorded_tool_call", lambda *_: activities.RecordedCall())  # no DB
    node = {
        "id": "send",
        "type": "connector",
        "config": {"tool": "gmail.create_draft", "args": {"recipient_email": "a@example.com"}},
        "routes": {"ok": "verify", "error": "failed"},
    }
    state = {"input": {}, "nodes": {}, "memory": [], "approvals": {"send": True}}
    step = activities._connector(NodeCall("run_x", {}, "send", state, attempt=2), node)
    assert fake.calls == [{"recipient_email": "a@example.com"}] and fake.approved == [True]
    assert step.route == "ok" and [d["id"] for t, d in step.events if t == "tool.call"] == ["tc_send_2"]


def _tool_calls(conn, run_id: str) -> list[dict]:
    return [e["data"] for e in _entries(conn, run_id) if e["type"] == "tool.call"]


def test_a_for_each_item_retried_after_its_commit_makes_no_second_call(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, _ = _new_run(runtime_env)
    snapshot = {"defs": {"workflow": {"w": {"body": {"nodes": [_send_node()]}}}}}
    item = activities.ItemCall(run_id, snapshot, "send", 1, 4, 0, {"recipient_email": "a@example.com"}, True)
    first = activities.PackActivities().for_each_call(item)
    # Temporal retries the activity when its result is lost after the commit landed (worker lost, timeout).
    again = activities.PackActivities().for_each_call(item)
    assert len(fake.calls) == 1
    assert again == first == {"route": None, "data": {"id": "r-1"}}
    [entry] = _tool_calls(runtime_env, run_id)
    assert entry["id"] == "tc_send_1_0"
    assert "result" not in entry  # the sealed receipt never holds connector data
    assert _tool_results(runtime_env, run_id) == [("send:1:tool.call:4", {"id": "r-1"})]


def _tool_results(conn, run_id: str) -> list[tuple[str, object]]:
    conn.commit()
    rows = conn.execute(
        "SELECT event_key, result FROM tool_results WHERE run_id = %s ORDER BY event_key", (run_id,)
    ).fetchall()
    return [(r["event_key"], r["result"]) for r in rows]


def test_a_tool_result_is_stored_only_with_its_receipt_entry(runtime_env, stub, monkeypatch):  # noqa: F811
    stub()
    run_id, _ = _new_run(runtime_env)
    snapshot = {"defs": {"workflow": {"w": {"body": {"nodes": [_send_node()]}}}}}
    item = activities.ItemCall(run_id, snapshot, "send", 1, 4, 0, {"recipient_email": "a@example.com"}, True)

    def lost(conn, run_id, events):
        raise RuntimeError("connection lost before the receipt entry")

    monkeypatch.setattr(activities, "record_events", lost)
    with pytest.raises(RuntimeError):
        activities.PackActivities().for_each_call(item)
    assert _tool_results(runtime_env, run_id) == [] and _tool_calls(runtime_env, run_id) == []


def test_a_denied_for_each_item_retried_after_its_commit_stays_denied_without_a_call(runtime_env, stub):  # noqa: F811
    fake = stub([(_deny(), None)])
    run_id, _ = _new_run(runtime_env)
    snapshot = {"defs": {"workflow": {"w": {"body": {"nodes": [_send_node()]}}}}}
    item = activities.ItemCall(run_id, snapshot, "send", 1, 4, 0, {"recipient_email": "a@example.com"}, False)
    first = activities.PackActivities().for_each_call(item)
    again = activities.PackActivities().for_each_call(item)
    assert len(fake.calls) == 1
    assert again == first == {"route": "denied", "data": None}
    assert _tool_results(runtime_env, run_id) == []  # a denied call has no result to keep


def test_a_single_connector_node_retried_after_its_commit_makes_no_second_call(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, _ = _new_run(runtime_env)
    node = {
        "id": "send",
        "type": "connector",
        "config": {"tool": "gmail.create_draft", "args": {"recipient_email": "a@example.com"}},
        "routes": {"ok": "verify", "error": "failed"},
    }
    snapshot = {"defs": {"workflow": {"w": {"body": {"nodes": [node]}}}}}
    state = {"input": {}, "nodes": {}, "memory": [], "approvals": {"send": True}}
    call = NodeCall(run_id, snapshot, "send", state, attempt=1, step=4)
    first = activities.PackActivities().run_node(call)
    again = activities.PackActivities().run_node(call)
    assert len(fake.calls) == 1
    assert again == first == {"output": {"id": "r-1"}, "route": "ok"}
    [entry] = _tool_calls(runtime_env, run_id)
    assert entry["id"] == "tc_send_1" and "result" not in entry
    assert _tool_results(runtime_env, run_id) == [("send:1:tool.call:4", {"id": "r-1"})]


def test_a_read_keeps_no_result_and_its_retry_reads_again(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, snapshot = _new_run(runtime_env)  # the recon pack pins shopify.list_orders, a read
    call = NodeCall(run_id, snapshot, "orders", {}, attempt=1, step=3)
    first = activities._tool_call(call, "shopify.list_orders", {"limit": 5}, "tc_orders_1", False)
    assert first.write is None  # nothing kept for a read
    activities._commit(call, [first.event], first.write)
    # Temporal retries the activity after its commit landed: the read runs again for its data.
    again = activities._tool_call(call, "shopify.list_orders", {"limit": 5}, "tc_orders_1", False)
    assert len(fake.calls) == 2
    assert first.data == {"id": "r-1"} and again.data == {"id": "r-2"}
    assert again.event[1]["id"] == "tc_orders_1" and again.failed is None
    assert _tool_results(runtime_env, run_id) == []
    assert [e["id"] for e in _tool_calls(runtime_env, run_id)] == ["tc_orders_1"]


def test_a_read_that_fails_when_read_again_is_retried_not_recorded(runtime_env, stub):  # noqa: F811
    failed = ToolResult(ok=False, data=None, mocked=True, error="quota exceeded")
    stub([(_permit(), None), (_permit(), failed)])
    run_id, snapshot = _new_run(runtime_env)
    call = NodeCall(run_id, snapshot, "orders", {}, attempt=1, step=3)
    first = activities._tool_call(call, "shopify.list_orders", {}, "tc_orders_1", False)
    activities._commit(call, [first.event], first.write)
    with pytest.raises(ApplicationError) as err:
        activities._tool_call(call, "shopify.list_orders", {}, "tc_orders_1", False)
    assert err.value.type == "ReadAgain" and not err.value.non_retryable
    assert [e["id"] for e in _tool_calls(runtime_env, run_id)] == ["tc_orders_1"]


def test_a_write_still_keeps_its_result_for_a_retry(runtime_env, stub):  # noqa: F811
    stub()
    run_id, _ = _new_run(runtime_env)
    snapshot = {"defs": {"workflow": {"w": {"body": {"nodes": [_send_node()]}}}}}  # unknown class: kept
    item = activities.ItemCall(run_id, snapshot, "send", 1, 4, 0, {"recipient_email": "a@example.com"}, True)
    activities.PackActivities().for_each_call(item)
    assert _tool_results(runtime_env, run_id) == [("send:1:tool.call:4", {"id": "r-1"})]


def _agent_use(run_id: str, block_id: str = "toolu_1") -> activities.ToolUse:
    name = agent.tool_name("gmail.create_draft")
    block = {"id": block_id, "name": name, "input": {"recipient_email": "a@example.com"}}
    return activities.ToolUse(run_id, {}, "draft", 1, 5, block, [name])


def test_an_agent_tool_call_retried_after_its_commit_makes_no_second_call(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, _ = _new_run(runtime_env)
    first = activities.PackActivities().tool_call(_agent_use(run_id))
    again = activities.PackActivities().tool_call(_agent_use(run_id))
    assert len(fake.calls) == 1
    assert (
        again
        == first
        == {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": json.dumps({"id": "r-1"}),
            "is_error": False,
        }
    )
    assert [e["id"] for e in _tool_calls(runtime_env, run_id)] == ["toolu_1"]
    assert _tool_results(runtime_env, run_id) == [("draft:1:tool.call:5", {"id": "r-1"})]


def test_a_denied_agent_tool_call_retried_stays_denied_without_a_call(runtime_env, stub):  # noqa: F811
    fake = stub([(_deny(), None)])
    run_id, _ = _new_run(runtime_env)
    first = activities.PackActivities().tool_call(_agent_use(run_id))
    again = activities.PackActivities().tool_call(_agent_use(run_id))
    assert len(fake.calls) == 1
    assert again == first and first["content"] == "Not permitted: ACTION_CLASS_DENIED" and first["is_error"]


def test_an_agent_tool_call_on_a_sealed_run_is_refused_without_a_call(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, _ = _new_run(runtime_env)
    _seal(run_id)
    with pytest.raises(ApplicationError) as err:
        activities.PackActivities().tool_call(_agent_use(run_id))
    assert err.value.type == activities.RUN_SEALED and err.value.non_retryable
    assert fake.calls == [] and _tool_calls(runtime_env, run_id) == []


def test_an_agent_tool_call_retried_after_the_seal_is_refused_without_a_call(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, _ = _new_run(runtime_env)
    activities.PackActivities().tool_call(_agent_use(run_id))
    _seal(run_id)  # the seal deletes the kept result: the retry cannot rebuild it and must not call again
    with pytest.raises(ApplicationError) as err:
        activities.PackActivities().tool_call(_agent_use(run_id))
    assert err.value.type == activities.RUN_SEALED and err.value.non_retryable
    assert len(fake.calls) == 1


def test_a_for_each_item_on_a_sealed_run_is_refused_without_a_call(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, _ = _new_run(runtime_env)
    _seal(run_id)
    snapshot = {"defs": {"workflow": {"w": {"body": {"nodes": [_send_node()]}}}}}
    item = activities.ItemCall(run_id, snapshot, "send", 1, 4, 0, {"recipient_email": "a@example.com"}, True)
    with pytest.raises(ApplicationError) as err:
        activities.PackActivities().for_each_call(item)
    assert err.value.type == activities.RUN_SEALED and err.value.non_retryable
    assert fake.calls == []


def test_a_single_connector_node_on_a_sealed_run_is_refused_without_a_call(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, _ = _new_run(runtime_env)
    _seal(run_id)
    node = {
        "id": "send",
        "type": "connector",
        "config": {"tool": "gmail.create_draft", "args": {"recipient_email": "a@example.com"}},
        "routes": {"ok": "verify", "error": "failed"},
    }
    snapshot = {"defs": {"workflow": {"w": {"body": {"nodes": [node]}}}}}
    state = {"input": {}, "nodes": {}, "memory": [], "approvals": {"send": True}}
    with pytest.raises(ApplicationError) as err:
        activities.PackActivities().run_node(NodeCall(run_id, snapshot, "send", state, attempt=1, step=4))
    assert err.value.type == activities.RUN_SEALED and err.value.non_retryable
    assert fake.calls == []


def test_an_agent_read_keeps_no_result_and_its_retry_reads_again(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, snapshot = _new_run(runtime_env)  # the recon pack pins shopify.list_orders, a read
    name = agent.tool_name("shopify.list_orders")
    use = activities.ToolUse(
        run_id, snapshot, "orders", 1, 3, {"id": "toolu_r", "name": name, "input": {}}, [name]
    )
    first = activities.PackActivities().tool_call(use)
    assert _tool_results(runtime_env, run_id) == []
    again = activities.PackActivities().tool_call(use)
    assert len(fake.calls) == 2
    assert first["content"] == json.dumps({"id": "r-1"}) and again["content"] == json.dumps({"id": "r-2"})
    assert [e["id"] for e in _tool_calls(runtime_env, run_id)] == ["toolu_r"]


def test_a_write_whose_data_is_null_is_rebuilt_on_retry_without_a_call(runtime_env, stub):  # noqa: F811
    fake = stub([(_permit(), ToolResult(ok=True, data=None, mocked=True))])
    run_id, _ = _new_run(runtime_env)
    first = activities.PackActivities().tool_call(_agent_use(run_id))
    again = activities.PackActivities().tool_call(_agent_use(run_id))
    assert len(fake.calls) == 1
    assert again == first and first["content"] == "null" and not first["is_error"]


def test_a_recorded_write_whose_kept_result_is_missing_fails_for_good(runtime_env, stub):  # noqa: F811
    fake = stub()
    run_id, _ = _new_run(runtime_env)
    use = _agent_use(run_id)
    entry = {"id": "toolu_1", "ok": True, "action_class": "write", "policy": {"verdict": gateway.PERMIT}}
    with db.connect() as conn:
        key = activities.event_key(use.node_id, use.attempt, "tool.call", use.step)
        activities.record_events(conn, run_id, [(key, "tool.call", use.node_id, entry)])
        conn.commit()
    with pytest.raises(ApplicationError) as err:
        activities.PackActivities().tool_call(use)
    assert err.value.type == "ResultLost" and err.value.non_retryable
    assert fake.calls == []


def test_an_agent_tool_use_without_an_id_answers_with_an_empty_id(runtime_env, stub):  # noqa: F811
    stub()
    run_id, snapshot = _new_run(runtime_env)
    use = activities.ToolUse(run_id, snapshot, "draft", 1, 5, {"id": None, "name": "unknown__tool"}, [])
    block = activities.PackActivities().tool_call(use)
    assert block["tool_use_id"] == "" and block["content"] == "Not permitted: TOOL_NOT_OFFERED"
    assert [e["id"] for e in _tool_calls(runtime_env, run_id)] == [""]


# --- reviewer records ----------------------------------------------------------------------------------


def test_a_generic_review_item_becomes_a_reviewer_record():
    item = {
        "ref": "INV-1042",
        "date": "2026-09-22",
        "amount_minor": 125000,
        "currency": "USD",
        "flag": "Overdue 21 days (firm)",
        "note": "21 days past due, so a firm reminder.",
    }
    record = tasks._record(item, 0)
    assert record.id == "INV-1042"
    assert (record.order.ref, record.order.date, record.order.amount) == (
        "INV-1042",
        "2026-09-22",
        "$1,250.00",
    )
    # No counterpart: nothing to name, rather than the word "None".
    assert record.order.payment_ref == "" and record.payment.ref == ""
    assert record.flag == "Overdue 21 days (firm)"
    assert record.agent_note == "21 days past due, so a firm reminder."
    assert record.kind == "item"


def test_a_support_case_is_an_item_with_no_amount():
    """The support triage's review item: a Gmail thread, no money and a category flag. Its record says it is
    an item, so the reviewer sees a plain card, not an order and its payment."""
    item = {
        "ref": "thread-18c2f",
        "date": "2026-10-14",
        "amount_minor": 0,
        "currency": "USD",
        "flag": "Complaint",
        "note": "Sorted without the decision model; check the category and the planned reply.",
    }
    record = tasks._record(item, 0)
    assert record.kind == "item"
    assert (record.id, record.order.ref, record.order.date) == ("thread-18c2f", "thread-18c2f", "2026-10-14")
    assert record.order.amount == ""  # no "$0.00"
    assert record.order.payment_ref == "" and record.payment.ref == ""
    assert "None" not in record.model_dump_json()
    assert record.model_dump(by_alias=True)["kind"] == "item"


def test_a_generic_review_item_names_its_counterpart():
    item = {
        "ref": "#1003",
        "date": "2026-10-12",
        "amount_minor": 2350,
        "currency": "USD",
        "flag": "Proposed: approve",
        "note": "Order #1003 is found, paid and not refunded.",
        "counterpart_ref": "ch_3Sandbox1003",
    }
    record = tasks._record(item, 3)
    assert record.id == "#1003"
    assert record.order.payment_ref == "ch_3Sandbox1003" and record.payment.ref == "ch_3Sandbox1003"


@pytest.mark.parametrize(
    ("note", "shown"),
    [
        ("Priya (priya.nair@example.com) says the item was used.", "Priya (Hidden) says the item was used."),
        ("Reply to Priya.Nair+orders@mail.example.co.uk today.", "Reply to Hidden today."),
        ("She asked us to call +1 415-555-0100 or (415) 555 0100.", "She asked us to call Hidden or Hidden."),
        ("Call 4155550100.", "Call Hidden."),
        ("Due 2026-09-22, 21 days late: firm.", "Due 2026-09-22, 21 days late: firm."),
        ("Call +1 555-123-4567 2026-10-13 please.", "Call Hidden please."),
        ("Ring 415 555 0100 1234 5678 now.", "Ring Hidden now."),
        ("Reconcile 2026-10-06..2026-10-12 now.", "Reconcile 2026-10-06..2026-10-12 now."),
        ("Period 2026-09-01 - 2026-09-30 end.", "Period 2026-09-01 - 2026-09-30 end."),
        ("At 2026-10-01 12:30 sharp.", "At 2026-10-01 12:30 sharp."),
        ("Call 415-555-0100x23.", "Call Hidden."),
        ("Call 415-555-0100 ext. 23 now.", "Call Hidden now."),
        ("Call-4155550100 now.", "Call-Hidden now."),
        ("Phone,4155550100 now.", "Phone,Hidden now."),
        ("Total 1,250,000 due.", "Total 1,250,000 due."),
        ("Order INV-123456789 open.", "Order INV-123456789 open."),
        ("Line $1250000.00 open.", "Line $1250000.00 open."),
        ("Charge ch_3Sandbox1003 ok.", "Charge ch_3Sandbox1003 ok."),
        ("Order #1003 for $1250000.00 (125000 minor) on ch_3Sandbox1003.", None),
    ],
)
def test_a_generic_record_hides_emails_and_phone_numbers_in_its_note_and_flag(note, shown):
    item = {"ref": "#1003", "date": "2026-10-12", "amount_minor": 2350, "flag": note, "note": note}
    record = tasks._record(item, 0)
    assert record.agent_note == (shown or note)
    assert record.flag == (shown or note)


def test_an_email_in_a_note_reaches_the_reviewer_as_hidden():
    item = {
        "ref": "#1003",
        "date": "2026-10-12",
        "amount_minor": 2350,
        "currency": "USD",
        "flag": "Proposed: partial 50% for priya.nair@example.com",
        "note": "priya.nair@example.com says the item was opened.",
    }
    record = tasks._record(item, 0)
    assert record.agent_note == "Hidden says the item was opened."
    assert record.flag == "Proposed: partial 50% for Hidden"
    assert "@" not in record.model_dump_json()


def test_a_reconciliation_mismatch_keeps_its_record_shape():
    item = {
        "order_id": "#1004",
        "charge_id": "ch_3Sandbox1004",
        "kind": "amount_mismatch",
        "date": "2026-10-07",
        "amount_minor": 8966,
        "amount_diff_minor": -290,
        "currency": "USD",
        "explanation": "The charge is short by the card fee.",
    }
    record = tasks._record(item, 0)
    assert record.kind == "reconciliation"
    assert record.id == "#1004" and record.flag == "Amount mismatch"
    assert (record.order.ref, record.order.amount, record.order.payment_ref) == (
        "#1004",
        "$89.66",
        "ch_3Sandbox1004",
    )
    assert (record.payment.ref, record.payment.date, record.payment.amount) == (
        "ch_3Sandbox1004",
        "2026-10-07",
        "$86.76",
    )
    assert record.agent_note == "The charge is short by the card fee."


# --- fake agent scripts -------------------------------------------------------------------------------


@cache
def _bundle():
    return load_bundle(settings.defs_dir())


def _schema(key: str) -> dict:
    return _bundle().get("schema", key).body


def _valid(schema_key: str, value) -> None:
    errors = [e.message for e in Draft202012Validator(_schema(schema_key)).iter_errors(value)]
    assert errors == [], errors


def _sandbox(connector: str, tool: str) -> dict:
    path = settings.defs_dir() / "connectors" / "sandbox" / connector / f"{tool}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _plan() -> dict:
    inputs = {"invoices": _sandbox("stripe", "list_invoices"), "as_of": AS_OF, "rules": []}
    return providers.fake_collections(inputs)


def _triage() -> dict:
    inputs = {
        "threads": _sandbox("gmail", "list_threads"),
        "orders": _sandbox("shopify", "list_orders"),
        "charges": _sandbox("stripe", "list_charges"),
        "rules": [],
    }
    return providers.fake_refunds(inputs)


def test_the_collections_script_plans_one_reminder_per_overdue_invoice():
    plan = _plan()
    _valid("overdue-invoice-follow-up/plan", plan)
    _valid("shared/review-items", plan["review_items"])
    assert [m["to"] for m in plan["messages"]] == [
        "accounts.harborcafe@example.net",
        "billing.lumenstudio@example.net",
        "ap.northfieldgym@example.net",
        "ben.hartley@example.com",
    ]
    assert [i["flag"] for i in plan["review_items"]] == [
        "Overdue 5 days (gentle)",
        "Overdue 21 days (firm)",
        "Overdue 50 days (final notice)",
        "Overdue 9 days (gentle)",
    ]
    assert [i["ref"] for i in plan["review_items"]] == ["INV-0107", "INV-0098", "INV-0086", "INV-0104"]
    assert [m["ref"] for m in plan["messages"]] == [i["ref"] for i in plan["review_items"]]
    firm = plan["messages"][1]
    assert firm["about"] == "Invoice INV-0098 is 21 days overdue"
    assert firm["facts"] == [
        "Invoice number: INV-0098",
        "Amount due: 1,250.00 USD",
        "Due date: 2026-09-22",
        "Stage: firm (21 days overdue)",
    ]
    assert (
        plan["review_items"][1]["amount_minor"] == 125000 and plan["review_items"][1]["date"] == "2026-09-22"
    )


def test_the_collections_script_with_nothing_overdue_plans_nothing():
    plan = providers.fake_collections(
        {"invoices": _sandbox("stripe", "list_invoices"), "as_of": "2026-08-01"}
    )
    _valid("overdue-invoice-follow-up/plan", plan)
    assert plan["messages"] == [] and plan["review_items"] == []


def test_the_refunds_script_follows_the_refund_policy():
    triage = _triage()
    _valid("refund-triage/triage", triage)
    _valid("shared/review-items", triage["review_items"])
    cases = triage["cases"]  # oldest request first
    assert [c["thread_id"] for c in cases] == [
        "18f3a0c1d2e41003",
        "18f3a0c1d2e41005",
        "18f3a0c1d2e41088",
        "18f3a0c1d2e41103",
    ]
    assert [c["recommendation"] for c in cases] == ["approve", "partial", "decline", "decline"]
    assert [c["order_id"] for c in cases] == ["#1003", "#1005", None, "#1003"]
    assert [c["charge_id"] for c in cases] == ["ch_3Sandbox1003", "ch_3Sandbox1005", None, "ch_3Sandbox1003"]
    assert [c["requested_minor"] for c in cases] == [2350, 15000, 4500, 2350]
    assert [c["amount_minor"] for c in cases] == [2350, 7500, 0, 0]
    assert "opened or used" in cases[1]["reason"]
    assert "No order #1088" in cases[2]["reason"]
    assert "repeats the earlier request 18f3a0c1d2e41003" in cases[3]["reason"]
    assert [c["from"] for c in cases] == [
        "priya.nair@example.com",
        "lena.fischer@example.com",
        "daniel.price@example.com",
        "priya.nair@example.com",
    ]
    assert [m["to"] for m in triage["messages"]] == [c["from"] for c in cases]
    assert all(any("proposed" in f for f in m["facts"]) for m in triage["messages"])
    # Every review item has its own ref: the repeated request goes by its thread id.
    assert [i["ref"] for i in triage["review_items"]] == ["#1003", "#1005", "#1088", "18f3a0c1d2e41103"]
    # Each reply carries its review item's ref, so a reviewer's resolution reaches its draft; the
    # order number the customer gave stays in the reply's facts.
    assert [m["ref"] for m in triage["messages"]] == [i["ref"] for i in triage["review_items"]]
    assert triage["messages"][3]["facts"][0] == "Order number: #1003"
    assert "counterpart_ref" not in triage["review_items"][2]
    assert triage["review_items"][0]["counterpart_ref"] == "ch_3Sandbox1003"


def _thread(thread_id: str, text: str, at: str = "2026-10-12T08:00:00Z") -> dict:
    return {"threadId": thread_id, "messageTimestamp": at, "sender": "a@example.com", "messageText": text}


def test_the_refunds_script_declines_an_already_refunded_payment():
    orders = _sandbox("shopify", "list_orders")
    charges = _sandbox("stripe", "list_charges")
    charges["data"] = [
        c | {"refunded": True, "amount_refunded": c["amount"]}
        if c["metadata"].get("order_id") == "#1002"
        else c
        for c in charges["data"]
    ]
    orders["orders"] = [
        o | {"financial_status": "refunded"} if o["name"] == "#1006" else o for o in orders["orders"]
    ]
    threads = {
        "messages": [
            _thread("t1", "Please refund order #1002, $129.00."),
            _thread("t2", "Please refund order #1006, $32.99."),
            _thread("t3", "Please refund order #1001."),
            _thread("t4", "Refund please, $10.00."),
        ]
    }
    triage = providers.fake_refunds({"threads": threads, "orders": orders, "charges": charges})
    _valid("refund-triage/triage", triage)
    cases = triage["cases"]
    assert [c["recommendation"] for c in cases] == ["decline", "decline", "approve", "decline"]
    assert "already refunded" in cases[0]["reason"] and "already refunded" in cases[1]["reason"]
    assert cases[2]["requested_minor"] == cases[2]["amount_minor"] == 4500  # no amount given: the order total
    assert cases[3]["order_id"] is None and triage["messages"][3]["ref"] == "t4"
    assert triage["review_items"][3]["ref"] == "t4"
    assert triage["messages"][3]["facts"][0] == "Order number: not given"


def test_the_writer_script_drafts_one_email_per_item():
    for messages in (_plan()["messages"], _triage()["messages"]):
        review = {"outcome": "resolved", "note": "", "resolutions": []}
        drafts = providers.fake_writer({"items": messages, "review": review, "tone": "firm but friendly"})
        _valid("shared/drafts", drafts)
        assert len(drafts["drafts"]) == len(messages) == 4
        for draft, item in zip(drafts["drafts"], messages, strict=True):
            assert (draft["to"], draft["subject"]) == (item["to"], item["about"])
            assert draft["body"].startswith("Hello,") and draft["body"].endswith("Accounts team")
            assert all(fact.rstrip(".") in draft["body"] for fact in item["facts"])
            assert draft["ref"] == item["ref"]  # copied from the item, not parsed from a fact


def test_the_writer_script_falls_back_to_the_first_fact_without_a_ref():
    item = {"to": "a@example.com", "about": "Hello", "facts": ["Invoice number: INV-0107", "Due."]}
    [draft] = providers.fake_writer({"items": [item], "review": None, "tone": "warm"})["drafts"]
    assert draft["ref"] == "INV-0107"


def test_the_writer_input_matches_its_schema():
    _valid("shared/draft-request", {"items": _plan()["messages"], "review": None, "tone": "warm and clear"})


# --- end to end (time-skipping Temporal, Postgres, fake models, sandbox connectors) ---------------------

SEED_RUNS = {
    "overdue-invoice-follow-up": {
        "input": {"as_of": AS_OF},
        "show": ["INV-0107", "INV-0098", "INV-0086", "INV-0104"],
        "agents": {"plan", "draft"},
        "reads": ["stripe.list_invoices"],
    },
    "refund-triage": {
        "input": {"since": "2026-10-06", "until": AS_OF},
        "show": ["#1003", "#1005", "#1088", "18f3a0c1d2e41103"],
        "agents": {"triage", "draft"},
        "reads": ["gmail.list_threads", "shopify.list_orders", "stripe.list_charges"],
    },
}


@pytest.mark.parametrize("pack", list(SEED_RUNS))
def test_a_seed_pack_runs_through_review_and_approval_to_drafts(runtime_env, pack):  # noqa: F811
    conn, spec = runtime_env, SEED_RUNS[pack]
    run_id, snapshot = _new_run(conn, pack=pack, input=spec["input"])

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot, spec["input"])
        review = await _waiting(handle, "review")
        [task] = _tasks(conn, run_id)
        assert [i["ref"] for i in task["payload"]["show"]] == spec["show"]
        row = {**task, "run_id": run_id, "run_title": pack, "created_at": datetime.now(UTC)}
        records = tasks.real_task(row).records
        assert [r.id for r in records] == spec["show"]
        assert not _drafts_written(conn, run_id)  # nothing is written while a person reviews
        resolutions = [{"order_id": spec["show"][0], "resolution": "explained", "note": "Checked."}]
        await handle.signal(
            PackRunner.human_result, args=[review["task_id"], "resolved", "Looks right.", resolutions]
        )

        approval = await _waiting(handle, "approve")
        pending = next(t for t in _tasks(conn, run_id) if t["kind"] == "approval")
        assert pending["payload"]["summary"] == "Create 4 email drafts in Gmail"
        assert pending["payload"]["tool_ref"] == "gmail.create_draft" and pending["payload"]["mocked"] is True
        assert not _drafts_written(conn, run_id)  # nothing is written before the approval
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"

    _assert_sealed(conn, run_id, snapshot, "COMPLETED")
    entries = _entries(conn, run_id)
    calls = [e for e in entries if e["type"] == "tool.call"]
    assert [c["data"]["tool_ref"] for c in calls if c["node_id"] != "send"] == spec["reads"]
    drafts = [c for c in calls if c["data"]["tool_ref"] == "gmail.create_draft"]
    assert [c["data"]["id"] for c in drafts] == [f"tc_send_1_{i}" for i in range(4)]
    assert all(
        c["data"]["ok"] and c["data"]["policy"]["reason_codes"] == ["APPROVAL_GRANTED"] for c in drafts
    )
    [granted] = [e for e in entries if e["type"] == "approval" and e["data"].get("status") == "granted"]
    assert min(c["seq"] for c in drafts) > granted["seq"]
    [completed] = [e for e in entries if e["type"] == "run.completed"]
    assert len(completed["data"]["deliverable"]["drafts"]) == 4 and completed["data"]["mocked"] is True
    assert {e["node_id"] for e in entries if e["type"] == "model.usage"} == spec["agents"]
    assert _run_row(conn, run_id)["status"] == "COMPLETED"
    finished = Run.model_validate(_run_row(conn, run_id)["projection"])
    assert finished.stages.verified == "done"  # the verify node passed
    result = finished.deliverable
    made = completed["data"]["deliverable"]["drafts"]
    assert result.kind == "Email drafts" and len(result.items) == 4
    assert [(r.label, r.value) for r in result.rows] == [("Drafts created", "4")]
    assert [i.label for i in result.items] == [f"{d['to']} — {d['subject']}" for d in made]
    assert [i.detail for i in result.items] == [d["body"][:160] for d in made]
    # Every call ran on sandbox data, so the headline says so and claims no email in Gmail.
    assert result.summary.startswith(
        "4 "
    ) and "were drafted on sandbox data. No email was created in Gmail" in (result.summary)
    human = next(t for t in _tasks(conn, run_id) if t["kind"] == "human")
    assert human["result"]["resolutions"] == [
        {"order_id": spec["show"][0], "resolution": "explained", "note": "Checked."}
    ]


def test_the_overdue_pack_with_nothing_overdue_completes_without_review(runtime_env):  # noqa: F811
    conn = runtime_env
    early = {"as_of": "2026-08-01"}
    run_id, snapshot = _new_run(conn, pack="overdue-invoice-follow-up", input=early)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot, early)
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")
    assert _tasks(conn, run_id) == []
    assert not _drafts_written(conn, run_id)
    finished = Run.model_validate(_run_row(conn, run_id)["projection"])
    assert finished.stages.verified == "not_required"  # nothing to do: no verification node ran
    result = finished.deliverable
    assert result.kind == "Email drafts" and result.items == []
    assert result.summary.endswith("none is overdue.")


def test_a_retried_draft_call_does_not_repeat_the_drafts_already_made(runtime_env, monkeypatch):  # noqa: F811
    conn, pack = runtime_env, "overdue-invoice-follow-up"
    spec = SEED_RUNS[pack]
    run_id, snapshot = _new_run(conn, pack=pack, input=spec["input"])
    real_call = gateway.call_tool
    seen: list[tuple[str, int]] = []  # (recipient, drafts already recorded when the call was made)

    def flaky(**kw):
        decision, result = real_call(**kw)
        if kw["tool_ref"] == "gmail.create_draft":
            seen.append((kw["args"]["recipient_email"], _recorded_drafts(run_id)))
            if len(seen) == 2:  # the second draft is made, then its activity fails before it commits
                raise RuntimeError("worker lost")
        return decision, result

    monkeypatch.setattr(activities.gateway, "call_tool", flaky)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot, spec["input"])
        review = await _waiting(handle, "review")
        await handle.signal(PackRunner.human_result, args=[review["task_id"], "resolved", "Fine."])
        approval = await _waiting(handle, "approve")
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "COMPLETED"
    recipients = [m["to"] for m in _plan()["messages"]]
    # Only the failed item is called again; each item's call sees every earlier item already recorded.
    assert seen == [
        (recipients[0], 0),
        (recipients[1], 1),
        (recipients[1], 1),
        (recipients[2], 2),
        (recipients[3], 3),
    ]
    drafts = [e for e in _entries(conn, run_id) if e["type"] == "tool.call" and e["node_id"] == "send"]
    assert [d["data"]["id"] for d in drafts] == [f"tc_send_1_{i}" for i in range(4)]
    _assert_sealed(conn, run_id, snapshot, "COMPLETED")


def _recorded_drafts(run_id: str) -> int:
    with db.connect() as c:
        return c.execute(
            "SELECT count(*) AS n FROM receipt_entries WHERE run_id = %s AND type = 'tool.call' "
            "AND data->>'tool_ref' = 'gmail.create_draft'",
            (run_id,),
        ).fetchone()["n"]


def _drafts_written(conn, run_id: str) -> bool:
    return any(
        e["type"] == "tool.call" and e["data"]["tool_ref"] == "gmail.create_draft"
        for e in _entries(conn, run_id)
    )


def test_repeated_event_types_in_one_step_get_distinct_keys():
    call = _call([])
    keyed = activities._keyed(
        call, [("node.started", {}), ("tool.call", {}), ("tool.call", {}), ("tool.call", {})]
    )
    keys = [k for k, *_ in keyed]
    assert keys[:2] == ["send:2:node.started:0", "send:2:tool.call:0"]  # the first keeps today's key
    assert len(set(keys)) == 4
