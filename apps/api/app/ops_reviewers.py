"""Ops console, live workspace: the New Machines reviewer network read from `network_reviewers`, with each
reviewer's last 30 days of network work, and suspend / reinstate written to `ops_audit`. A reviewer who turned
"Review for the network" off is listed only while suspended."""

from datetime import UTC, datetime, timedelta

from app import ops_state, run_tasks
from app.errors import ApiProblem
from app.models.common import Money
from app.models.ops import OpsRole, Reviewer, ReviewerStatus
from app.store import iso

WINDOW_DAYS = 30
LIVE_LEVEL = "trainee"  # the network has no levels; the console hides the column in the live workspace
LIVE_ACCURACY = 1.0  # not measured without an acceptance check; the console hides the column too

# A network task the reviewer decided within the window.
_DONE = "t.decided_at >= %(since)s AND t.decided_by = n.user_id"
_SELECT = (
    "SELECT n.user_id, n.name, n.email, n.languages, n.skills, n.status, n.created_at, "
    f"count(t.id) FILTER (WHERE {_DONE}) AS done, "
    f"COALESCE(sum((t.payload->>'pay')::bigint) FILTER (WHERE {_DONE}), 0) AS earned, "
    "count(t.id) FILTER (WHERE t.status = 'open') AS queue, "
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM t.decided_at "
    f"- (t.payload->>'claimed_at')::timestamptz) / 60) FILTER (WHERE {_DONE}) AS median "
    "FROM network_reviewers n LEFT JOIN run_tasks t ON t.kind = 'human' "
    "AND t.payload->>'claimed_by' = n.user_id AND t.payload->>'claimed_via' = 'network' "
)


def _reviewer(row: dict) -> Reviewer:
    return Reviewer(
        id=row["user_id"],
        name=row["name"],
        email=row["email"],
        country="",
        languages=list(row["languages"]),
        skills=list(row["skills"]),
        level=LIVE_LEVEL,
        status=row["status"],
        tasks_done30d=int(row["done"]),
        accuracy=LIVE_ACCURACY,
        median_minutes=round(row["median"] or 0),
        earnings30d=Money(amount_minor=int(row["earned"])),
        joined_at=iso(row["created_at"]),
        queue=int(row["queue"]),
    )


def _rows(conn, where: str, params: dict) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
    return conn.execute(
        f"{_SELECT} WHERE {where} GROUP BY n.user_id ORDER BY n.created_at, n.user_id",
        {"since": since, **params},
    ).fetchall()


def list_reviewers(conn, status: ReviewerStatus | None) -> list[Reviewer]:
    """Network reviewers who are enabled, or suspended, oldest first; `status` filters (no applicants
    live)."""
    rows = _rows(
        conn,
        "(n.enabled OR n.status = 'suspended') AND (%(status)s::text IS NULL OR n.status = %(status)s)",
        {"status": status},
    )
    return [_reviewer(r) for r in rows]


def move(
    conn,
    user_id: str,
    verb: str,
    allowed: ReviewerStatus,
    target: ReviewerStatus,
    actor_email: str,
    reason: str,
    *,
    actor_role: OpsRole | None = None,
) -> Reviewer:
    """One status step, audited; a suspension returns the reviewer's open network claims to the queue. Locks
    the profile row before the release touches any task: the lock order of `app.review_routing`, so a claim
    in flight either commits first and is released, or waits and then cannot see the task. Does not
    commit."""
    row = conn.execute(
        "SELECT status FROM network_reviewers WHERE user_id = %s FOR UPDATE", (user_id,)
    ).fetchone()
    if row is None:
        raise ApiProblem(404, "NOT_FOUND", f"No reviewer {user_id}.")
    if row["status"] != allowed:
        raise ApiProblem(
            409, "INVALID_TRANSITION", f"A {row['status']} reviewer cannot be moved with {verb}."
        )
    conn.execute(
        "UPDATE network_reviewers SET status = %s, updated_at = now() WHERE user_id = %s", (target, user_id)
    )
    if target == "suspended":
        run_tasks.release_claims(conn, user_id=user_id, via="network")
    summary = {"summary": f"Status {allowed} → {target}"}
    ops_state.audit(
        conn, actor_email, f"reviewer.{verb}", "reviewer", user_id, reason, summary, actor_role=actor_role
    )
    [updated] = _rows(conn, "n.user_id = %(user)s", {"user": user_id})
    return _reviewer(updated)
