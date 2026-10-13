"""Real runs (NM_RUNTIME=temporal): pin a snapshot, insert the run, start PackRunner; read runs and receipts.

Every function here needs Postgres. The runs router only calls them when the runtime is on.
"""

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as InputError
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app import db, settings, temporal_client
from app.auth import Actor
from app.defs import registry
from app.defs.snapshot import build_snapshot
from app.errors import ApiProblem, ProblemIssue
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
MAX_INPUT_BYTES = 10_000
MAX_INPUT_ISSUES = 20
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


def input_schema(conn, pack_slug: str) -> dict | None:
    """The JSON Schema of the pack's run input: its Work Contract's `input_schema_ref` (the contract is the
    workflow's `work_contract_ref`, else the pack's `contract`, as in the pinned snapshot)."""
    pack = registry.latest(conn, "pack", pack_slug)
    if pack is None:
        return None
    workflow = registry.latest(conn, "workflow", str(pack.body.get("workflow") or ""))
    key = (workflow.body if workflow else {}).get("work_contract_ref") or pack.body.get("contract")
    contract = registry.latest(conn, "contract", str(key or ""))
    ref = (contract.body if contract else {}).get("input_schema_ref")
    schema = registry.latest(conn, "schema", str(ref)) if ref else None
    return schema.body if schema else None


def _join(prefix: str, field: object) -> str:
    return f"{prefix}/{field}" if prefix else str(field)


def _field_issues(pack_slug: str, error: InputError) -> list[ProblemIssue]:
    """The input issues one schema error stands for, each at the field it is about: a missing field and an
    unknown field are named by their own path (one issue per field), any other error by the value's path."""
    path = "/".join(str(p) for p in error.absolute_path)
    instance = error.instance if isinstance(error.instance, dict) else None
    fields: list[tuple[str, str]] = []
    if instance is not None and error.validator == "required":
        fields = [(f, f"{f} is required.") for f in error.validator_value if f not in instance]
    elif instance is not None and error.validator == "additionalProperties":
        known = set(error.schema.get("properties") or {})
        patterns = [re.compile(p) for p in error.schema.get("patternProperties") or {}]
        unknown = [k for k in instance if k not in known and not any(p.search(k) for p in patterns)]
        fields = [(k, f"{k} is not a field this pack takes.") for k in unknown]
    if not fields:
        return [ProblemIssue(kind="input", key=pack_slug, path=path, message=error.message)]
    return [ProblemIssue(kind="input", key=pack_slug, path=_join(path, f), message=m) for f, m in fields]


def _input_issues(pack_slug: str, errors: list[InputError]) -> list[ProblemIssue]:
    """Every field issue once, sorted by path. jsonschema reports a `required` error once per missing field,
    each listing every required field, so issues are de-duplicated."""
    seen: dict[tuple[str, str], ProblemIssue] = {}
    for error in errors:
        for issue in _field_issues(pack_slug, error):
            seen.setdefault((issue.path, issue.message), issue)
    return sorted(seen.values(), key=lambda i: (i.path, i.message))[:MAX_INPUT_ISSUES]


def check_input(pack_slug: str, value: str | dict, schema: dict | None) -> dict:
    """The run input: an object as given, or free text parsed as a date range (`parse_run_input`). It must
    match the pack's input schema; 422 INVALID_INPUT lists each field error otherwise."""
    inp = parse_run_input(value) if isinstance(value, str) else value
    if len(json.dumps(inp)) > MAX_INPUT_BYTES:
        raise _invalid("The input is too large.")
    if not schema:
        return inp
    issues = _input_issues(pack_slug, list(Draft202012Validator(schema).iter_errors(inp)))
    if not issues:
        return inp
    first = issues[0]
    where = f"{first.path}: " if first.path else ""
    raise ApiProblem(422, "INVALID_INPUT", f"The input is not valid. {where}{first.message}", errors=issues)


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


def start_real_run(
    body: StartRunRequest, actor: Actor, catalog: list[ConnectorEntry], inp: dict | None = None
) -> Run:
    """Insert the run, then start PackRunner (workflow id = run id). 503 when Temporal is unreachable.
    `inp` is the input already checked (`check_input`); without it the body's input is checked here."""
    if inp is None:
        with db.connect() as conn:
            schema = input_schema(conn, body.pack_slug)
        inp = check_input(body.pack_slug, body.input, schema)
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
