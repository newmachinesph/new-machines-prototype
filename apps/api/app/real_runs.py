"""Real runs (NM_RUNTIME=temporal): pin a snapshot, insert the run, start PackRunner; read runs and receipts.

Every function here needs Postgres. The runs router only calls them when the runtime is on.
"""

import logging
import re
from datetime import UTC, date, datetime, timedelta

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app import db, settings, temporal_client
from app.auth import Actor
from app.defs import registry
from app.defs.snapshot import build_snapshot
from app.errors import ApiProblem
from app.models.common import money_text
from app.models.ops import ConnectorEntry
from app.models.requests import StartRunRequest
from app.models.runs import PinnedVersion, Receipt, ReceiptItem, Run, RunSummary
from app.runtime import gateway, projection, receipt
from app.store import iso
from app.worker.activities import event_key, record_events

log = logging.getLogger(__name__)

STARTED_BY = "You"
LIST_LIMIT = 50
DEFAULT_DAYS = 7
MAX_DAYS = 366
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})")
_LAST_DAYS = re.compile(r"\blast\s+(\d+)\s+days?\b", re.IGNORECASE)


# --- start ----------------------------------------------------------------------------------------------


def has_pack(slug: str) -> bool:
    """True when the runtime is on and the registry has a pack definition with this slug."""
    if not settings.runtime_enabled():
        return False
    with db.connect() as conn:
        return registry.latest(conn, "pack", slug) is not None


def _invalid(detail: str) -> ApiProblem:
    return ApiProblem(422, "INVALID_INPUT", detail)


def _day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _invalid(f"{text} is not a valid date.") from None


def parse_run_input(text: str, today: date | None = None) -> dict:
    """The start form's free text as the pack input {since, until} (ISO dates, both inclusive).

    `YYYY-MM-DD..YYYY-MM-DD` is a range, "last N days" ends today (UTC), anything else is the last 7 days."""
    today = today or datetime.now(UTC).date()
    if found := _RANGE.search(text):
        since, until = _day(found[1]), _day(found[2])
        if since > until:
            raise _invalid("The range starts after it ends.")
    else:
        days = int(found[1]) if (found := _LAST_DAYS.search(text)) else DEFAULT_DAYS
        if not 1 <= days <= MAX_DAYS:
            raise _invalid(f"Choose between 1 and {MAX_DAYS} days.")
        since, until = today - timedelta(days=days - 1), today
    if (until - since).days >= MAX_DAYS:
        raise _invalid(f"A run covers at most {MAX_DAYS} days.")
    return {"since": since.isoformat(), "until": until.isoformat()}


def ops_connector_policy(snapshot: dict, catalog: list[ConnectorEntry]) -> tuple[dict, list[str]]:
    """(overrides, disabled) for the snapshot's connectors from the Ops connector catalog, matched by app
    name: overrides = the Ops action-class defaults by connector key; disabled = those Ops has disabled."""
    by_app = {entry.app.casefold(): entry for entry in catalog}
    overrides, disabled = {}, []
    for key, item in sorted(((snapshot.get("defs") or {}).get("connector") or {}).items()):
        entry = by_app.get(str((item.get("body") or {}).get("app", "")).casefold())
        if entry is None:
            continue
        overrides[key] = entry.defaults.model_dump()
        if entry.status == "disabled":
            disabled.append(key)
    return overrides, disabled


def _contract_budget(snapshot: dict) -> tuple[int, str]:
    """(maximum_minor, currency) of the pinned contract's budget; 0 when it sets no maximum."""
    budget = gateway.contract_of(snapshot).get("budget") or {}
    return int(budget.get("maximum_minor") or 0), str(budget.get("currency") or "USD")


