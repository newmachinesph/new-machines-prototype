"""The org's own reviewers (live workspace): members with the reviewer capability, Reviewer invitations, and
the org's switch for the New Machines reviewer network. Every query is scoped to one org; owners and admins
make every change."""

from app import db, run_tasks, workspace
from app.errors import ApiProblem
from app.models.workforce import OrgReviewer, OrgReviewers

_COLUMNS = "email, name, role, status"


def _require_manager(role: str) -> None:
    if role not in workspace.INVITER_ROLES:
        raise ApiProblem(403, "POLICY_DENIED", "Only owners and admins can change reviewers.")


def _reviewer(row: dict) -> OrgReviewer:
    return OrgReviewer(
        email=row["email"] or "",
        name=row["name"] or row["email"] or "Reviewer",
        role=row["role"],
        pending=row["status"] == "invited",
    )


def _list(conn, org_id: str) -> OrgReviewers:
    org = conn.execute("SELECT allow_network FROM orgs WHERE id = %s", (org_id,)).fetchone()
    if org is None:
        raise ApiProblem(404, "NOT_FOUND", "This workspace no longer exists.")
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM org_members WHERE org_id = %s AND reviewer "
        "AND status IN ('active', 'invited') ORDER BY status = 'invited', created_at, email",
        (org_id,),
    ).fetchall()
    return OrgReviewers(allow_network=bool(org["allow_network"]), reviewers=[_reviewer(r) for r in rows])


def reviewers(org_id: str) -> OrgReviewers:
    """Members with the reviewer capability, then pending invitations that carry it, each oldest first."""
    with db.connect() as conn:
        return _list(conn, org_id)


def add(org_id: str, actor_role: str, email: str) -> OrgReviewer:
    """Give a member (or a pending invitation) the reviewer capability; invite anyone else with role Reviewer.
    The invitation is accepted explicitly, as every invitation. 409 when the person already reviews here."""
    _require_manager(actor_role)
    address = email.strip().lower()
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE org_members SET reviewer = true WHERE org_id = %s AND email = %s "
            f"AND status IN ('active', 'invited') AND NOT reviewer RETURNING {_COLUMNS}",
            (org_id, address),
        ).fetchone()
        if row is None:
            # A new invitation, or a former member's row invited again; nothing for anyone already here.
            row = conn.execute(
                "INSERT INTO org_members (org_id, email, role, status, reviewer) "
                "VALUES (%s, %s, 'reviewer', 'invited', true) "
                "ON CONFLICT (org_id, email) DO UPDATE SET user_id = NULL, role = 'reviewer', "
                "status = 'invited', reviewer = true, created_at = now() "
                f"WHERE org_members.status = 'inactive' RETURNING {_COLUMNS}",
                (org_id, address),
            ).fetchone()
        conn.commit()
    if row is None:
        raise ApiProblem(409, "CONFLICT", "This person already reviews for this workspace.")
    return _reviewer(row)


def remove(org_id: str, actor_role: str, email: str) -> None:
    """Remove a reviewer. A pending Reviewer invitation is withdrawn. A Reviewer member leaves the org
    (inactive, tokens revoked) and gets an org of their own on their next request. Anyone else keeps their
    membership without the capability. Open tasks they claimed in this org go back to the queue."""
    _require_manager(actor_role)
    address = email.strip().lower()
    with db.connect() as conn:
        # The membership row first, then its tasks: the lock order of `app.review_routing`.
        row = conn.execute(
            "SELECT user_id, role, status FROM org_members WHERE org_id = %s AND email = %s AND reviewer "
            "AND status IN ('active', 'invited') FOR UPDATE",
            (org_id, address),
        ).fetchone()
        if row is None:
            raise ApiProblem(404, "NOT_FOUND", "This person is not a reviewer in this workspace.")
        where = (org_id, address)
        if row["role"] != "reviewer":
            conn.execute("UPDATE org_members SET reviewer = false WHERE org_id = %s AND email = %s", where)
        elif row["status"] == "invited":
            conn.execute("DELETE FROM org_members WHERE org_id = %s AND email = %s", where)
        else:
            conn.execute(
                "UPDATE org_members SET status = 'inactive', reviewer = false "
                "WHERE org_id = %s AND email = %s",
                where,
            )
            conn.execute(
                "UPDATE api_tokens SET revoked_at = now() "
                "WHERE org_id = %s AND user_id = %s AND revoked_at IS NULL",
                (org_id, row["user_id"]),
            )
        if row["user_id"] is not None:
            run_tasks.release_claims(conn, org_id=org_id, user_id=row["user_id"])
        conn.commit()


def set_network(org_id: str, actor_role: str, allow: bool) -> OrgReviewers:
    """Allow or stop the New Machines reviewer network for the org's tasks. Turning it off returns the open
    tasks network reviewers claimed to the queue, so the team gets them back."""
    _require_manager(actor_role)
    with db.connect() as conn:
        # The org row first, then its tasks: the lock order of `app.review_routing`.
        conn.execute("UPDATE orgs SET allow_network = %s WHERE id = %s", (allow, org_id))
        if not allow:
            run_tasks.release_claims(conn, org_id=org_id, via="network")
        result = _list(conn, org_id)
        conn.commit()
    return result
