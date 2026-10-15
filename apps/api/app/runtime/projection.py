"""Run projection: the existing `Run` API model in its camelCase wire form, folded from receipt events.

`apply_event` is pure: it returns a new dict and never changes its input. Events are receipt entries:
{seq, at, type, node_id, data}. Unknown event types leave the projection unchanged.
"""

import copy
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from app.runtime import cel

X_STEP = 210
FAILURE_ROW_Y = 140
CURRENCY = "USD"
# Route labels that lead away from the happy path; nodes reached only through them sit on a lower row.
FAILURE_ROUTES = {"blocked", "rejected", "timeout", "denied", "error", "fail", "failed"}
NODE_ACTORS = {
    "trigger": "buyer",
    "memory": "system",
    "connector": "machine",
    "agent": "machine",
    "decision": "machine",
    "verification": "machine",
    "human_workforce": "human",
    "approval": "buyer",
    "end": "system",
}
NODE_FAILURE_STATUSES = {"FAILED", "REJECTED", "TIMED_OUT", "BLOCKED", "CANCELLED"}
TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
OPEN_ROW_STATUSES = {"open", "unreviewed"}
SIMULATED_LIMITATION = "Simulated: connector data came from sandbox responses, not a live account."
VIEW_ITEMS_MAX = 50  # a pack's deliverable view shows at most this many items
VIEW_DETAIL_MAX = 160  # characters of an item's detail

log = logging.getLogger(__name__)


def _money(amount_minor: int) -> dict:
    return {"amountMinor": amount_minor, "currency": CURRENCY}


def _major(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100}.{abs(minor) % 100:02d}"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- initial layout --------------------------------------------------------------------------------


def _only(snapshot: dict, kind: str) -> tuple[str, dict]:
    items = (snapshot.get("defs") or {}).get(kind) or {}
    if len(items) != 1:
        raise LookupError(f"snapshot must pin exactly one {kind}, found {len(items)}")
    key, value = next(iter(items.items()))
    return key, value["body"]


def _body(snapshot: dict, kind: str, key: str) -> dict:
    return (((snapshot.get("defs") or {}).get(kind) or {}).get(key) or {}).get("body") or {}


def _version_ref(snapshot: dict, kind: str, key: str) -> str:
    version = next(
        (v["version"] for v in snapshot.get("versions") or [] if v["kind"] == kind and v["key"] == key), None
    )
    return f"{key}@{version}" if version is not None else key


def _node_text(node: dict, snapshot: dict) -> tuple[str, str | None, str | None]:
    """(label, subtitle, pinned version ref) for a workflow node."""
    cfg, kind = node.get("config") or {}, node["type"]
    if kind == "connector":
        connector_key, _, tool_id = str(cfg.get("tool", "")).partition(".")
        connector = _body(snapshot, "connector", connector_key)
        tool = next((t for t in connector.get("tools") or [] if t.get("id") == tool_id), {})
        app = connector.get("app", connector_key)
        label = f"{app}: {tool_id.replace('_', ' ')}"
        return (
            label,
            f"{tool.get('action_class', 'tool')} access",
            _version_ref(snapshot, "connector", connector_key),
        )
    if kind == "agent":
        agent = _body(snapshot, "agent", cfg.get("agent", ""))
        profile = (agent.get("runtime") or {}).get("model_profile")
        label = str(cfg.get("agent", "agent")).replace("-", " ").capitalize()
        return (
            label,
            f"{profile} model" if profile else None,
            _version_ref(snapshot, "agent", cfg.get("agent", "")),
        )
    if kind == "decision":
        rules = _body(snapshot, "decision_rules", cfg.get("rules", ""))
        return (
            rules.get("question", "Decide"),
            "Rules",
            _version_ref(snapshot, "decision_rules", cfg.get("rules", "")),
        )
    if cfg.get("title"):
        return cfg["title"], None, None
    labels = {
        "trigger": "Start",
        "memory": "Recall company knowledge" if cfg.get("op") == "recall" else "Remember what was learned",
        "verification": "Verify the result",
        "end": "Done" if cfg.get("status") == "COMPLETED" else "Stopped",
    }
    return labels.get(kind, node["id"]), None, None


