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
# The run's title, its step labels and pinned connector definitions come along so a row maps onto the API
# models alone.
_SELECT = (
    "SELECT t.id, t.run_id, t.node_id, t.kind, t.status, t.payload, t.result, t.created_at, t.decided_by, "
    "t.decided_at, r.projection->>'title' AS run_title, "
    "(SELECT jsonb_agg(jsonb_build_object('id', n->'id', 'label', n->'label')) "
    "FROM jsonb_array_elements(r.projection->'nodes') n) AS run_nodes, "
    "r.snapshot->'defs'->'connector' AS connectors "
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


def apply_claim(conn, row: dict, by: str, marks: dict | None = None) -> None:
    """Claim `row`, an open human task locked FOR UPDATE in this transaction, for `by`: the holder, the time
    and `marks` merge into its payload (the row stays open). Does not commit. Claiming a task `by` already
    holds changes nothing; a decided task, or one someone else holds, is a 409."""
    holder = (row["payload"] or {}).get("claimed_by")
    if row["status"] != OPEN_STATUSES["human"] or holder not in (None, by):
        raise ApiProblem(409, "CONFLICT", "This task can no longer be claimed.")
    if holder is None:
        claim_marks = {"claimed_by": by, "claimed_at": utc_now(), **(marks or {})}
        conn.execute(
            "UPDATE run_tasks SET payload = payload || %s WHERE id = %s", (Jsonb(claim_marks), row["id"])
        )


def claim(org_id: str, task_id: str, by: str) -> dict:
    """Claim an open human task of the org for `by` (`apply_claim`) and commit. Returns the updated row."""
    with db.connect() as conn:
        apply_claim(conn, _locked(conn, org_id, "human", task_id), by)
        updated = conn.execute(f"{_SELECT} AND t.id = %s", (org_id, "human", task_id)).fetchone()
        conn.commit()
    return updated


_RELEASE = (
    "UPDATE run_tasks t SET payload = t.payload - 'claimed_by' - 'claimed_at' - 'claimed_via' - 'pay' "
    "FROM runs r WHERE r.id = t.run_id AND t.kind = 'human' AND t.status = 'open' "
    "AND t.payload->>'claimed_by' IS NOT NULL "
    "AND (%(org)s::text IS NULL OR r.org_id = %(org)s) "
    "AND (%(pack)s::text IS NULL OR r.pack_slug = %(pack)s) "
    "AND (%(user)s::text IS NULL OR t.payload->>'claimed_by' = %(user)s) "
    "AND (%(via)s::text IS NULL OR t.payload->>'claimed_via' = %(via)s)"
)


def release_claims(
    conn,
    *,
    org_id: str | None = None,
    user_id: str | None = None,
    via: str | None = None,
    pack_slug: str | None = None,
) -> int:
    """Put open human tasks back in the queue by removing their claim (holder, time, route and network pay).
    Filters: tasks of `org_id`'s runs, of runs of `pack_slug`, claimed by `user_id`, claimed through `via`
    ("team" or "network"); at least one of org, user and route is required. Does not commit. Returns how many
    tasks were released."""
    if org_id is None and user_id is None and via is None:
        raise ValueError("release_claims needs a filter")
    params = {"org": org_id, "pack": pack_slug, "user": user_id, "via": via}
    return conn.execute(_RELEASE, params).rowcount


def apply_decision(conn, row: dict, kind: str, status: str, by: str, result: dict) -> bool:
    """Record a decision on `row`, a task row locked FOR UPDATE in this transaction; does not commit. False
    when `by` repeats the decision already recorded (nothing is written, so the caller can signal it again);
    a 409 for any other change to a decided task, and for a human task not claimed by `by`."""
    if row["status"] != OPEN_STATUSES[kind]:
        if row["status"] == status and row["decided_by"] == by:
            return False
        raise ApiProblem(409, "CONFLICT", f"This {_noun(kind)} is already {row['status']}.")
    if kind == "human" and (row["payload"] or {}).get("claimed_by") != by:
        raise ApiProblem(409, "CONFLICT", "Claim the task before submitting a review.")
    conn.execute(
        "UPDATE run_tasks SET status = %s, decided_by = %s, decided_at = now(), result = %s WHERE id = %s",
        (status, by, Jsonb(result), row["id"]),
    )
    return True


def decide(org_id: str, kind: str, task_id: str, status: str, by: str, result: dict) -> dict:
    """Record the decision on an open task of the org (`apply_decision`) and commit. Returns the updated row;
    the same person repeating the recorded decision gets the stored row back unchanged."""
    with db.connect() as conn:
        row = _locked(conn, org_id, kind, task_id)
        if apply_decision(conn, row, kind, status, by, result):
            row = conn.execute(f"{_SELECT} AND t.id = %s", (org_id, kind, task_id)).fetchone()
        conn.commit()
    return row


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