def _insert_run(body: StartRunRequest, actor: Actor, catalog: list[ConnectorEntry], inp: dict) -> dict:
    """Pin the snapshot, insert the runs row and its `run.started` receipt entry; commit. Returns the row
    values the workflow needs: {run_id, snapshot, projection}."""
    with db.connect() as conn:
        try:
            snapshot = build_snapshot(conn, body.pack_slug, actor.org_id, {}, set())
        except LookupError as exc:
            log.error("Cannot pin %s: %s", body.pack_slug, exc)
            raise ApiProblem(409, "PACK_UNAVAILABLE", "This Workflow Pack cannot run right now.") from None
        maximum, currency = _contract_budget(snapshot)
        if maximum and body.budget_minor > maximum:
            limit = money_text(maximum, currency)
            raise ApiProblem(422, "BUDGET_TOO_HIGH", f"The budget can be at most {limit} for this pack.")
        overrides, disabled = ops_connector_policy(snapshot, catalog)
        snapshot = {
            **snapshot,
            "overrides": overrides,
            "disabled": disabled,
            "budget_minor": body.budget_minor,
        }
        number = conn.execute("SELECT nextval('run_number') AS n").fetchone()["n"]
        run_id = f"run_{number}"
        initial = projection.initial_projection(run_id, snapshot, inp, STARTED_BY, body.budget_minor)
        conn.execute(
            "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input) "
            "VALUES (%s, %s, %s, 'RUNNING', %s, %s, %s)",
            (run_id, actor.org_id, body.pack_slug, Jsonb(snapshot), Jsonb(initial), Jsonb(inp)),
        )
        started = {
            "versions": snapshot["versions"],
            "input": inp,
            "budget_minor": body.budget_minor,
            "started_by": actor.user_id,
        }
        record_events(conn, run_id, [(event_key(None, 0, "run.started", 0), "run.started", None, started)])
        conn.commit()
    return {"run_id": run_id, "snapshot": snapshot, "projection": initial}


def _fail_unstarted(run_id: str) -> None:
    """The workflow could not be started: end the run as FAILED, with the reason in its (sealed) receipt."""
    failed = {"reason": "The workflow engine was unavailable, so the run did not start."}
    with db.connect() as conn:
        record_events(conn, run_id, [(event_key(None, 0, "run.failed", 0), "run.failed", None, failed)])
        conn.commit()


def _stop_unstarted(run_id: str) -> None:
    """A start that failed or timed out may still have reached Temporal: terminate that workflow if it exists
    (best effort). Should one start anyway, its first activity finds the receipt sealed and ends it."""
    try:
        temporal_client.terminate_run(run_id, "The API gave up starting this run.")
    except Exception as exc:  # not found (the usual case) or Temporal unreachable
        log.info("No workflow to terminate for %s (%s).", run_id, type(exc).__name__)


def start_real_run(body: StartRunRequest, actor: Actor, catalog: list[ConnectorEntry]) -> Run:
    """Insert the run, then start PackRunner (workflow id = run id). 503 when Temporal is unreachable."""
    inp = parse_run_input(body.input)
    created = _insert_run(body, actor, catalog, inp)
    run_id = created["run_id"]
    try:
        temporal_client.start_run(run_id, created["snapshot"], inp)
    except Exception:
        log.exception("Could not start the workflow for %s", run_id)
        _stop_unstarted(run_id)
        _fail_unstarted(run_id)
        raise ApiProblem(
            503, "RUNTIME_UNAVAILABLE", "The run could not be started. Try again in a minute."
        ) from None
    return Run.model_validate(created["projection"])


# --- read -----------------------------------------------------------------------------------------------