def _failure_only_targets(nodes: list[dict]) -> set[str]:
    incoming: dict[str, set[str]] = {}
    for node in nodes:
        for label, target in (node.get("routes") or {}).items():
            incoming.setdefault(target, set()).add(label)
    return {target for target, labels in incoming.items() if labels <= FAILURE_ROUTES}


def describe_input(value: dict) -> str:
    if "since" in value and "until" in value:
        return f"{value['since']} to {value['until']}"
    return ", ".join(f"{k}: {v}" for k, v in value.items())


def initial_projection(run_id: str, snapshot: dict, input: dict, started_by: str, budget_minor: int) -> dict:
    pack_key, pack = _only(snapshot, "pack")
    workflow_key, workflow = _only(snapshot, "workflow")
    contract_key = workflow.get("work_contract_ref") or pack.get("contract", "")
    lower_row = _failure_only_targets(workflow["nodes"])
    nodes, edges = [], []
    for i, node in enumerate(workflow["nodes"]):
        label, subtitle, version = _node_text(node, snapshot)
        entry = {
            "id": node["id"],
            "type": node["type"],
            "label": label,
            "actor": NODE_ACTORS.get(node["type"], "system"),
            "status": "CREATED",
            "x": X_STEP * i,
            "y": FAILURE_ROW_Y if node["id"] in lower_row else 0,
        }
        entry.update({k: v for k, v in (("subtitle", subtitle), ("version", version)) if v})
        nodes.append(entry)
        for route, target in (node.get("routes") or {}).items():
            edge = {"from": node["id"], "to": target, "taken": False}
            if route != "next":
                edge["label"] = route
            edges.append(edge)
    now = _now()
    workflow_ref = _version_ref(snapshot, "workflow", workflow_key)
    contract_ref = _version_ref(snapshot, "contract", contract_key)
    return {
        "id": run_id,
        "packSlug": pack_key,
        "title": pack.get("name", pack_key),
        "status": "RUNNING",
        "startedAt": now,
        "startedBy": started_by,
        "input": describe_input(input),
        "workflowRef": workflow_ref,
        "contractRef": contract_ref,
        "budget": _money(budget_minor),
        "spent": {"ai": _money(0), "human": _money(0), "tools": _money(0)},
        "stages": {
            "executed": "pending",
            "verified": "pending",
            "accepted": "pending",
            "settlement": "pending",
        },
        "summary": "Starting.",
        **({"outcome": str(pack["outcome"])} if pack.get("outcome") else {}),
        "nodes": nodes,
        "edges": edges,
        "timeline": [
            {
                "at": now,
                "actor": "buyer",
                "who": started_by,
                "title": "Started the run",
                "detail": describe_input(input),
                "nodeId": workflow.get("entry_node_id", nodes[0]["id"] if nodes else None),
            },
            {
                "at": now,
                "actor": "system",
                "who": "Workflow engine",
                "title": f"Pinned {workflow_ref} and {contract_ref}",
                "ref": workflow_ref,
            },
        ],
    }


# --- events ----------------------------------------------------------------------------------------


def _node(p: dict, node_id: str | None) -> dict | None:
    return next((n for n in p["nodes"] if n["id"] == node_id), None)


def _say(p: dict, event: dict, actor: str, who: str, title: str, **extra: Any) -> None:
    item = {"at": event["at"], "actor": actor, "who": who, "title": title}
    if event.get("node_id"):
        item["nodeId"] = event["node_id"]
    item.update({k: v for k, v in extra.items() if v is not None})
    p["timeline"].append(item)


def _set_run_status(p: dict, status: str) -> None:
    if p["status"] not in TERMINAL_RUN_STATUSES:
        p["status"] = status


def _take_edge(p: dict, node_id: str, route: str | None) -> None:
    outgoing = [e for e in p["edges"] if e["from"] == node_id]
    for edge in outgoing:
        if edge.get("label") == route or (route in (None, "next") and "label" not in edge):
            edge["taken"] = True
    if route is None and len(outgoing) == 1:
        outgoing[0]["taken"] = True


