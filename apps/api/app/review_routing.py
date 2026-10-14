"""Who sees a human-review task in the reviewer portal (/work), in the live workspace.

A task belongs to a run of an org, and the org's hire of the pack sets its reviewer pool:

| Pool | Org's reviewers | Network reviewers (org switch on) |
|---|---|---|
| team | see it | never |
| network | only while the switch is off | see it |
| team_then_network | see it | once it is 30 minutes old and nobody has claimed it |

A run whose pack has no hire row counts as `team`. With the org's switch "Allow the New Machines reviewer
network" off, or the org suspended, the network sees none of the org's tasks. Team reviewers are active
members with the reviewer capability (`org_members.reviewer`); network reviewers have an enabled, active
`network_reviewers` row and never reach their own org's tasks through the network.

The 30 minutes are a rule on `created_at` evaluated in the query, with `now` as a parameter, not a Temporal
timer: PackRunner is unchanged (recorded histories still replay), the org switch and the hire's pool are
read at every request, and tests check the boundary exactly. Each row carries `via` ("team" or "network"),
which decides the copy a reviewer gets (`routers.tasks.real_task`), and `org_name`, which a network copy
scrubs out.

Task ids. The org's own team addresses a task by its id (`run_tasks.id`, which carries the run id). A network
reviewer addresses it by `run_tasks.public_id` (migration 009) and never reaches it by its id, since another
org's run ids are not theirs to know (`address`).

Lock order. Every transaction that changes who may hold a task locks rows in this order, each in its own
statement: `network_reviewers` -> `orgs` -> `org_members` -> `run_tasks`. A claim or decision (`_locked`)
takes the reviewer's profile, the task's org and the reviewer's membership of it FOR SHARE, then the task
FOR UPDATE. The changes lock their row first, then release claims:
- a user's switch-off (`network_reviewers.update`) and an operator's suspension (`ops_reviewers.move`):
  their profile;
- an org's network switch-off (`org_reviewers.set_network`), an operator's tenant suspension
  (`ops_live.suspend`) and a pack's pool saved as `team` (`live_catalog.install`): the org;
- a reviewer's removal (`org_reviewers.remove`) and a member leaving (`workspace._leave`): the membership
  (`_leave` locks the org before it only to delete an empty org).
Whichever commits second sees the other: a change that waited releases the claim just committed, and a
claim that waited reads the committed change in a fresh snapshot and gets a 404.
"""

from datetime import UTC, datetime, timedelta

from app import db, run_tasks
from app.errors import ApiProblem

NETWORK_DELAY = timedelta(minutes=30)
NETWORK_PAY_PER_RECORD_MINOR = 150  # simulated pay per record shown; no money moves
LIST_LIMIT = 100

_POOL = "COALESCE(i.reviewer_pool, 'team')"
_SELECT = (
    "SELECT t.id, t.public_id, t.run_id, t.node_id, t.kind, t.status, t.payload, t.result, t.created_at, "
    "t.decided_by, t.decided_at, r.projection->>'title' AS run_title, "
    "r.snapshot->'defs'->'connector' AS connectors, o.name AS org_name, "
    "CASE WHEN r.org_id = %(org)s THEN 'team' ELSE 'network' END AS via "
    "FROM run_tasks t JOIN runs r ON r.id = t.run_id JOIN orgs o ON o.id = r.org_id "
    "LEFT JOIN installations i ON i.org_id = r.org_id AND i.pack_slug = r.pack_slug "
)
# The org's own reviewers: every task of its runs, except a network-pool task while the switch is on (unless
# the reviewer claimed it before the switch went on).
_TEAM = (
    "r.org_id = %(org)s AND EXISTS (SELECT 1 FROM org_members m WHERE m.org_id = r.org_id "
    "AND m.user_id = %(user)s AND m.status = 'active' AND m.reviewer) "
    f"AND ({_POOL} <> 'network' OR NOT o.allow_network OR t.payload->>'claimed_by' = %(user)s)"
)
# An open task nobody has claimed.
_UNCLAIMED = "t.status = %(open)s AND t.payload->>'claimed_by' IS NULL"
# An unclaimed task the network is offered.
_OFFERED = (
    f"{_UNCLAIMED} AND ({_POOL} = 'network' "
    f"OR ({_POOL} = 'team_then_network' AND t.created_at <= %(cutoff)s))"
)
# A network reviewer: other active orgs' offers with the switch on, and the tasks they claimed through the
# network.
_NETWORK = (
    "r.org_id <> %(org)s AND o.status = 'active' AND o.allow_network "
    "AND EXISTS (SELECT 1 FROM network_reviewers n WHERE n.user_id = %(user)s AND n.enabled "
    "AND n.status = 'active') AND ((t.payload->>'claimed_by' = %(user)s "
    f"AND t.payload->>'claimed_via' = 'network') OR ({_OFFERED}))"
)
_VISIBLE = f"{_SELECT}WHERE t.kind = 'human' AND (({_TEAM}) OR ({_NETWORK}))"
# The task `%(id)s` names: by its id for the org's own team, by its public id for anyone else (the network).
_ADDRESSED = "((r.org_id = %(org)s AND t.id = %(id)s) OR (r.org_id <> %(org)s AND t.public_id = %(id)s))"


