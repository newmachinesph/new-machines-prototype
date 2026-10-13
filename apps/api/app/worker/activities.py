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

from app import db, settings
from app.runtime import agent, cel, decisions, gateway, memory, projection, providers, receipt
from app.runtime.drivers import ToolResult, safe_message
from app.runtime.providers import ModelProvider, ToolSpec

MAX_TOKENS = 8000
DEFAULT_TASK_TIMEOUT_S = 86400
MODELS_KEY = "default"
MAX_REPORTED_ERRORS = 5
MAX_ERROR_CHARS = 300
SAFE_ERROR_TYPES = {"ConfigError", "CelError", "InputInvalid", "OutputInvalid"}  # messages written here
_OUTCOMES = {"human": {"resolved", "rejected", "timeout"}, "approval": {"granted", "denied", "timeout"}}
REVIEW_VERDICTS = {"HUMAN_REVIEW", "ESCALATED", "REVISION_REQUIRED"}
_FAILED_STATUS = {"rejected": "REJECTED", "denied": "REJECTED", "timeout": "TIMED_OUT"}

SEALED = "receipt.sealed"
RUN_SEALED = "RunSealed"  # error type: the run's receipt is sealed, so nothing more may happen in it
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
        raise _fatal(RUN_SEALED, f"run {run_id} is already finished; its receipt is sealed")


