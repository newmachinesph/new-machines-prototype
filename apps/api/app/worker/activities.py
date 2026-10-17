"""PackRunner activities: every side effect of a run (database, model, tools) lives here, not in the workflow.

Each activity writes its events with `record_events`: receipt entry + projection update in one transaction.
Event keys are deterministic (`<node>:<attempt>:<type>:<step>`, the counters come from the workflow), so a
retried activity never appends an event twice. Errors that retrying cannot fix (bad config, invalid agent
output) raise a non-retryable ApplicationError whose message is safe to show in the receipt.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from jsonschema import Draft202012Validator
from psycopg.types.json import Jsonb
from temporalio import activity
from temporalio.exceptions import ApplicationError

from app import db, fees, settings
from app.defs.tool_names import action_name
from app.runtime import (
    agent,
    cel,
    decisions,
    drivers,
    gateway,
    memory,
    projection,
    providers,
    receipt,
    tracing,
)
from app.runtime.drivers import ToolResult, safe_message
from app.runtime.providers import ModelProvider, ToolSpec

MAX_TOKENS = 16000
DEFAULT_TASK_TIMEOUT_S = 86400
MODELS_KEY = "default"
MAX_REPORTED_ERRORS = 5
MAX_ERROR_CHARS = 300
MAX_FOR_EACH_ITEMS = 50  # a connector node's for_each makes at most this many calls
# Error types that stop the run whatever the node's error route says: a step whose publisher fee would go
# over the monthly cap or the run's budget (`fees.agent_fee_writer`).
STOP_ERROR_TYPES = {fees.SPEND_CAP, fees.BUDGET_EXCEEDED}
# Messages written here
SAFE_ERROR_TYPES = {"ConfigError", "CelError", "InputInvalid", "OutputInvalid", *STOP_ERROR_TYPES}
_OUTCOMES = {"human": {"resolved", "rejected", "timeout"}, "approval": {"granted", "denied", "timeout"}}
REVIEW_VERDICTS = {"HUMAN_REVIEW", "ESCALATED", "REVISION_REQUIRED"}
_FAILED_STATUS = {"rejected": "REJECTED", "denied": "REJECTED", "timeout": "TIMED_OUT"}
NETWORK_REVIEWER = "Network reviewer"  # a network reviewer as the buyer's timeline names them

SEALED = "receipt.sealed"
RUN_SEALED = "RunSealed"  # error type: the run's receipt is sealed, so nothing more may happen in it
RESULT_LOST = "ResultLost"  # error type: a recorded side-effecting call's kept result is missing
FINAL_STATUS = {"run.completed": "COMPLETED", "run.failed": "FAILED"}  # final event -> sealed status

Event = tuple[str, dict]  # (type, data); node id and key come from the activity's call


# --- inputs (one dataclass per activity, as Temporal recommends) ----------------------------------------


@dataclass
class NodeCall:
    run_id: str
    snapshot: dict
    node_id: str
    state: dict
    attempt: int = 1
    step: int = 0
    reason: str | None = None  # end nodes: why the run reached a failure end


@dataclass
class ModelCall:
    run_id: str
    snapshot: dict
    node_id: str
    attempt: int
    step: int
    profile: str
    system: str
    messages: list[dict]
    tools: list[dict]


@dataclass
class ToolUse:
    run_id: str
    snapshot: dict
    node_id: str
    attempt: int
    step: int
    block: dict  # a model tool_use block {"id", "name", "input"}
    offered: list[str]  # tool names the agent was given; anything else is refused


@dataclass
class ItemCall:
    """One for_each item of a connector node: its args are already resolved by plan_for_each."""

    run_id: str
    snapshot: dict
    node_id: str
    attempt: int
    step: int
    index: int
    args: dict
    approved: bool  # the node's approval covers every item


@dataclass
class AgentResult:
    run_id: str
    snapshot: dict
    node_id: str
    attempt: int
    step: int
    result: Any


@dataclass
class TaskDecision:
    run_id: str
    node_id: str
    attempt: int
    step: int
    kind: str  # human | approval
    task_id: str
    outcome: str  # human: resolved|rejected|timeout; approval: granted|denied|timeout
    note: str = ""
    by: str | None = None
    resolutions: list[dict] = field(default_factory=list)


@dataclass
class Failure:
    run_id: str
    node_id: str | None
    attempt: int
    step: int
    reason: str
    route: str | None = None
    node_failed: bool = True
    end_run: bool = True


# --- events -------------------------------------------------------------------------------------------


def event_key(node_id: str | None, attempt: int, type_: str, step: int) -> str:
    return f"{node_id or 'run'}:{attempt}:{type_}:{step}"


def _refuse_after_seal(conn, run_id: str, keys: list[str]) -> None:
    """A sealed receipt takes no new entries. A retry that only repeats recorded keys is allowed (it adds
    nothing); anything new is refused without retrying, which ends the workflow. This stops a workflow the
    API failed to start in time (its run is already sealed FAILED) from running at all."""
    sealed = conn.execute(
        "SELECT 1 FROM receipt_entries WHERE run_id = %s AND type = %s LIMIT 1", (run_id, SEALED)
    ).fetchone()
    if sealed is None or not keys:
        return
    known = conn.execute(
        "SELECT count(*) AS n FROM receipt_entries WHERE run_id = %s AND event_key = ANY(%s)", (run_id, keys)
    ).fetchone()["n"]
    if known < len(set(keys)):
        raise _sealed(run_id)


def _sealed(run_id: str) -> ApplicationError:
    """The non-retryable error for any attempt to add to a sealed run."""
    return _fatal(RUN_SEALED, f"run {run_id} is already finished; its receipt is sealed")


def record_events(conn, run_id: str, events: list[tuple[str, str, str | None, dict]]) -> int:
    """Append (event_key, type, node_id, data) entries and fold them into the projection. Does not commit.

    A run's final event (run.completed / run.failed) is followed by a `receipt.sealed` entry, so every
    finished run's receipt ends with its seal. Returns how many entries were new (0 on a retry)."""
    row = conn.execute(
        "SELECT projection, snapshot->'versions' AS versions, snapshot->'defs'->'pack' AS packs "
        "FROM runs WHERE id = %s FOR UPDATE",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"run {run_id} does not exist")
    _refuse_after_seal(conn, run_id, [key for key, *_ in events])
    current, added, seal = row["projection"], 0, None
    view = projection.deliverable_view(row["packs"])
    for key, type_, node_id, data in events:
        entry = receipt.append(conn, run_id, key, type_, node_id, data)
        if entry is not None:
            current = projection.apply_event(current, entry, view)
            added += 1
            if type_ in FINAL_STATUS:
                seal = (f"{key}:sealed", node_id, FINAL_STATUS[type_])
    if seal is not None:
        key, node_id, status = seal
        last = conn.execute(
            "SELECT max(seq) AS n FROM receipt_entries WHERE run_id = %s", (run_id,)
        ).fetchone()
        sealed = {"entry_count": last["n"], "versions": row["versions"] or [], "status": status}
        receipt.append(conn, run_id, key, SEALED, node_id, sealed)
        added += 1
        # The run is over: nothing of it may retry a call any more, so the results kept for retries go now.
        conn.execute("DELETE FROM tool_results WHERE run_id = %s", (run_id,))
    if added:
        projection.save(conn, run_id, current, current["status"])
    return added