def _params(org_id: str, user_id: str, now: datetime | None, **more) -> dict:
    cutoff = (now or datetime.now(UTC)) - NETWORK_DELAY
    open_status = run_tasks.OPEN_STATUSES["human"]
    return {"org": org_id, "user": user_id, "cutoff": cutoff, "open": open_status, **more}


def address(row: dict) -> str:
    """The id the reviewer addresses a visible task by: its id for the team, its public id for the network."""
    return row["public_id"] if row.get("via") == "network" else row["id"]


def network_pay_minor(payload: dict) -> int:
    """Simulated pay for a network review: a fixed amount per record shown, at least one record's worth."""
    shown = payload.get("show")
    return max(len(shown) if isinstance(shown, list) else 0, 1) * NETWORK_PAY_PER_RECORD_MINOR


def visible_rows(
    org_id: str, user_id: str, *, now: datetime | None = None, offered: bool = False
) -> list[dict]:
    """The human tasks the user may see, newest first: their org's as a team reviewer, other orgs' as a
    network reviewer. `offered`: only open, unclaimed ones (the offers), so decided and claimed tasks do not
    use up the limit."""
    where = f" AND {_UNCLAIMED}" if offered else ""
    with db.connect() as conn:
        return conn.execute(
            f"{_VISIBLE}{where} ORDER BY t.created_at DESC, t.id DESC LIMIT %(limit)s",
            _params(org_id, user_id, now, limit=LIST_LIMIT),
        ).fetchall()


def _one(conn, org_id: str, user_id: str, task_id: str, now: datetime | None, lock: bool = False):
    """The visible task the user addresses as `task_id` (`address`)."""
    return conn.execute(
        f"{_VISIBLE} AND {_ADDRESSED}" + (" FOR UPDATE OF t" if lock else ""),
        _params(org_id, user_id, now, id=task_id),
    ).fetchone()


def visible_row(org_id: str, user_id: str, task_id: str, *, now: datetime | None = None) -> dict | None:
    with db.connect() as conn:
        return _one(conn, org_id, user_id, task_id, now)


def _locked(conn, org_id: str, user_id: str, task_id: str, now: datetime | None) -> dict:
    """The task the user may see, locked for a claim or decision. Lock order (module docstring): the user's
    network profile, the task's org, then the user's membership of that org, each FOR SHARE in its own
    statement, then the task FOR UPDATE in a statement whose fresh snapshot sees any switch, removal or
    leave committed while this transaction waited. A row that does not exist is not locked."""
    conn.execute("SELECT 1 FROM network_reviewers WHERE user_id = %s FOR SHARE", (user_id,))
    org = conn.execute(
        "SELECT o.id FROM orgs o JOIN runs r ON r.org_id = o.id JOIN run_tasks t ON t.run_id = r.id "
        f"WHERE {_ADDRESSED} FOR SHARE OF o",
        {"org": org_id, "id": task_id},
    ).fetchone()
    if org is not None:
        conn.execute(
            "SELECT 1 FROM org_members WHERE org_id = %s AND user_id = %s FOR SHARE", (org["id"], user_id)
        )
    row = _one(conn, org_id, user_id, task_id, now, lock=True)
    if row is None:
        raise ApiProblem(404, "NOT_FOUND", f"No task {task_id}.")
    return row


def claim(org_id: str, user_id: str, task_id: str, *, now: datetime | None = None) -> dict:
    """Claim a task the user may see (`run_tasks.apply_claim`). The claim records its route (`claimed_via`)
    and, through the network, the simulated pay. 404 when the task is not visible, 409 when it is decided or
    someone else holds it."""
    with db.connect() as conn:
        row = _locked(conn, org_id, user_id, task_id, now)
        marks: dict = {"claimed_via": row["via"]}
        if row["via"] == "network":
            marks["pay"] = network_pay_minor(row["payload"] or {})
        run_tasks.apply_claim(conn, row, user_id, marks)
        updated = _one(conn, org_id, user_id, task_id, now)
        conn.commit()
    return updated


def decide(
    org_id: str, user_id: str, task_id: str, status: str, result: dict, *, now: datetime | None = None
) -> dict:
    """Record the reviewer's decision on a task they may see (`run_tasks.apply_decision`) and commit."""
    with db.connect() as conn:
        row = _locked(conn, org_id, user_id, task_id, now)
        if run_tasks.apply_decision(conn, row, "human", status, user_id, result):
            row = _one(conn, org_id, user_id, task_id, now)
        conn.commit()
    return row