def record_events(conn, run_id: str, events: list[tuple[str, str, str | None, dict]]) -> int:
    """Append (event_key, type, node_id, data) entries and fold them into the projection. Does not commit.

    A run's final event (run.completed / run.failed) is followed by a `receipt.sealed` entry, so every
    finished run's receipt ends with its seal. Returns how many entries were new (0 on a retry)."""
    row = conn.execute(
        "SELECT projection, snapshot->'versions' AS versions FROM runs WHERE id = %s FOR UPDATE", (run_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"run {run_id} does not exist")
    _refuse_after_seal(conn, run_id, [key for key, *_ in events])
    current, added, seal = row["projection"], 0, None
    for key, type_, node_id, data in events:
        entry = receipt.append(conn, run_id, key, type_, node_id, data)
        if entry is not None:
            current = projection.apply_event(current, entry)
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
    if added:
        projection.save(conn, run_id, current, current["status"])
    return added


def record(run_id: str, event_key: str, type: str, node_id: str | None, data: dict) -> None:
    """Record one event in its own transaction."""
    with db.connect() as conn:
        record_events(conn, run_id, [(event_key, type, node_id, data)])
        conn.commit()


def _keyed(call, events: list[Event]) -> list[tuple[str, str, str | None, dict]]:
    return [(event_key(call.node_id, call.attempt, t, call.step), t, call.node_id, d) for t, d in events]


def _commit(call, events: list[Event], write: Callable[[Any], None] | None = None) -> None:
    """Record `events` for the call's node and run `write(conn)` in the same transaction."""
    with db.connect() as conn:
        if write is not None:
            write(conn)
        record_events(conn, call.run_id, _keyed(call, events))
        conn.commit()


# --- snapshot access and safe errors ------------------------------------------------------------------


def _fatal(kind: str, message: str) -> ApplicationError:
    """A non-retryable failure; its message goes into the receipt, so it gets the same sanitizer as tool
    errors (no URLs, one line, bounded)."""
    return ApplicationError(safe_message(message, MAX_ERROR_CHARS), type=kind, non_retryable=True)


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
        "action": tool_id.replace("_", " "),
        "capability": tool.get("capability", ""),
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


def _memory(call: NodeCall, node: dict) -> Step:
    cfg = node.get("config") or {}
    space, route = cfg["space"], _success_route(node)
    if cfg.get("op", "recall") == "recall":
        query = str(cel.resolve(cfg.get("query", ""), call.state) or "")
        with db.connect() as conn:
            items = memory.recall(conn, space, query, int(cfg.get("limit", 8)))
        output = [{"id": i["id"], "text": i["text"]} for i in items]
        summary = f"Recalled {len(output)} items from {space}."
        return Step(output, route, [("node.completed", {"route": route, "summary": summary})])
    if cfg["op"] != "remember":
        raise ValueError(f"unknown memory op {cfg['op']!r}")
    text = str(cel.resolve(cfg["text"], call.state))
    source = f"run:{call.run_id}:{call.node_id}:{call.attempt}"  # also the idempotency key for retries

    def write(conn) -> None:
        if not conn.execute("SELECT 1 FROM memory_items WHERE source = %s", (source,)).fetchone():
            memory.remember(conn, space, text, source, cfg.get("actor", "workflow"))

    summary = f"Remembered one item in {space}."
    return Step({"text": text}, route, [("node.completed", {"route": route, "summary": summary})], write)


def _connector(call: NodeCall, node: dict) -> Step:
    cfg = node.get("config") or {}
    ref = cfg["tool"]
    args = cel.resolve(cfg.get("args") or {}, call.state)
    approved = bool((call.state.get("approvals") or {}).get(call.node_id))
    decision, result = gateway.call_tool(
        snapshot=call.snapshot, tool_ref=ref, args=args, approved=approved, mode=settings.connector_mode()
    )
    data = _tool_event(call.snapshot, ref, f"tc_{call.node_id}_{call.attempt}", decision, result)
    events: list[Event] = [("tool.call", data)]
    if decision.verdict != gateway.PERMIT:
        error = ", ".join(decision.reason_codes)
        failed = {"status": "BLOCKED", "route": "denied", "error": error}
        return Step(None, "denied", [*events, ("node.failed", failed)])
    if result is None or not result.ok:
        failed = {"route": "error", "error": data.get("error", "the tool call failed")}
        return Step(None, "error", [*events, ("node.failed", failed)])
    route = _success_route(node)
    done = {"route": route, "summary": _records_summary(result.data)}
    return Step(result.data, route, [*events, ("node.completed", _compact(done))])


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
    authorization = gateway.contract_of(call.snapshot).get("authorization") or {}
    payload["policy_ref"] = authorization.get("policy_ref") or gateway.DEFAULT_POLICY_REF
    return payload


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
    conn.execute(
        "UPDATE run_tasks SET status = %s, result = %s, decided_by = %s, "
        f"decided_at = COALESCE(decided_at, now()) WHERE id = %s {open_only}",
        (call.outcome, Jsonb(_task_result(final)), by, call.task_id),
    )
    return final


def _task_events(call: TaskDecision) -> list[Event]:
    human = call.kind == "human"
    status = {"status": call.outcome, "decided_by": call.by}
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
            }
        _commit(call, [("node.started", {})])
        return spec

    @activity.defn
    def model_call(self, call: ModelCall) -> dict:
        with _config_errors():
            models_def = _body(call.snapshot, "models", MODELS_KEY)
            provider, model = providers.provider_for(call.profile, models_def, settings.model_env())
        turn = (self._provider or provider).call(
            model=model,
            system=call.system,
            messages=call.messages,
            tools=[ToolSpec(**t) for t in call.tools],
            max_tokens=MAX_TOKENS,
        )
        cost = providers.cost_minor(models_def, call.profile, turn.input_tokens, turn.output_tokens)
        usage = {"input_tokens": turn.input_tokens, "output_tokens": turn.output_tokens, "cost_minor": cost}
        _commit(call, [("model.usage", usage)])
        return {"content": turn.content, "stop_reason": turn.stop_reason, "cost_minor": cost}

    @activity.defn
    def tool_call(self, call: ToolUse) -> dict:
        """One agent tool call through the gateway (never pre-approved). Returns a tool_result block."""
        name = str(call.block.get("name", ""))
        ref = agent.tool_ref(name)
        if name not in call.offered or name == providers.SUBMIT_TOOL:
            policy_ref = (gateway.contract_of(call.snapshot).get("authorization") or {}).get("policy_ref")
            decision = gateway.PolicyDecision(
                verdict=gateway.DENY,
                reason_codes=["TOOL_NOT_OFFERED"],
                ref=policy_ref or gateway.DEFAULT_POLICY_REF,
            )
            result = None
        else:
            decision, result = gateway.call_tool(
                snapshot=call.snapshot,
                tool_ref=ref,
                args=call.block.get("input") or {},
                approved=False,
                mode=settings.connector_mode(),
            )
        data = _tool_event(call.snapshot, ref, str(call.block.get("id", "")), decision, result)
        _commit(call, [("tool.call", data)])
        if result is None:
            content = "Not permitted: " + ", ".join(decision.reason_codes)
        elif not result.ok:
            content = f"Error: {data.get('error', 'the tool call failed')}"
        else:
            content = json.dumps(result.data, ensure_ascii=False)
        ok = bool(result and result.ok)
        return {
            "type": "tool_result",
            "tool_use_id": call.block.get("id"),
            "content": content,
            "is_error": not ok,
        }

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
        """Create the human task or approval row and mark the node as waiting."""
        with _config_errors():
            node = _node(call.snapshot, call.node_id)
            kind = "human" if node["type"] == "human_workforce" else "approval"
            payload = _task_payload(call, node, kind)
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
            record_events(conn, call.run_id, _keyed(call, _task_events(final)))
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