def record(run_id: str, event_key: str, type: str, node_id: str | None, data: dict) -> None:
    """Record one event in its own transaction."""
    with db.connect() as conn:
        record_events(conn, run_id, [(event_key, type, node_id, data)])
        conn.commit()


def _keyed(call, events: list[Event]) -> list[tuple[str, str, str | None, dict]]:
    """Keys for one step's events. A type that repeats in the step gets `.<n>` on its second and later
    keys, so no event is dropped as a retry and the first keeps the key it always had."""
    seen: dict[str, int] = {}
    out = []
    for t, d in events:
        n = seen[t] = seen.get(t, -1) + 1
        key = event_key(call.node_id, call.attempt, t, call.step) + (f".{n}" if n else "")
        out.append((key, t, call.node_id, d))
    return out


def _commit(call, events: list[Event], write: Callable[[Any], None] | None = None) -> None:
    """Record `events` for the call's node and run `write(conn)` in the same transaction."""
    with db.connect() as conn:
        # First: it takes the run's row lock, so this commit and the seal cannot interleave.
        record_events(conn, call.run_id, _keyed(call, events))
        if write is not None:
            write(conn)
        conn.commit()


# --- snapshot access and safe errors ------------------------------------------------------------------


def _fatal(kind: str, message: str) -> ApplicationError:
    """A non-retryable failure; its message goes into the receipt, so it gets the same sanitizer as tool
    errors (no URLs, one line, bounded)."""
    return ApplicationError(safe_message(message, MAX_ERROR_CHARS), type=kind, non_retryable=True)


def run_budget_minor(snapshot: dict) -> int:
    """The run's budget in minor units, for its AI spend and agent fees: the budget asked for at start, capped
    by the contract maximum. 0 means no limit (neither is set)."""
    maximum = int((gateway.contract_of(snapshot).get("budget") or {}).get("maximum_minor") or 0)
    requested = int(snapshot.get("budget_minor") or 0)
    limits = [b for b in (maximum, requested) if b > 0]
    return min(limits) if limits else 0


def policy_verdict(decision_verdict: str) -> str:
    """The policy verdict behind a rules decision: go ahead, needs a person, or stop."""
    if decision_verdict == "APPROVED":
        return gateway.PERMIT
    if decision_verdict in REVIEW_VERDICTS:
        return gateway.REQUIRE_APPROVAL
    return gateway.DENY  # BLOCKED, REJECTED, ERROR, TIMED_OUT and anything unknown fail closed


def _compact(data: dict) -> dict:
    return {k: v for k, v in data.items() if v is not None}


@contextmanager
def _config_errors() -> Iterator[None]:
    """Definition problems are not fixed by retrying: fail the activity for good with a readable reason."""
    try:
        yield
    except cel.CelError as exc:
        raise _fatal("CelError", str(exc)) from exc
    except (LookupError, ValueError, TypeError) as exc:
        raise _fatal("ConfigError", f"{type(exc).__name__}: {exc}") from exc


def _graph(snapshot: dict) -> dict:
    workflows = snapshot["defs"]["workflow"]
    if len(workflows) != 1:
        raise LookupError("snapshot must pin exactly one workflow")
    return next(iter(workflows.values()))["body"]


def _node(snapshot: dict, node_id: str) -> dict:
    node = next((n for n in _graph(snapshot)["nodes"] if n["id"] == node_id), None)
    if node is None:
        raise LookupError(f"workflow has no node {node_id!r}")
    return node


def _body(snapshot: dict, kind: str, key: str) -> dict:
    found = ((snapshot.get("defs") or {}).get(kind) or {}).get(key)
    if found is None:
        raise LookupError(f"snapshot does not pin {kind}/{key}")
    return found["body"]


def _version(snapshot: dict, kind: str, key: str) -> int | None:
    pinned = snapshot.get("versions") or []
    return next((v["version"] for v in pinned if v["kind"] == kind and v["key"] == key), None)


def _success_route(node: dict) -> str:
    return "ok" if "ok" in (node.get("routes") or {}) else "next"


def _schema_errors(schema: dict, value: Any) -> list[str]:
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.absolute_path))
    out = []
    for e in errors[:MAX_REPORTED_ERRORS]:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"{where}: {safe_message(e.message)}")
    return out


def _summary(output: Any) -> str | None:
    if not isinstance(output, dict):
        return None
    if isinstance(output.get("summary"), str):
        return output["summary"]
    totals = output.get("totals")
    if isinstance(totals, dict):
        parts = [
            f"{v} {k.removesuffix('_count').replace('_', ' ')}"
            for k, v in totals.items()
            if k.endswith("_count") and isinstance(v, int)
        ]
        if parts:
            return "Result: " + ", ".join(parts) + "."
    return None


