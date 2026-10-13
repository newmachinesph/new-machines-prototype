"""Real human tasks and approvals: the `run_tasks` rows PackRunner opens, read and decided through the API.

A decision is recorded on the row (status, decided_by, decided_at, result) and committed before the
workflow is signalled. If the signal fails the recorded decision stands: the same person sending the same
decision again gets it re-signalled (the workflow ignores a duplicate), and when the task's timer fires the
workflow reads the row and follows the recorded decision instead of the timeout. When Temporal no longer
knows the workflow at all (its history was lost), the run is ended FAILED rather than left waiting.
"""

import logging
from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from app import db, settings
from app.errors import ApiProblem
from app.store import utc_now
from app.worker.activities import RUN_SEALED, event_key, record_events

log = logging.getLogger(__name__)

LIST_LIMIT = 100
OPEN_STATUSES = {"human": "open", "approval": "pending"}
LOST_REASON = "The workflow engine lost this run, so it could not continue."
# The run's title and pinned connector definitions come along so a row maps onto the API models alone.
_SELECT = (
    "SELECT t.id, t.run_id, t.node_id, t.kind, t.status, t.payload, t.result, t.created_at, t.decided_by, "
    "t.decided_at, r.projection->>'title' AS run_title, r.snapshot->'defs'->'connector' AS connectors "
    "FROM run_tasks t JOIN runs r ON r.id = t.run_id WHERE r.org_id = %s AND t.kind = %s"
)


def list_rows(org_id: str, kind: str) -> list[dict]:
    """Newest first; none when the runtime is off (no database)."""
    if not settings.runtime_enabled():
        return []
    with db.connect() as conn:
        return conn.execute(
            f"{_SELECT} ORDER BY t.created_at DESC, t.id DESC LIMIT %s", (org_id, kind, LIST_LIMIT)
        ).fetchall()


def get_row(org_id: str, kind: str, task_id: str) -> dict | None:
    if not settings.runtime_enabled():
        return None
    with db.connect() as conn:
        return conn.execute(f"{_SELECT} AND t.id = %s", (org_id, kind, task_id)).fetchone()


def _locked(conn, org_id: str, kind: str, task_id: str) -> dict:
    row = conn.execute(f"{_SELECT} AND t.id = %s FOR UPDATE OF t", (org_id, kind, task_id)).fetchone()
    if row is None:
        raise ApiProblem(404, "NOT_FOUND", f"No task {task_id}.")
    return row


def claim(org_id: str, task_id: str, by: str) -> dict:
    """Mark an open human task as claimed by `by` (kept in its payload; the row stays open). 409 otherwise."""
    with db.connect() as conn:
        row = _locked(conn, org_id, "human", task_id)
        holder = (row["payload"] or {}).get("claimed_by")
        if row["status"] != OPEN_STATUSES["human"] or holder not in (None, by):
            raise ApiProblem(409, "CONFLICT", "This task can no longer be claimed.")
        conn.execute(
            "UPDATE run_tasks SET payload = payload || %s WHERE id = %s",
            (Jsonb({"claimed_by": by, "claimed_at": utc_now()}), task_id),
        )
        updated = conn.execute(f"{_SELECT} AND t.id = %s", (org_id, "human", task_id)).fetchone()
        conn.commit()
    return updated


def decide(org_id: str, kind: str, task_id: str, status: str, by: str, result: dict) -> dict:
    """Record the decision on an open task and commit. Returns the updated row.

    The same person repeating the decision already recorded gets the stored row back unchanged (so the caller
    can signal it again); any other change to a decided task is a 409, as is a human task not claimed by `by`.
    """
    with db.connect() as conn:
        row = _locked(conn, org_id, kind, task_id)
        if row["status"] != OPEN_STATUSES[kind]:
            if row["status"] == status and row["decided_by"] == by:
                return row
            raise ApiProblem(409, "CONFLICT", f"This {_noun(kind)} is already {row['status']}.")
        if kind == "human" and (row["payload"] or {}).get("claimed_by") != by:
            raise ApiProblem(409, "CONFLICT", "Claim the task before submitting a review.")
        conn.execute(
            "UPDATE run_tasks SET status = %s, decided_by = %s, decided_at = now(), result = %s "
            "WHERE id = %s",
            (status, by, Jsonb(result), task_id),
        )
        updated = conn.execute(f"{_SELECT} AND t.id = %s", (org_id, kind, task_id)).fetchone()
        conn.commit()
    return updated


def signal(send: Callable[..., None], run_id: str, *args: Any) -> None:
    """Signal the run's workflow. A failure is logged and swallowed: the decision is already recorded. When
    Temporal reports the workflow missing, the run is ended FAILED (unless it already finished)."""
    try:
        send(run_id, *args)
    except RPCError as exc:
        # NOT_FOUND also means a missing namespace (bad config); only a missing workflow ends the run.
        if exc.status != RPCStatusCode.NOT_FOUND or "namespace" in exc.message.lower():
            _log_failed(send, run_id, args)
            return
        log.warning("Signal %s for %s: the workflow does not exist; ending the run.", send.__name__, run_id)
        fail_lost_run(run_id)
    except Exception:
        _log_failed(send, run_id, args)


def fail_lost_run(run_id: str) -> None:
    """End a run whose workflow Temporal no longer has with run.failed, which seals its receipt. A run that
    already finished (sealed) is left as it is."""
    key = f"{event_key(None, 0, 'run.failed', 0)}:lost"
    try:
        with db.connect() as conn:
            record_events(conn, run_id, [(key, "run.failed", None, {"reason": LOST_REASON})])
            conn.commit()
    except ApplicationError as exc:
        if exc.type != RUN_SEALED:
            raise


def _log_failed(send: Callable[..., None], run_id: str, args: tuple) -> None:
    log.warning(
        "Signal %s%r failed; the recorded decision stands.",
        send.__name__,
        (run_id, *args[:2]),
        exc_info=True,
    )


def _noun(kind: str) -> str:
    return "task" if kind == "human" else "approval"