def _add_money(holder: dict, key: str, amount: int) -> None:
    holder[key] = _money(holder.get(key, _money(0))["amountMinor"] + amount)


def _on_node_started(p: dict, event: dict, data: dict) -> None:
    node = _node(p, event["node_id"])
    if node is None:
        return
    node["status"] = "RUNNING"
    node["attempts"] = node.get("attempts", 0) + 1
    _set_run_status(p, "VERIFYING" if node["type"] == "verification" else "RUNNING")


def _on_node_completed(p: dict, event: dict, data: dict) -> None:
    node = _node(p, event["node_id"])
    if node is None:
        return
    node["status"] = "COMPLETED"
    if data.get("summary"):
        node["output"] = data["summary"]
    if data.get("duration_s") is not None:
        node["durationS"] = int(data["duration_s"])
    _take_edge(p, node["id"], data.get("route"))
    if node["type"] == "verification":
        passed = data.get("route", "pass") == "pass"
        p["stages"]["executed"] = "done"
        p["stages"]["verified"] = "done" if passed else "failed"
    # A review's decision has its own line (`_on_human_task`) with the reviewer's note: no second one.
    if node["type"] not in ("trigger", "end", "human_workforce"):
        _say(p, event, node["actor"], node["label"], data.get("summary") or f"Finished: {node['label']}")


def _on_node_waiting(p: dict, event: dict, data: dict) -> None:
    node = _node(p, event["node_id"])
    if node is None:
        return
    node["status"] = "WAITING"
    if data.get("note"):
        node["note"] = data["note"]
    _set_run_status(p, "WAITING_FOR_HUMAN" if node["type"] == "human_workforce" else "WAITING_FOR_EVENT")


def _on_node_failed(p: dict, event: dict, data: dict) -> None:
    node = _node(p, event["node_id"])
    if node is None:
        return
    status = data.get("status")
    node["status"] = status if status in NODE_FAILURE_STATUSES else "FAILED"
    if data.get("error"):
        node["note"] = data["error"]
    _take_edge(p, node["id"], data.get("route"))
    _say(
        p,
        event,
        node["actor"],
        node["label"],
        f"{node['label']} did not finish",
        detail=data.get("error"),
        tone="blocked",
    )


def _tool_status(verdict: str, ok: bool) -> str:
    if verdict == "DENY":
        return "DENIED"
    if verdict == "REQUIRE_APPROVAL":
        return "PLANNED"
    return "CONFIRMED" if ok else "FAILED"


def _on_tool_call(p: dict, event: dict, data: dict) -> None:
    node = _node(p, event["node_id"])
    if node is None:
        return
    policy = data.get("policy") or {}
    verdict = policy.get("verdict", "DENY")
    ok = bool(data.get("ok"))
    mocked = bool(data.get("mocked"))
    app = data.get("app") or str(data.get("tool_ref", "tool")).partition(".")[0]
    action = data.get("action") or str(data.get("tool_ref", "call")).partition(".")[2].replace("_", " ")
    detail = data.get("detail") or data.get("error") or ", ".join(policy.get("reason_codes") or [])
    call = {
        "id": data.get("id") or f"tool_{event['seq']}",
        "app": app,
        "action": action,
        "capability": data.get("capability", ""),
        "status": _tool_status(verdict, ok),
        "policy": verdict,
        "detail": detail or action,
        "mocked": mocked,
    }
    if data.get("action_class"):
        call["actionClass"] = str(data["action_class"])
    node["toolCalls"] = [*node.get("toolCalls", []), call]
    _add_money(p["spent"], "tools", int(data.get("cost_minor") or 0))
    tone = {"PERMIT": "ok", "REQUIRE_APPROVAL": "warn"}.get(verdict, "blocked")
    words = {"PERMIT": "Permitted", "REQUIRE_APPROVAL": "Needs approval for", "DENY": "Denied"}
    _say(
        p,
        event,
        "policy",
        "Policy engine",
        f"{words.get(verdict, verdict)} {app}: {action}",
        ref=policy.get("ref"),
        tone=tone,
    )
    if verdict == "PERMIT":
        title = f"{action.capitalize()}{' (Simulated)' if mocked else ''}"
        _say(p, event, "machine", app, title, detail=detail or None, tone=None if ok else "blocked")