def _tool_event(snapshot: dict, ref: str, call_id: str, decision, result: ToolResult | None) -> dict:
    found = gateway.find_tool(snapshot, ref)
    connector_key, _, tool_id = ref.partition(".")
    connector, tool = (found[1], found[2]) if found else ({}, {})
    data = {
        "id": call_id,
        "tool_ref": ref,
        "app": connector.get("app", connector_key),
        "action": action_name(tool, tool_id),
        "capability": tool.get("capability", ""),
        "action_class": tool.get("action_class", ""),
        "policy": {"verdict": decision.verdict, "reason_codes": decision.reason_codes, "ref": decision.ref},
        "ok": bool(result and result.ok),
        "mocked": bool(result and result.mocked),
    }
    if result is not None and result.error:
        data["error"] = safe_message(result.error)
    return data


def _records_summary(data: Any) -> str | None:
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if lists:
            return f"Returned {len(lists[0])} records."
    return None


# --- node executors (run_node) ------------------------------------------------------------------------


@dataclass
class Step:
    output: Any
    route: str | None
    events: list[Event]
    write: Callable[[Any], None] | None = None


def _trigger(call: NodeCall, node: dict) -> Step:
    contract = gateway.contract_of(call.snapshot)
    schema_key = contract.get("input_schema_ref")
    if schema_key:
        errors = _schema_errors(_body(call.snapshot, "schema", schema_key), call.state.get("input"))
        if errors:
            raise _fatal("InputInvalid", "; ".join(errors))
    route = _success_route(node)
    return Step(call.state.get("input"), route, [("node.completed", {"route": route})])


def _org_of(call: NodeCall) -> str | None:
    """The org the run works for (pinned in its snapshot): its memory items belong to that org."""
    return call.snapshot.get("org_id") or None


def _memory(call: NodeCall, node: dict) -> Step:
    cfg = node.get("config") or {}
    space, route = cfg["space"], _success_route(node)
    if cfg.get("op", "recall") == "recall":
        query = str(cel.resolve(cfg.get("query", ""), call.state) or "")
        with db.connect() as conn:
            items = memory.recall(conn, space, query, int(cfg.get("limit", 8)), org_id=_org_of(call))
        output = [{"id": i["id"], "text": i["text"]} for i in items]
        summary = f"Recalled {len(output)} items from {space}."
        return Step(output, route, [("node.completed", {"route": route, "summary": summary})])
    if cfg["op"] != "remember":
        raise ValueError(f"unknown memory op {cfg['op']!r}")
    text = str(cel.resolve(cfg["text"], call.state))
    source = f"run:{call.run_id}:{call.node_id}:{call.attempt}"  # also the idempotency key for retries

    def write(conn) -> None:
        if not conn.execute("SELECT 1 FROM memory_items WHERE source = %s", (source,)).fetchone():
            memory.remember(conn, space, text, source, cfg.get("actor", "workflow"), org_id=_org_of(call))

    summary = f"Remembered one item in {space}."
    return Step({"text": text}, route, [("node.completed", {"route": route, "summary": summary})], write)


@dataclass(frozen=True)
class RecordedCall:
    """What a tool call finds before it reaches the gateway, in one query."""

    sealed: bool = False  # the run's receipt is sealed
    entry: dict | None = None  # the step's tool.call entry, when the call already committed
    kept: Any = None  # the call's kept result in tool_results
    has_kept: bool = False  # a tool_results row exists (tells a kept JSON null from no row)