def real_summaries(org_id: str) -> list[RunSummary]:
    """The org's real runs, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, projection FROM runs WHERE org_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
            (org_id, LIST_LIMIT),
        ).fetchall()
    summaries = []
    for row in rows:
        try:
            summaries.append(Run.model_validate(row["projection"]).summary_row())
        except ValidationError:
            log.error("Run %s has a malformed projection; left out of the list.", row["id"], exc_info=True)
    return summaries


def real_run(org_id: str, run_id: str) -> Run | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT projection FROM runs WHERE id = %s AND org_id = %s", (run_id, org_id)
        ).fetchone()
    return Run.model_validate(row["projection"]) if row else None


def ops_runs() -> list[tuple[str, RunSummary]]:
    """(org id, summary) of the newest real runs of every org, for the operator console."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, org_id, projection FROM runs ORDER BY created_at DESC, id DESC LIMIT %s",
            (LIST_LIMIT,),
        ).fetchall()
    found = []
    for row in rows:
        try:
            found.append((row["org_id"], Run.model_validate(row["projection"]).summary_row()))
        except ValidationError:
            log.error("Run %s has a malformed projection; left out of the list.", row["id"], exc_info=True)
    return found


def ops_run(run_id: str) -> Run | None:
    """A real run of any org, for the operator console."""
    with db.connect() as conn:
        row = conn.execute("SELECT projection FROM runs WHERE id = %s", (run_id,)).fetchone()
    return Run.model_validate(row["projection"]) if row else None


def _summary(type_: str, node_id: str | None, data: dict) -> str:
    """A short human line per receipt entry type."""
    node = node_id or "run"
    policy = data.get("policy") or {}
    match type_:
        case "run.started":
            return f"Run started with {len(data.get('versions') or [])} pinned definitions."
        case "node.started":
            return f"{node} started."
        case "node.waiting":
            return f"{node} is waiting: {data.get('note') or 'for a person'}."
        case "node.completed":
            route = data.get("route")
            return f"{node} completed" + (f" ({route})." if route else ".")
        case "node.failed":
            return f"{node} failed: {data.get('error') or data.get('status') or 'error'}."
        case "tool.call":
            mocked = " (simulated)" if data.get("mocked") else ""
            return f"{data.get('tool_ref') or 'Tool call'}: {policy.get('verdict', '?')}{mocked}."
        case "decision":
            return f"Decision {data.get('verdict', '?')} ({data.get('reason_code', '?')})."
        case "model.usage":
            tokens = int(data.get("input_tokens") or 0) + int(data.get("output_tokens") or 0)
            return f"Model call: {tokens} tokens, {int(data.get('cost_minor') or 0)} minor units."
        case "human.task":
            return f"Human task {data.get('task_id', '?')}: {data.get('status', '?')}."
        case "approval":
            return f"Approval {data.get('approval_id', '?')}: {data.get('status', '?')}."
        case "run.completed":
            return "Run completed."
        case "run.failed":
            return f"Run failed: {data.get('reason') or 'stopped'}"
        case "receipt.sealed":
            return f"Receipt sealed after {data.get('entry_count', 0)} entries ({data.get('status', '')})."
    return type_


def receipt_of(org_id: str | None, run_id: str) -> Receipt | None:
    """The run's receipt with the chain recomputed now; None when the org has no such real run.
    `org_id=None` (the operator console) matches a run of any org."""
    with db.connect() as conn:
        run = conn.execute(
            "SELECT snapshot->'versions' AS versions FROM runs "
            "WHERE id = %s AND (%s::text IS NULL OR org_id = %s)",
            (run_id, org_id, org_id),
        ).fetchone()
        if run is None:
            return None
        verified, count, head = receipt.verify(conn, run_id)
        rows = conn.execute(
            "SELECT seq, at, type, node_id, data, hash FROM receipt_entries WHERE run_id = %s ORDER BY seq",
            (run_id,),
        ).fetchall()
    items = [
        ReceiptItem(
            seq=r["seq"],
            at=iso(r["at"]),
            type=r["type"],
            node_id=r["node_id"],
            summary=_summary(r["type"], r["node_id"], r["data"] or {}),
            hash=r["hash"],
        )
        for r in rows
    ]
    pinned = [PinnedVersion.model_validate(v) for v in run["versions"] or []]
    return Receipt(
        run_id=run_id, verified=verified, entries=count, head_hash=head, pinned=pinned, items=items
    )