def _on_decision(p: dict, event: dict, data: dict) -> None:
    node = _node(p, event["node_id"])
    if node is None:
        return
    verdict = data["verdict"]
    raw = data.get("policy") or {}
    # Events use snake_case (`reason_codes`, like tool.call); the projection stores the Run wire form.
    policy = {
        "id": raw.get("id") or f"poldec_{event['node_id']}_{event['seq']}",
        "ref": raw.get("ref") or "policy/default",
        "verdict": raw.get("verdict") or "PERMIT",
        "reasonCodes": list(raw.get("reason_codes") or ["RULES_EVALUATED"]),
        "actor": raw.get("actor") or "Policy engine",
    }
    node["decision"] = {
        "question": data.get("question") or node["label"],
        "evaluator": {"kind": "rules", "label": "Rules", "configVersion": str(data.get("rules_ref") or "1")},
        "chain": [{"kind": "rules", "verdict": verdict, "note": data.get("explanation", "")}],
        "verdict": verdict,
        "reasonCodes": [data["reason_code"]],
        "explanation": data.get("explanation", ""),
        "evidenceRefs": list(data.get("evidence_refs") or []),
        "route": data["route"],
        "evaluatedAt": event["at"],
        "policy": policy,
    }
    tone = (
        "ok"
        if verdict == "APPROVED"
        else "blocked"
        if verdict in ("BLOCKED", "REJECTED", "ERROR")
        else "warn"
    )
    _say(
        p,
        event,
        "machine",
        "Decision step",
        data.get("explanation") or verdict,
        detail=f"Reason code: {data['reason_code']}",
        tone=tone,
    )


def _on_model_usage(p: dict, event: dict, data: dict) -> None:
    cost = int(data.get("cost_minor") or 0)
    _add_money(p["spent"], "ai", cost)
    node = _node(p, event["node_id"])
    if node is not None:
        node["cost"] = _money(node.get("cost", _money(0))["amountMinor"] + cost)


# A review's verdict as the run's timeline names the decision (the reviewer portal's words).
VERDICT_TITLES = {
    "APPROVED": "Approved the result",
    "REVISION_REQUIRED": "Sent back with corrections",
    "REJECTED": "Rejected the result",
    "ESCALATED": "Escalated the result",
}


def _on_human_task(p: dict, event: dict, data: dict) -> None:
    node = _node(p, event["node_id"])
    task_id = data.get("task_id")
    if data.get("status", "open") == "open":
        if node is not None:
            node["status"] = "WAITING"
            node["humanTaskId"] = task_id
        _set_run_status(p, "WAITING_FOR_HUMAN")
        title = data.get("title") or "A reviewer task is open"
        p["attention"] = {
            "tone": "human",
            "title": "A step is waiting for a reviewer",
            "body": title,
            "href": f"/work/tasks/{task_id}",
            "cta": "Open the reviewer task",
        }
        _say(p, event, "system", "Human workforce", f"Created task {task_id}", detail=title, ref=task_id)
        return
    p.pop("attention", None)
    _set_run_status(p, "RUNNING")
    cost = int(data.get("cost_minor") or 0)
    _add_money(p["spent"], "human", cost)
    if node is not None and cost:
        node["cost"] = _money(node.get("cost", _money(0))["amountMinor"] + cost)
    titles = {
        "resolved": "Resolved the task",
        "rejected": "Rejected the task",
        "timeout": "The task timed out",
    }
    status = data.get("status")
    _say(
        p,
        event,
        "human" if status != "timeout" else "system",
        data.get("decided_by") or "Reviewer",
        VERDICT_TITLES.get(data.get("verdict") or "") or titles.get(status, f"Task {status}"),
        detail=data.get("note") or None,
        ref=task_id,
        tone="ok" if status == "resolved" else "blocked",
    )