def _recorded_tool_call(run_id: str, key: str, call_id: str) -> RecordedCall:
    """Whether the run is sealed, and the tool.call entry with this event key and id plus its kept result
    when the call already committed."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM receipt_entries WHERE run_id = %s AND type = %s) AS sealed, "
            "e.data, r.result, r.event_key IS NOT NULL AS has_kept FROM (SELECT 1) AS one "
            "LEFT JOIN receipt_entries e ON e.run_id = %s AND e.event_key = %s AND e.type = 'tool.call' "
            "AND e.data->>'id' = %s "
            "LEFT JOIN tool_results r ON r.run_id = e.run_id AND r.event_key = e.event_key",
            (run_id, SEALED, run_id, key, call_id),
        ).fetchone()
    return RecordedCall(row["sealed"], row["data"], row["result"], row["has_kept"])


def _keep_result(run_id: str, key: str, result: Any) -> Callable[[Any], None]:
    """A `write(conn)` that keeps a permitted side-effecting call's result in `tool_results`, so it lands in
    the same transaction as the call's tool.call entry: both exist or neither does. The table exists only for
    retry idempotency (the sealed receipt never holds connector data) and its rows are deleted when the run's
    receipt is sealed (`record_events`). No API reads it."""

    def write(conn) -> None:
        conn.execute(
            "INSERT INTO tool_results (run_id, event_key, result) SELECT %s, %s, %s "
            "WHERE NOT EXISTS (SELECT 1 FROM receipt_entries WHERE run_id = %s AND type = %s) "
            "ON CONFLICT (run_id, event_key) DO NOTHING",
            (run_id, key, Jsonb(result), run_id, SEALED),
        )

    return write


READ = "read"  # the action class of a call with no side effects


def _keeps_result(entry: dict) -> bool:
    """Only a call with side effects keeps its result for a retry; a retried read reads again. A call whose
    action class is unknown is kept, since it may have side effects."""
    return entry.get("action_class") != READ


READ_AGAIN = "ReadAgain"  # error type: a recorded read could not be read again


def _read_again(call, ref: str, args: dict, approved: bool) -> Any:
    """The data of a read whose tool.call entry is already recorded. The receipt keeps its first entry, so
    nothing is recorded that contradicts it. A read the policy no longer permits (a revoked grant, a disabled
    connector) or whose app was reconnected another way since the run started (RouteChanged: never sandbox
    data in place of real data, the reverse, or another account's data) fails for good; any other failure
    raises a retryable error and Temporal tries again."""
    decision, result = gateway.call_tool(
        snapshot=call.snapshot, tool_ref=ref, args=args, approved=approved, mode=settings.connector_mode()
    )
    if decision.verdict != gateway.PERMIT:
        codes = ", ".join(decision.reason_codes)
        raise _fatal(READ_AGAIN, f"the repeated read of {ref} is not permitted any more: {codes}")
    if result is None:
        raise ApplicationError(f"the repeated read of {ref} did not run", type=READ_AGAIN)
    if drivers.is_route_changed(result):
        raise _fatal(drivers.ROUTE_CHANGED, str(result.error))
    if not result.ok:
        raise ApplicationError(
            f"the repeated read of {ref} did not succeed: {safe_message(result.error)}", type=READ_AGAIN
        )
    return result.data


@dataclass
class ToolOutcome:
    event: Event  # the tool.call receipt entry
    failed: Event | None  # node.failed when the call was denied or failed
    data: Any  # the connector's data (None unless the call was permitted and succeeded)
    write: Callable[[Any], None] | None = None  # keeps `data` in tool_results; commit it with `event`


def _tool_outcome(entry: dict, data: Any) -> ToolOutcome:
    policy = entry["policy"]
    if policy["verdict"] != gateway.PERMIT:
        error = ", ".join(policy["reason_codes"])
        failed = {"status": "BLOCKED", "route": "denied", "error": error}
        return ToolOutcome(("tool.call", entry), ("node.failed", failed), None)
    if not entry["ok"]:
        failed = {"route": "error", "error": entry.get("error", "the tool call failed")}
        return ToolOutcome(("tool.call", entry), ("node.failed", failed), None)
    return ToolOutcome(("tool.call", entry), None, data)


def _tool_result_block(call_id: str, entry: dict, data: Any) -> dict:
    """The model's tool_result block for a tool.call entry and the call's data."""
    policy = entry["policy"]
    permitted = policy["verdict"] == gateway.PERMIT
    if not permitted:
        content = "Not permitted: " + ", ".join(policy["reason_codes"])
    elif not entry["ok"]:
        content = f"Error: {entry.get('error', 'the tool call failed')}"
    else:
        content = json.dumps(data, ensure_ascii=False)
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": content,
        "is_error": not (permitted and entry["ok"]),
    }


def _recorded_outcome(call, prior: RecordedCall, ref: str, args: dict, approved: bool) -> ToolOutcome:
    """The outcome of a call whose tool.call entry already committed, rebuilt without calling the connector
    again. Only a permitted, successful read reads again, since reads keep no result."""
    entry = prior.entry
    if prior.has_kept or entry["policy"]["verdict"] != gateway.PERMIT or not entry["ok"]:
        return _tool_outcome(entry, prior.kept)
    if prior.sealed:  # its kept result went with the seal; nothing may run any more
        raise _sealed(call.run_id)
    if entry.get("action_class") == READ:
        return _tool_outcome(entry, _read_again(call, ref, args, approved))
    raise _fatal(RESULT_LOST, f"the result of tool call {entry['id']} was not kept; it will not be repeated")


def _tool_call(
    call: NodeCall | ItemCall | ToolUse, ref: str, args: dict, call_id: str, approved: bool
) -> ToolOutcome:
    """One gateway call. `approved` is the node's approval (`state.approvals[node_id]`), which covers it.

    At most once per step: when an activity is retried after its commit landed (its result was lost), the
    tool.call entry is already recorded under this step's key, so the outcome is rebuilt from it and from the
    result kept in `tool_results`, and the connector is not called again (a live retry would otherwise repeat
    a real side effect). Only side-effecting calls keep their result in `tool_results`; a retried read reads
    again (`_read_again`). A sealed run calls no connector: the call is refused with RunSealed before the
    gateway (the commit would refuse its entry anyway, but only after the call had run). This is best-effort
    against sealers outside the workflow (the API seals a run whose start failed): a seal that lands between
    this check and the gateway call cannot stop the call. The caller commits `write` with the events."""
    key = event_key(call.node_id, call.attempt, "tool.call", call.step)  # its key in _keyed: first tool.call
    prior = _recorded_tool_call(call.run_id, key, call_id)
    if prior.entry is not None:
        return _recorded_outcome(call, prior, ref, args, approved)
    if prior.sealed:
        raise _sealed(call.run_id)
    decision, result = gateway.call_tool(
        snapshot=call.snapshot, tool_ref=ref, args=args, approved=approved, mode=settings.connector_mode()
    )
    data = result.data if result is not None else None
    outcome = _tool_outcome(_tool_event(call.snapshot, ref, call_id, decision, result), data)
    if outcome.failed is not None or not _keeps_result(outcome.event[1]):
        return outcome
    return replace(outcome, write=_keep_result(call.run_id, key, outcome.data))


def _approved(state: dict, node_id: str) -> bool:
    return bool((state.get("approvals") or {}).get(node_id))


def _connector(call: NodeCall, node: dict) -> Step:
    """A connector node without `for_each`: one call. (With `for_each` the workflow runs plan_for_each,
    one for_each_call per item and finish_for_each instead.)"""
    cfg = node.get("config") or {}
    if "for_each" in cfg:
        raise ValueError("a for_each connector node runs one activity per item, not run_node")
    args = cel.resolve(cfg.get("args") or {}, call.state)
    call_id = f"tc_{call.node_id}_{call.attempt}"
    outcome = _tool_call(call, cfg["tool"], args, call_id, _approved(call.state, call.node_id))
    if outcome.failed is not None:
        return Step(None, outcome.failed[1]["route"], [outcome.event, outcome.failed])
    route = _success_route(node)
    done = {"route": route, "summary": _records_summary(outcome.data)}
    return Step(outcome.data, route, [outcome.event, ("node.completed", _compact(done))], outcome.write)


def _for_each_args(call: NodeCall, node: dict) -> list[dict] | str:
    """Every item's resolved `config.args` (with `item` bound to it), or why `config.for_each` is unusable.
    A CEL error in any item raises before any call is made."""
    cfg = node["config"]
    items = cel.resolve(cfg["for_each"], call.state)
    if not isinstance(items, list) or len(items) > MAX_FOR_EACH_ITEMS:
        found = f"{len(items)} items" if isinstance(items, list) else "a value that is not a list"
        return f"for_each must give a list of at most {MAX_FOR_EACH_ITEMS} items, not {found}"
    return [cel.resolve(cfg.get("args") or {}, {**call.state, "item": item}) for item in items]


def _decision(call: NodeCall, node: dict) -> Step:
    key = (node.get("config") or {})["rules"]
    rules = _body(call.snapshot, "decision_rules", key)
    outcome = decisions.evaluate_rules(rules, call.state)
    rules_ref = f"{key}@v{_version(call.snapshot, 'decision_rules', key) or 1}"
    # The rules evaluation is itself the policy decision behind the routing.
    policy = {
        "id": f"poldec_{call.run_id}_{call.node_id}_{call.attempt}",
        "ref": rules_ref,
        "verdict": policy_verdict(outcome.verdict),
        "reason_codes": [outcome.reason_code],
        "actor": "rules",
    }
    output = asdict(outcome)
    decided = {**output, "question": rules.get("question"), "rules_ref": rules_ref, "policy": policy}
    done = {"route": outcome.route, "summary": f"{outcome.verdict}: {outcome.reason_code}"}
    return Step(output, outcome.route, [("decision", decided), ("node.completed", done)])


def _verification(call: NodeCall, node: dict) -> Step:
    cfg = node.get("config") or {}
    value = cel.resolve(cfg.get("value"), call.state)
    errors = _schema_errors(_body(call.snapshot, "schema", cfg["schema"]), value) if cfg.get("schema") else []
    for check in cfg.get("checks") or []:
        if cel.evaluate(check, call.state) is not True:
            errors.append(f"check failed: {check}")
    route = "fail" if errors else "pass"
    summary = "The result passed every check." if not errors else f"Failed: {errors[0]}"
    output = {"passed": not errors, "errors": errors}
    return Step(output, route, [("node.completed", {"route": route, "summary": summary})])


def _any_mocked(run_id: str) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM receipt_entries WHERE run_id = %s AND type = 'tool.call' "
            "AND (data->>'mocked')::boolean LIMIT 1",
            (run_id,),
        ).fetchone()
    return row is not None


def _end(call: NodeCall, node: dict) -> Step:
    cfg = node.get("config") or {}
    status = cfg.get("status", "COMPLETED")
    if status != "COMPLETED":
        reason = call.reason or f"The run ended at {call.node_id}."
        events: list[Event] = [("node.completed", {}), ("run.failed", {"reason": reason})]
        return Step({"status": "FAILED", "reason": reason}, None, events)
    deliverable = cel.resolve(cfg["deliverable"], call.state) if cfg.get("deliverable") else None
    done: dict = {"mocked": _any_mocked(call.run_id)}
    if deliverable is not None:
        done["deliverable"] = deliverable
    events = [("node.completed", {}), ("run.completed", done)]
    return Step({"status": status, "deliverable": deliverable}, None, events)


_EXECUTORS: dict[str, Callable[[NodeCall, dict], Step]] = {
    "trigger": _trigger,
    "memory": _memory,
    "connector": _connector,
    "decision": _decision,
    "verification": _verification,
    "end": _end,
}


# --- human tasks and approvals ------------------------------------------------------------------------


def _task_payload(call: NodeCall, node: dict, kind: str) -> dict:
    cfg = node.get("config") or {}
    timeout_s = int(cfg.get("timeout_s") or DEFAULT_TASK_TIMEOUT_S)
    payload = {
        "title": str(cel.resolve(cfg.get("title") or call.node_id, call.state)),
        "node_type": node["type"],
        "timeout_s": timeout_s,
        "expires_at": (datetime.now(UTC) + timedelta(seconds=timeout_s)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if kind == "human":
        payload["instructions"] = cel.resolve(cfg.get("instructions", ""), call.state)
        payload["show"] = cel.resolve(cfg.get("show"), call.state)
        return payload
    target = (node.get("routes") or {}).get("granted")
    payload["summary"] = cel.resolve(cfg.get("summary", ""), call.state)
    payload["target_node"] = target
    target_cfg = (_node(call.snapshot, target).get("config") or {}) if target else {}
    if target_cfg.get("tool"):
        tool_ref = target_cfg["tool"]
        payload["tool_ref"] = tool_ref
        # The inbox labels the step "Simulated" only when its call would use sandbox data.
        payload["mocked"] = gateway.runs_simulated(call.snapshot, tool_ref, settings.connector_mode())
        payload["count"] = _write_count(call, target_cfg)
    # The grant also lets these writes through, so the approver sees every one of them.
    payload["unlocked"] = [
        {
            "node": node_id,
            "tool_ref": tool_ref,
            "mocked": gateway.runs_simulated(call.snapshot, tool_ref, settings.connector_mode()),
            "count": _write_count(call, _node(call.snapshot, node_id).get("config") or {}),
        }
        for node_id, tool_ref in _also_unlocked_tools(call, node)
    ]
    authorization = gateway.contract_of(call.snapshot).get("authorization") or {}
    payload["policy_ref"] = authorization.get("policy_ref") or gateway.DEFAULT_POLICY_REF
    return payload


def _write_count(call: NodeCall, cfg: dict) -> int | None:
    """How many calls a write step will make once approved: its `for_each` list as the run state stands now,
    else one. None when the list cannot be resolved (the step itself then fails)."""
    if "for_each" not in cfg:
        return 1
    try:
        items = cel.resolve(cfg["for_each"], call.state)
    except cel.CelError:
        return None
    return len(items) if isinstance(items, list) else None


def _also_unlocked_tools(call: NodeCall, node: dict) -> list[tuple[str, str]]:
    """(node id, tool ref) of each connector step `config.also_unlocks` names besides the granted target."""
    target = (node.get("routes") or {}).get("granted")
    out = []
    for node_id in (node.get("config") or {}).get("also_unlocks") or []:
        if not isinstance(node_id, str) or node_id == target or any(node_id == seen for seen, _ in out):
            continue
        tool_ref = (_node(call.snapshot, node_id).get("config") or {}).get("tool")
        if isinstance(tool_ref, str) and tool_ref:
            out.append((node_id, tool_ref))
    return out


_REFUSALS = {
    gateway.GRANT_REVOKED: "the {app} connection no longer grants this pack the access the step needs",
    gateway.NOT_CONNECTED: "{app} is not connected",
    gateway.ROUTE_CHANGED: "the {app} connection changed during this run",
}


def _refused_approval(call: NodeCall, node: dict) -> tuple[str, str] | None:
    """(reason code, explanation) when the approval at `node` must not be asked because the call it approves
    could not run (`gateway.approval_refusal`); None otherwise."""
    target = (node.get("routes") or {}).get("granted")
    tool_ref = (_node(call.snapshot, target).get("config") or {}).get("tool") if target else None
    # Every write the grant lets through must be able to run, not only the granted target.
    refs = [tool_ref] if tool_ref else []
    refs += [ref for _, ref in _also_unlocked_tools(call, node)]
    code, tool_ref = next(
        ((c, ref) for ref in refs if (c := gateway.approval_refusal(call.snapshot, ref))), (None, None)
    )
    if code is None:
        return None
    found = gateway.find_tool(call.snapshot, tool_ref)
    app = (found[1].get("app") if found else None) or tool_ref.partition(".")[0]
    why = _REFUSALS[code].format(app=app)
    return code, f"The approval was not asked for: {why} ({code})."


def _recorded_opening(call: NodeCall) -> dict[str, dict]:
    """What an earlier attempt of this step's `open_task` committed, by event type: `node.failed` (the
    approval was refused) and `approval` (it was opened). A retry follows the receipt, not a new forecast."""
    keys = [event_key(call.node_id, call.attempt, t, call.step) for t in ("node.failed", "approval")]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT type, data FROM receipt_entries WHERE run_id = %s AND event_key = ANY(%s)",
            (call.run_id, keys),
        ).fetchall()
    return {r["type"]: r["data"] or {} for r in rows}


def _refused(kind: str, explanation: str) -> dict:
    """open_task's result for an approval it did not open: the workflow follows `denied` without waiting."""
    output = {"explanation": explanation}
    return {"task_id": None, "kind": kind, "timeout_s": 0, "route": "denied", "output": output}


def _clean_resolutions(items: list) -> list[dict]:
    keep = ("order_id", "resolution", "note")
    return [{k: str(i[k]) for k in keep if i.get(k) is not None} for i in items or [] if isinstance(i, dict)]


def _task_result(call: TaskDecision) -> dict:
    """What the node outputs and the run_tasks row stores as `result`."""
    if call.kind == "human":
        return {
            "outcome": call.outcome,
            "note": call.note,
            "resolutions": _clean_resolutions(call.resolutions),
        }
    return {"decision": call.outcome, "by": call.by, "note": call.note}


def _settle_task(conn, call: TaskDecision) -> TaskDecision:
    """Store the decision on the run_tasks row and return the decision that counts.

    A timeout only closes a task that is still open: when the API recorded a decision before the timer
    fired, that decision wins. `decided_by` the API recorded is kept either way."""
    row = conn.execute(
        "SELECT status, result, decided_by FROM run_tasks WHERE id = %s FOR UPDATE", (call.task_id,)
    ).fetchone()
    if row is None:
        raise _fatal("ConfigError", f"task {call.task_id} does not exist")
    decided = _OUTCOMES[call.kind] - {"timeout"}
    if call.outcome == "timeout" and row["status"] in decided:
        stored = row["result"] or {}
        return replace(
            call,
            outcome=row["status"],
            note=str(stored.get("note") or ""),
            by=row["decided_by"] or stored.get("by"),
            resolutions=list(stored.get("resolutions") or []),
        )
    by = row["decided_by"] or call.by
    final = replace(call, by=by)
    open_only = "AND status IN ('open', 'pending')" if call.outcome == "timeout" else ""
    # Merged, not replaced: the API's record of the decision carries more than the workflow's (the verdict).
    conn.execute(
        "UPDATE run_tasks SET status = %s, result = COALESCE(result, '{}'::jsonb) || %s, decided_by = %s, "
        f"decided_at = COALESCE(decided_at, now()) WHERE id = %s {open_only}",
        (call.outcome, Jsonb(_task_result(final)), by, call.task_id),
    )
    return final