def _on_approval(p: dict, event: dict, data: dict) -> None:
    node = _node(p, event["node_id"])
    approval_id = data.get("approval_id")
    if data.get("status", "pending") == "pending":
        if node is not None:
            node["status"] = "WAITING"
            node["note"] = f"Waiting on {approval_id}."
        _set_run_status(p, "WAITING_FOR_EVENT")
        p["attention"] = {
            "tone": "warn",
            "title": "Your approval is needed",
            "body": data.get("summary")
            or data.get("title")
            or (node or {}).get("label", "Approve the next step."),
            "href": "/app/approvals",
            "cta": "Review and approve",
        }
        _say(p, event, "system", "Workflow engine", "Asked for your approval", ref=approval_id)
        return
    p.pop("attention", None)
    _set_run_status(p, "RUNNING")
    status = data.get("status")
    titles = {"granted": "Approved", "denied": "Declined", "timeout": "The approval timed out"}
    _say(
        p,
        event,
        "buyer" if status != "timeout" else "system",
        data.get("decided_by") or "You",
        titles.get(status, f"Approval {status}"),
        ref=approval_id,
        tone="ok" if status == "granted" else "blocked",
    )


def _deliverable(p: dict, report: dict, mocked: bool) -> dict:
    """Turn the reconciliation report ({summary, rows, totals}) into the Deliverable the run page shows; used
    for a pack without a `deliverable_view`."""
    totals = report.get("totals") or {}
    rows = [r for r in report.get("rows") or [] if isinstance(r, list) and len(r) >= 6]
    facts = [
        ("Orders checked", totals.get("orders_count")),
        ("Matched", totals.get("matched_count")),
        ("Mismatches", totals.get("mismatch_count")),
    ]
    out_rows = [{"label": label, "value": str(value)} for label, value in facts if value is not None]
    if totals.get("net_difference_minor") is not None:
        net = f"{_major(totals['net_difference_minor'])} {totals.get('currency', CURRENCY)}"
        out_rows.append({"label": "Net difference", "value": net})
    out_rows.append({"label": "Rows in the report", "value": str(len(rows))})
    return {
        "title": p["title"],
        "kind": "Report rows",
        "summary": report.get("summary", ""),
        "rows": out_rows,
        "limitations": [SIMULATED_LIMITATION] if mocked else [],
        "unresolved": [f"{r[1]}: {r[5]}" for r in rows if r[4] in OPEN_ROW_STATUSES],
        "evidence": [],
    }


def deliverable_view(packs: dict | None) -> dict | None:
    """The pinned pack's `deliverable_view`, from a snapshot's `defs.pack`; None when it has none."""
    bodies = [(entry or {}).get("body") or {} for entry in (packs or {}).values()]
    view = bodies[0].get("deliverable_view") if len(bodies) == 1 else None
    return view if isinstance(view, dict) else None


def _view_value(value: Any, state: dict) -> Any:
    """A view field: CEL when it starts with "=", else the literal."""
    return cel.evaluate(value, state) if isinstance(value, str) and value.startswith("=") else value


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _view_items(spec: dict, state: dict) -> list[dict]:
    source = _view_value(spec["from"], state)
    if not isinstance(source, list):
        raise cel.CelError(f"items.from gave {type(source).__name__}, not a list")
    items = []
    for item in source[:VIEW_ITEMS_MAX]:
        scope = {**state, "item": item}
        detail = _text(_view_value(spec["detail"], scope))
        items.append({"label": _text(_view_value(spec["label"], scope)), "detail": detail[:VIEW_DETAIL_MAX]})
    return items