def pay_minor(payload: dict) -> int:
    """A human task's pay: `pay` in minor units, or a Money object; 0 without one."""
    pay = payload.get("pay")
    if isinstance(pay, dict):
        pay = pay.get("amountMinor", pay.get("amount_minor"))
    try:
        return max(int(pay or 0), 0)
    except TypeError, ValueError:
        return 0


def _shown_decision(conn, call: TaskDecision) -> dict:
    """What the run's timeline shows of a settled decision. An approval: who decided, by name or email when
    they are a member of the run's org, else as recorded. A review: who made it as the buyer may see them (a
    network reviewer stays anonymous, a member shows by name or email), its verdict, and the network
    reviewer's simulated pay, which the run counts as reviewer pay."""
    if call.kind != "human":
        member = conn.execute(
            "SELECT m.name, m.email FROM runs r JOIN org_members m ON m.org_id = r.org_id AND m.user_id = %s "
            "WHERE r.id = %s",
            (call.by, call.run_id),
        ).fetchone()
        return {"decided_by": (member and (member["name"] or member["email"])) or call.by}
    row = conn.execute(
        "SELECT t.payload, t.result, m.name, m.email FROM run_tasks t JOIN runs r ON r.id = t.run_id "
        "LEFT JOIN org_members m ON m.org_id = r.org_id AND m.user_id = %s WHERE t.id = %s",
        (call.by, call.task_id),
    ).fetchone()
    payload, result = (row["payload"] or {}, row["result"] or {}) if row else ({}, {})
    network = payload.get("claimed_via") == "network"
    if call.by is None:
        who = None
    elif network:
        who = NETWORK_REVIEWER
    else:  # the demo workspace's reviewers are not members: they show as recorded
        who = (row and (row["name"] or row["email"])) or call.by
    paid = network and call.outcome != "timeout"
    return {
        "decided_by": who,
        "verdict": result.get("verdict"),
        "cost_minor": pay_minor(payload) if paid else None,
    }


def _task_events(call: TaskDecision, shown: dict) -> list[Event]:
    human = call.kind == "human"
    status = {"status": call.outcome, **shown}
    if human:
        decided = ("human.task", {"task_id": call.task_id, "note": call.note or None, **status})
    else:
        decided = ("approval", {"approval_id": call.task_id, **status})
    if call.outcome in ("resolved", "granted"):
        ended = ("node.completed", {"route": call.outcome, "summary": call.note or None})
    else:
        error = call.note or f"The {'task' if human else 'approval'} ended: {call.outcome}."
        ended = (
            "node.failed",
            {"status": _FAILED_STATUS[call.outcome], "route": call.outcome, "error": error},
        )
    return [(t, _compact(d)) for t, d in (decided, ended)]


# --- activities ---------------------------------------------------------------------------------------


class PackActivities:
    """The activities PackRunner calls. `provider` replaces the model provider of every profile (tests)."""

    def __init__(self, provider: ModelProvider | None = None) -> None:
        self._provider = provider

    def all(self) -> list[Callable]:
        return [
            self.run_node,
            self.plan_for_each,
            self.for_each_call,
            self.finish_for_each,
            self.start_agent,
            self.model_call,
            self.tool_call,
            self.finish_node,
            self.open_task,
            self.close_task,
            self.fail,
        ]

    @activity.defn
    def run_node(self, call: NodeCall) -> dict:
        """trigger, memory, connector, decision, verification and end nodes: one step each."""
        with _config_errors():
            node = _node(call.snapshot, call.node_id)
            executor = _EXECUTORS.get(node["type"])
            if executor is None:
                raise LookupError(f"node type {node['type']!r} is not run by run_node")
            step = executor(call, node)
        _commit(call, [("node.started", {}), *step.events], step.write)
        return {"output": step.output, "route": step.route}

    @activity.defn
    def plan_for_each(self, call: NodeCall) -> dict:
        """Start a for_each connector node: resolve its list and every item's args before any call.
        Returns {"route": None, "items": [args...]}, or {"route": "error"} when the list is unusable."""
        with _config_errors():
            planned = _for_each_args(call, _node(call.snapshot, call.node_id))
        if isinstance(planned, str):
            _commit(call, [("node.started", {}), ("node.failed", {"route": "error", "error": planned})])
            return {"route": "error", "items": None}
        _commit(call, [("node.started", {})])
        return {"route": None, "items": planned}

    @activity.defn
    def for_each_call(self, call: ItemCall) -> dict:
        """One item's tool call, committed on its own so a retry never repeats an earlier item. A denied or
        failed call also fails the node: {"route": "denied" | "error"}; otherwise {"route": None, "data"}."""
        with _config_errors():
            ref = (_node(call.snapshot, call.node_id).get("config") or {})["tool"]
        call_id = f"tc_{call.node_id}_{call.attempt}_{call.index}"
        outcome = _tool_call(call, ref, call.args, call_id, call.approved)
        failed = outcome.failed
        _commit(call, [outcome.event] if failed is None else [outcome.event, failed], outcome.write)
        return {"route": failed[1]["route"] if failed else None, "data": outcome.data}

    @activity.defn
    def finish_for_each(self, call: AgentResult) -> dict:
        """Complete a for_each connector node whose items all succeeded: output {"results": [...]}."""
        with _config_errors():
            node = _node(call.snapshot, call.node_id)
        route = _success_route(node)
        done = {"route": route, "summary": f"Made {len(call.result)} calls, one per item."}
        _commit(call, [("node.completed", done)])
        return {"output": {"results": call.result}, "route": route}

    @activity.defn
    def start_agent(self, call: NodeCall) -> dict:
        with _config_errors():
            cfg = _node(call.snapshot, call.node_id).get("config") or {}
            agent_def = call.snapshot["defs"]["agent"][cfg["agent"]]
            body = agent_def["body"]
            runtime = body.get("runtime") or {}
            schema_key = cfg.get("output_schema") or body["output_schema_ref"]
            output_schema = _body(call.snapshot, "schema", schema_key)
            inputs = cel.resolve(cfg.get("inputs") or {}, call.state)
            profile = runtime.get("model_profile", "reasoning")
            models_def = _body(call.snapshot, "models", MODELS_KEY)
            _, model = providers.provider_for(profile, models_def, settings.model_env())
            spec = {
                "system": agent.build_system(agent_def),
                "messages": [
                    {"role": "user", "content": agent.build_user_message(cfg.get("task", ""), inputs)}
                ],
                "tools": [asdict(t) for t in agent.agent_tools(body, call.snapshot, output_schema)],
                "profile": profile,
                "model": model,
                "max_turns": int(runtime.get("max_turns", 6)),
                "adapter": runtime.get("adapter", "hosted"),
                "agent_id": body["agent_id"],
            }
        # A listed agent of another workspace owes its per-call fee: one line per step attempt, written with
        # node.started so a retry adds nothing (sub-project D). A fee that would go over the monthly cap or
        # the run's budget is refused before the step starts: nothing is written and the run stops.
        key = event_key(call.node_id, call.attempt, "fee", call.step)
        budget = run_budget_minor(call.snapshot)
        fee = fees.agent_fee_writer(call.snapshot, call.run_id, cfg["agent"], key, budget)
        try:
            _commit(call, [("node.started", {})], fee)
        except fees.OverCap as exc:
            raise _fatal(exc.code, exc.message) from None
        charged = fees.agent_fee(call.snapshot, cfg["agent"])
        return {**spec, "fee_minor": int(charged["unit_minor"]) if charged else 0}

    @activity.defn
    def model_call(self, call: ModelCall) -> dict:
        with _config_errors():
            models_def = _body(call.snapshot, "models", MODELS_KEY)
            provider, model = providers.provider_for(call.profile, models_def, settings.model_env())
        with tracing.generation(call, model) as traced:
            turn = (self._provider or provider).call(
                model=model,
                system=call.system,
                messages=call.messages,
                tools=[ToolSpec(**t) for t in call.tools],
                max_tokens=MAX_TOKENS,
            )
            cost = providers.cost_minor(models_def, call.profile, turn.input_tokens, turn.output_tokens)
            traced.record(turn, cost)
        usage = {"input_tokens": turn.input_tokens, "output_tokens": turn.output_tokens, "cost_minor": cost}
        _commit(call, [("model.usage", usage)])
        return {"content": turn.content, "stop_reason": turn.stop_reason, "cost_minor": cost}

    @activity.defn
    def tool_call(self, call: ToolUse) -> dict:
        """One agent tool call through the gateway (never pre-approved). Returns a tool_result block.
        At most once per step, like a connector node (`_tool_call`): a retry after the commit landed
        rebuilds the block from the recorded entry and the kept result, and does not call the connector
        again."""
        name = str(call.block.get("name", ""))
        ref = agent.tool_ref(name)
        call_id = str(call.block.get("id") or "")
        if name not in call.offered or name == providers.SUBMIT_TOOL:
            policy_ref = (gateway.contract_of(call.snapshot).get("authorization") or {}).get("policy_ref")
            decision = gateway.PolicyDecision(
                verdict=gateway.DENY,
                reason_codes=["TOOL_NOT_OFFERED"],
                ref=policy_ref or gateway.DEFAULT_POLICY_REF,
            )
            entry = _tool_event(call.snapshot, ref, call_id, decision, None)
            _commit(call, [("tool.call", entry)])
            return _tool_result_block(call_id, entry, None)
        outcome = _tool_call(call, ref, call.block.get("input") or {}, call_id, approved=False)
        _commit(call, [outcome.event], outcome.write)
        return _tool_result_block(call_id, outcome.event[1], outcome.data)

    @activity.defn
    def finish_node(self, call: AgentResult) -> dict:
        """Validate the submitted result against the node's output schema; invalid output fails for good."""
        with _config_errors():
            node = _node(call.snapshot, call.node_id)
            cfg = node.get("config") or {}
            agent_body = _body(call.snapshot, "agent", cfg["agent"])
            schema = _body(
                call.snapshot, "schema", cfg.get("output_schema") or agent_body["output_schema_ref"]
            )
        errors = _schema_errors(schema, call.result)
        if errors:
            raise _fatal("OutputInvalid", "the result does not match the output schema: " + "; ".join(errors))
        route = _success_route(node)
        done = {"route": route, "summary": _summary(call.result)}
        _commit(call, [("node.completed", _compact(done))])
        return {"output": call.result, "route": route}

    @activity.defn
    def open_task(self, call: NodeCall) -> dict:
        """Create the human task or approval row and mark the node as waiting. An approval for a call that
        could not run (its app not connected, reconnected another way, or no longer granting the pack the
        access) is not opened: the node fails on its `denied` route at once, with the reason code, and the
        result carries `route` and `output` for the workflow to follow without waiting. A retry keeps what
        the receipt already holds for this step, whatever the connection says now."""
        with _config_errors():
            node = _node(call.snapshot, call.node_id)
            kind = "human" if node["type"] == "human_workforce" else "approval"
        recorded = _recorded_opening(call) if kind == "approval" else {}
        if "node.failed" in recorded:
            return _refused(kind, str(recorded["node.failed"].get("error") or ""))
        with _config_errors():
            refused = _refused_approval(call, node) if kind == "approval" and not recorded else None
            payload = _task_payload(call, node, kind) if refused is None else {}
        if refused is not None:
            code, explanation = refused
            failed = {"status": "BLOCKED", "route": "denied", "error": explanation, "reason_codes": [code]}
            _commit(call, [("node.started", {}), ("node.failed", failed)])
            return _refused(kind, explanation)
        task_id = f"{'ht' if kind == 'human' else 'apr'}_{call.run_id}_{call.node_id}_{call.attempt}"
        status = "open" if kind == "human" else "pending"
        if kind == "human":
            opened = ("human.task", {"task_id": task_id, "status": status, "title": payload["title"]})
        else:
            summary = payload.get("summary") or None
            data = {"approval_id": task_id, "status": status, "title": payload["title"], "summary": summary}
            opened = ("approval", _compact(data))

        def write(conn) -> None:
            conn.execute(
                "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (task_id, call.run_id, call.node_id, kind, status, Jsonb(payload)),
            )

        waiting = ("node.waiting", {"note": payload["title"]})
        _commit(call, [("node.started", {}), waiting, opened], write)
        return {"task_id": task_id, "kind": kind, "timeout_s": payload["timeout_s"]}

    @activity.defn
    def close_task(self, call: TaskDecision) -> dict:
        """Record the person's decision (or the timeout) and route the node by it."""
        if call.outcome not in _OUTCOMES[call.kind]:
            raise _fatal("ConfigError", f"{call.outcome!r} is not a {call.kind} outcome")
        with db.connect() as conn:
            final = _settle_task(conn, call)
            record_events(conn, call.run_id, _keyed(call, _task_events(final, _shown_decision(conn, final))))
            conn.commit()
        return {"output": _task_result(final), "route": final.outcome}

    @activity.defn
    def fail(self, call: Failure) -> None:
        """A node failed outside its own executor (activity error, guard, budget); optionally end the run."""
        events: list[Event] = []
        if call.node_failed and call.node_id:
            data = {"error": call.reason, **({"route": call.route} if call.route else {})}
            events.append(("node.failed", data))
        if call.end_run:
            events.append(("run.failed", {"reason": call.reason}))
        _commit(call, events)