def _viewed_deliverable(p: dict, view: dict, deliverable: dict, mocked: bool) -> dict:
    """The Deliverable a pack describes with its `deliverable_view`. A view that fails to evaluate never
    fails the projection: it falls back to the summary alone (the deliverable's own when the view's fails).
    The view's CEL sees {deliverable, mocked}; `mocked` is true when any tool call in the run used sandbox
    data."""
    state = {"deliverable": deliverable, "mocked": mocked}
    own_summary = deliverable.get("summary")
    out = {
        "title": p["title"],
        "kind": _text(view.get("kind")) or "Result",
        "summary": own_summary if isinstance(own_summary, str) else "",
        "rows": [],
        "limitations": [SIMULATED_LIMITATION] if mocked else [],
        "unresolved": [],
        "evidence": [],
    }
    try:
        out["summary"] = _text(_view_value(view.get("summary", ""), state))
        rows = [
            {"label": _text(f.get("label")), "value": _text(_view_value(f.get("value"), state))}
            for f in view.get("facts") or []
        ]
        items = _view_items(view["items"], state) if isinstance(view.get("items"), dict) else None
    except Exception:  # nothing in a pack's view may fail the projection (and so record_events)
        log.warning(
            "Run %s: its pack's deliverable view did not evaluate; showing the summary only.",
            p["id"],
            exc_info=True,
        )
        return out
    out["rows"] = rows
    if items is not None:
        out["items"] = items
    return out


def _any_mocked_call(p: dict) -> bool:
    """Whether any tool.call receipt entry folded into this run ran against sandbox data."""
    return any(call.get("mocked") for node in p["nodes"] for call in node.get("toolCalls") or [])


def _on_run_completed(p: dict, event: dict, data: dict, view: dict | None = None) -> None:
    p["status"] = "COMPLETED"
    p["endedAt"] = event["at"]
    p.pop("attention", None)
    stages = p["stages"]
    stages.update(executed="done", accepted="not_required", settlement="not_required")
    # Verified only when a verification node passed in this run (it sets "done"); a run that ended without
    # one, such as a pack's "nothing to do" path, had no independent check. A recorded failure stays.
    if stages.get("verified") not in ("done", "failed"):
        stages["verified"] = "not_required"
    report = data.get("deliverable")
    if isinstance(report, dict):
        mocked = bool(data.get("mocked")) or _any_mocked_call(p)
        if view is not None:
            p["deliverable"] = _viewed_deliverable(p, view, report, mocked)
        else:
            p["deliverable"] = _deliverable(p, report, mocked)
    p["summary"] = data.get("summary") or (p.get("deliverable") or {}).get("summary") or "Completed."
    _say(p, event, "system", "Workflow engine", "Completed the run", tone="ok")


def _on_run_failed(p: dict, event: dict, data: dict) -> None:
    p["status"] = "FAILED"
    p["endedAt"] = event["at"]
    reason = data.get("reason") or "The run stopped."
    p["summary"] = reason
    p["attention"] = {"tone": "blocked", "title": "The run stopped", "body": reason}
    stages = p["stages"]
    if stages["executed"] == "pending":
        stages["executed"] = "failed"
    if stages["verified"] == "pending":
        stages["verified"] = "blocked"
    stages.update(accepted="not_required", settlement="not_required")
    _say(p, event, "system", "Workflow engine", "The run stopped", detail=reason, tone="blocked")


_HANDLERS: dict[str, Callable[[dict, dict, dict], None]] = {
    "node.started": _on_node_started,
    "node.completed": _on_node_completed,
    "node.waiting": _on_node_waiting,
    "node.failed": _on_node_failed,
    "tool.call": _on_tool_call,
    "decision": _on_decision,
    "model.usage": _on_model_usage,
    "human.task": _on_human_task,
    "approval": _on_approval,
    "run.failed": _on_run_failed,
}


def apply_event(projection: dict, event: dict, view: dict | None = None) -> dict:
    """Fold one event into a copy of `projection`. `view` is the pinned pack's `deliverable_view` (see
    `deliverable_view`); without one, a completed run's deliverable is read as a reconciliation report."""
    updated = copy.deepcopy(projection)
    data = event.get("data") or {}
    if event["type"] == "run.completed":
        _on_run_completed(updated, event, data, view)
    elif (handler := _HANDLERS.get(event["type"])) is not None:
        handler(updated, event, data)
    return updated


def save(conn, run_id: str, projection: dict, status: str) -> None:
    """Store the projection and run status on the runs row. Does not commit."""
    conn.execute(
        "UPDATE runs SET projection = %s, status = %s, updated_at = now() WHERE id = %s",
        (Jsonb(projection), status, run_id),
    )
