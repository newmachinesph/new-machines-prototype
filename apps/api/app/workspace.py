"""The live workspace (NM_WORKSPACE=live with NM_RUNTIME=temporal): each signed-in user works in an org of
their own in Postgres. Membership and provisioning on first sign-in, and the org, members, invitations, API
tokens, usage and attention the organization routes serve. Every query here is scoped to one org (and, for
tokens, one user); nothing reads fixtures."""

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from app import db, run_tasks, settings
from app.errors import ApiProblem
from app.models.common import Money, money_text
from app.models.org import (
    AttentionItem,
    LedgerLine,
    LedgerTxn,
    McpToken,
    Member,
    Organization,
    PendingInvitation,
    Policy,
)
from app.models.requests import CreatedToken
from app.models.runs import Spent
from app.run_tasks import OPEN_STATUSES
from app.runtime.projection import TERMINAL_RUN_STATUSES
from app.store import iso

log = logging.getLogger(__name__)

# Where the database and API run. Model requests go to the model provider and are not pinned to it.
REGION = "asia-south1"
REGION_NAME = "Mumbai"
TOKEN_DAYS = 30
TOKEN_PREFIX = "nm_pat_"
TOKEN_PREFIX_SHOWN = len(TOKEN_PREFIX) + 4  # nm_pat_ plus the first four characters of the random part
LEDGER_LIMIT = 100
FAILED_RUN_DAYS = 7
FAILED_RUN_LIMIT = 10
SPEND_WARN_PERCENT = 80
ROLE_NAMES = {"owner": "Owner", "admin": "Admin", "member": "Member", "reviewer": "Reviewer"}
INVITER_ROLES = frozenset({"owner", "admin"})
_PROVISION_LOCK = "nm-workspace-member:"


def live() -> bool:
    """True when customer routes serve the live workspace. It needs the runtime (Postgres): with NM_RUNTIME
    off the API stays in the demo workspace (see `check_config`)."""
    return settings.workspace_mode() == "live" and settings.runtime_enabled()


def check_config() -> None:
    """Called at startup. NM_WORKSPACE=live needs NM_RUNTIME=temporal: locally a missing runtime is logged
    and sign-in stays in the demo workspace, but on Cloud Run (K_SERVICE set) the boot fails, as it does for
    a live workspace with AUTH_MODE=dev, so a deploy never puts every user in the shared demo org or skips
    sign-in. Any NM_WORKSPACE other than demo or live is refused, so a typo never falls back to the demo."""
    mode = settings.workspace_mode()
    if mode not in ("demo", "live"):
        raise RuntimeError(f"NM_WORKSPACE must be demo or live, not {mode!r}.")
    if mode != "live":
        return
    on_cloud_run = bool(os.environ.get("K_SERVICE"))
    if not settings.runtime_enabled():
        if on_cloud_run:
            raise RuntimeError("NM_WORKSPACE=live needs NM_RUNTIME=temporal.")
        log.error(
            "NM_WORKSPACE=live needs NM_RUNTIME=temporal; customer sign-in stays in the demo workspace."
        )
    if on_cloud_run and os.environ.get("AUTH_MODE") == "dev":
        raise RuntimeError("NM_WORKSPACE=live cannot run with AUTH_MODE=dev on Cloud Run.")


# --- identity and membership ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str | None  # lower-case
    email_verified: bool
    name: str | None


DEV_IDENTITY = Identity(user_id="dev-user", email=None, email_verified=False, name=None)


def identity_from_claims(claims: dict[str, Any]) -> Identity:
    """The user named by verified Firebase ID token claims. Only a real boolean `email_verified` counts."""
    email = claims.get("email")
    name = claims.get("name")
    return Identity(
        user_id=claims["sub"],
        email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
        email_verified=claims.get("email_verified") is True,
        name=name.strip() if isinstance(name, str) and name.strip() else None,
    )


@dataclass(frozen=True)
class Membership:
    org_id: str
    org_name: str
    org_status: str
    role: str


def workspace_name(name: str | None) -> str:
    first = name.split()[0] if name else ""
    return f"{first}'s workspace" if first else "My workspace"


def membership(identity: Identity) -> Membership:
    """The org the user works in. On first sign-in a new org is created with the user as owner; signing in
    never joins another org, even with a pending invitation (the user accepts one with
    `accept_invitation`). A per-user advisory lock makes concurrent requests wait for each other, so they
    find (not create) the same org."""
    with db.connect() as conn:
        found = _active(conn, identity.user_id)
        if found is None:
            _lock_user(conn, identity.user_id)
            found = _active(conn, identity.user_id)
            if found is None:
                _provision(conn, identity)
                found = _active(conn, identity.user_id)
        conn.commit()
    if found is None:  # pragma: no cover - the rows were inserted in this transaction
        raise RuntimeError(f"No membership after provisioning {identity.user_id}.")
    return found


def _lock_user(conn, user_id: str) -> None:
    """Serialise this user's membership changes until the transaction ends."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (_PROVISION_LOCK + user_id,))


def _active(conn, user_id: str) -> Membership | None:
    row = conn.execute(
        "SELECT m.org_id, m.role, o.name, o.status FROM org_members m JOIN orgs o ON o.id = m.org_id "
        "WHERE m.user_id = %s AND m.status = 'active' ORDER BY m.created_at, m.org_id LIMIT 1",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return Membership(org_id=row["org_id"], org_name=row["name"], org_status=row["status"], role=row["role"])


def _provision(conn, identity: Identity) -> None:
    org_id = f"org_{secrets.token_hex(8)}"
    conn.execute("INSERT INTO orgs (id, name) VALUES (%s, %s)", (org_id, workspace_name(identity.name)))
    conn.execute(
        "INSERT INTO org_members (org_id, user_id, email, name, role, status, reviewer) "
        "VALUES (%s, %s, %s, %s, 'owner', 'active', true)",
        (org_id, identity.user_id, identity.email, identity.name),
    )
    log.info("Provisioned %s for user %s.", org_id, identity.user_id)


# --- invitations to the signed-in user -----------------------------------------------------------------


def _require_verified(identity: Identity) -> str:
    if not (identity.email and identity.email_verified):
        raise ApiProblem(403, "EMAIL_UNVERIFIED", "Verify your email address to answer invitations.")
    return identity.email


def _no_invitation() -> ApiProblem:
    return ApiProblem(404, "NOT_FOUND", "There is no pending invitation to this workspace.")


def pending_invitations(identity: Identity, current_org_id: str) -> list[PendingInvitation]:
    """Invitations to active orgs, other than the current one, addressed to the user's verified email,
    oldest first. One query on the partial index `org_members_invited`; none without a verified email."""
    if not (identity.email and identity.email_verified):
        return []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT m.org_id, o.name, m.role, m.created_at FROM org_members m JOIN orgs o ON o.id = m.org_id "
            "WHERE m.email = %s AND m.status = 'invited' AND m.org_id <> %s AND o.status = 'active' "
            "ORDER BY m.created_at, m.org_id",
            (identity.email, current_org_id),
        ).fetchall()
    return [
        PendingInvitation(
            org_id=r["org_id"], org_name=r["name"], role=r["role"], invited_at=iso(r["created_at"])
        )
        for r in rows
    ]


def accept_invitation(identity: Identity, org_id: str) -> Membership:
    """Join the org that invited the user's verified email. Under the per-user advisory lock, the user's
    current membership ends: an empty org is deleted, and any other org keeps its data with the user's row
    marked inactive and their tokens in it revoked. 403 without a verified email, 404 without a pending
    invitation to an active org other than the current one."""
    email = _require_verified(identity)
    with db.connect() as conn:
        _lock_user(conn, identity.user_id)
        current = _active(conn, identity.user_id)
        invited = conn.execute(
            "SELECT m.org_id FROM org_members m JOIN orgs o ON o.id = m.org_id "
            "WHERE m.org_id = %s AND m.email = %s AND m.status = 'invited' AND o.status = 'active' "
            "FOR UPDATE OF m",
            (org_id, email),
        ).fetchone()
        if invited is None or (current is not None and current.org_id == org_id):
            raise _no_invitation()
        if current is not None:
            _leave(conn, identity.user_id, current.org_id)
        # A row left inactive in this org earlier (under another email) would clash with the joined one.
        conn.execute(
            "DELETE FROM org_members WHERE org_id = %s AND user_id = %s AND status = 'inactive'",
            (org_id, identity.user_id),
        )
        conn.execute(
            "UPDATE org_members SET user_id = %s, status = 'active', name = COALESCE(%s, name) "
            "WHERE org_id = %s AND email = %s",
            (identity.user_id, identity.name, org_id, email),
        )
        found = _active(conn, identity.user_id)
        conn.commit()
    if found is None:  # pragma: no cover - the row was activated in this transaction
        raise RuntimeError(f"No membership after {identity.user_id} accepted {org_id}.")
    log.info("User %s accepted an invitation to %s.", identity.user_id, org_id)
    return found


def decline_invitation(identity: Identity, org_id: str) -> None:
    """Delete the pending invitation to this org for the user's verified email; 403 without a verified
    email, 404 without such an invitation."""
    email = _require_verified(identity)
    with db.connect() as conn:
        row = conn.execute(
            "DELETE FROM org_members WHERE org_id = %s AND email = %s AND status = 'invited' "
            "RETURNING org_id",
            (org_id, email),
        ).fetchone()
        conn.commit()
    if row is None:
        raise _no_invitation()
    log.info("User %s declined an invitation to %s.", identity.user_id, org_id)


def _is_empty(conn, org_id: str, user_id: str) -> bool:
    """No one else in the org (member, invited or former), and no hired packs, app connections or runs."""
    row = conn.execute(
        "SELECT NOT EXISTS (SELECT 1 FROM org_members WHERE org_id = %(org)s "
        "  AND user_id IS DISTINCT FROM %(user)s)"
        " AND NOT EXISTS (SELECT 1 FROM installations WHERE org_id = %(org)s)"
        " AND NOT EXISTS (SELECT 1 FROM connections WHERE org_id = %(org)s)"
        " AND NOT EXISTS (SELECT 1 FROM runs WHERE org_id = %(org)s) AS empty",
        {"org": org_id, "user": user_id},
    ).fetchone()
    return bool(row["empty"])


def _leave(conn, user_id: str, org_id: str) -> None:
    """End the user's membership of `org_id`. An empty org is deleted with the user's row and tokens, in a
    savepoint after locking the org row and checking again; if anything still refers to it, or it is not
    empty, the org keeps its data, the user's row becomes inactive, their tokens in it are revoked and the
    org's open human tasks they had claimed return to the queue."""
    if _is_empty(conn, org_id, user_id):
        try:
            with conn.transaction():
                conn.execute("SELECT id FROM orgs WHERE id = %s FOR UPDATE", (org_id,))
                if _is_empty(conn, org_id, user_id):
                    conn.execute("DELETE FROM api_tokens WHERE org_id = %s", (org_id,))
                    # Only the user's own row: any other member row keeps its foreign key, rolling back.
                    conn.execute(
                        "DELETE FROM org_members WHERE org_id = %s AND user_id = %s", (org_id, user_id)
                    )
                    conn.execute("DELETE FROM orgs WHERE id = %s", (org_id,))
                    log.info("User %s left and deleted the empty %s.", user_id, org_id)
                    return
        except psycopg.errors.IntegrityError:
            log.warning("%s could not be deleted when user %s left it; it is kept.", org_id, user_id)
    conn.execute(
        "UPDATE org_members SET status = 'inactive' WHERE org_id = %s AND user_id = %s", (org_id, user_id)
    )
    conn.execute(
        "UPDATE api_tokens SET revoked_at = now() WHERE org_id = %s AND user_id = %s AND revoked_at IS NULL",
        (org_id, user_id),
    )
    run_tasks.release_claims(conn, org_id=org_id, user_id=user_id)
    log.info("User %s left %s, which keeps its data.", user_id, org_id)


# --- org, policies, members ----------------------------------------------------------------------------


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(month_start: datetime) -> datetime:
    return (month_start + timedelta(days=32)).replace(day=1)


def _part(name: str) -> str:
    return f"COALESCE((projection #>> '{{spent,{name},amountMinor}}')::bigint, 0)"


_AI, _TOOLS, _HUMAN = _part("ai"), _part("tools"), _part("human")
# A run's spend (AI, tools and human review) read from its projection, as SQL over the `runs` table.
RUN_SPENT_SQL = f"({_AI} + {_TOOLS} + {_HUMAN})"
RUN_AI_SPENT_SQL = _AI  # the AI part alone


def _org_row(conn, org_id: str) -> dict:
    row = conn.execute(
        "SELECT id, name, plan, monthly_cap_minor, created_at FROM orgs WHERE id = %s", (org_id,)
    ).fetchone()
    if row is None:
        raise ApiProblem(404, "NOT_FOUND", "This workspace no longer exists.")
    return row


def month_spent_by_org(conn, *, now: datetime | None = None, org_id: str | None = None) -> dict[str, int]:
    """{org id: what its runs spent this calendar month (UTC), in minor units} in one query, for every org
    with runs this month (or only `org_id`). The one definition of a month's spend: the customer app and
    the operator console both read it."""
    start = _month_start(now)
    rows = conn.execute(
        f"SELECT org_id, SUM({RUN_SPENT_SQL}) AS spent FROM runs "
        "WHERE created_at >= %(since)s AND created_at < %(until)s "
        "AND (%(org)s::text IS NULL OR org_id = %(org)s) GROUP BY org_id",
        {"since": start, "until": _next_month(start), "org": org_id},
    ).fetchall()
    return {r["org_id"]: int(r["spent"]) for r in rows}


def month_spent(conn, org_id: str) -> int:
    """What the org's runs spent this calendar month (UTC), in minor units (`month_spent_by_org`)."""
    return month_spent_by_org(conn, org_id=org_id).get(org_id, 0)


def _organization(conn, org_id: str) -> Organization:
    row = _org_row(conn, org_id)
    return Organization(
        id=row["id"],
        name=row["name"],
        short=row["name"],
        plan=str(row["plan"]).capitalize(),
        monthly_cap=Money(amount_minor=int(row["monthly_cap_minor"])),
        month_spent=Money(amount_minor=month_spent(conn, org_id)),
        region=REGION,
    )


def organization(org_id: str) -> Organization:
    with db.connect() as conn:
        return _organization(conn, org_id)


# The rules every live workspace starts with; they describe what the runtime enforces.
DEFAULT_POLICIES = (
    Policy(
        ref="tool_actions@1",
        summary="Every tool call is checked first. Reads are permitted, writes and money movements wait for "
        "your approval, and an action the policy does not know is denied.",
        updated="",
    ),
    Policy(
        ref="human_review@1",
        summary="Work a pack sends for review is checked by a person before it is accepted.",
        updated="",
    ),
    Policy(
        ref="spend_cap@1",
        summary="New runs do not start once this month's spend reaches the workspace's monthly cap.",
        updated="",
    ),
    Policy(
        ref="region@1",
        summary=f"Customer data is stored and processed in {REGION} ({REGION_NAME}). AI model requests are "
        "sent to the model provider and are not pinned to a region.",
        updated="",
    ),
)


def policies(org_id: str) -> list[Policy]:
    """The built-in defaults, dated when the workspace was created."""
    with db.connect() as conn:
        created = _org_row(conn, org_id)["created_at"].astimezone(UTC)
    when = f"{created:%b} {created.day}"
    return [p.model_copy(update={"updated": when}) for p in DEFAULT_POLICIES]


def _member(row: dict) -> Member:
    invited = row["status"] == "invited"
    return Member(
        name=row["name"] or row["email"] or "Member",
        email=row["email"] or "",
        role=ROLE_NAMES[row["role"]],
        via="Invite link" if invited else "Signed in",
        pending=True if invited else None,
    )


def org_members(conn, org_id: str) -> list[Member]:
    """Active members, then pending invitations, each oldest first."""
    rows = conn.execute(
        "SELECT email, name, role, status FROM org_members WHERE org_id = %s AND status <> 'inactive' "
        "ORDER BY status = 'invited', created_at, email",
        (org_id,),
    ).fetchall()
    return [_member(r) for r in rows]


def members(org_id: str) -> list[Member]:
    """Active members, then pending invitations, each oldest first."""
    with db.connect() as conn:
        return org_members(conn, org_id)


def invite(org_id: str, inviter_role: str, email: str, role: str) -> Member:
    """Add a pending member. Owners and admins invite; an email already in the org (member or invited) is a
    409, while a former member (inactive) can be invited again, without a reviewer capability they had unless
    the invitation is for a Reviewer."""
    if inviter_role not in INVITER_ROLES:
        raise ApiProblem(403, "POLICY_DENIED", "Only owners and admins can invite people.")
    with db.connect() as conn:
        row = conn.execute(
            "INSERT INTO org_members (org_id, email, role, status) VALUES (%s, %s, %s, 'invited') "
            "ON CONFLICT (org_id, email) DO UPDATE SET user_id = NULL, role = EXCLUDED.role, "
            "status = 'invited', reviewer = (EXCLUDED.role = 'reviewer'), created_at = now() "
            "WHERE org_members.status = 'inactive' RETURNING email, name, role, status",
            (org_id, email.strip().lower(), role.lower()),
        ).fetchone()
        conn.commit()
    if row is None:
        raise ApiProblem(409, "CONFLICT", "This person is already in the workspace or invited.")
    return _member(row)


# --- API tokens ----------------------------------------------------------------------------------------


def _token(row: dict) -> McpToken:
    return McpToken(
        id=row["id"],
        name=row["name"],
        last4=row["last4"],
        prefix=row["prefix"],
        scopes=list(row["scopes"]),
        created_at=iso(row["created_at"]),
        expires_at=iso(row["expires_at"]),
        last_used="",
    )


_TOKEN_COLUMNS = "id, name, prefix, last4, scopes, created_at, expires_at"


def tokens(org_id: str, user_id: str) -> list[McpToken]:
    """The user's tokens in this org that are neither revoked nor expired, newest first. Secrets are never
    returned."""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT {_TOKEN_COLUMNS} FROM api_tokens "
            "WHERE org_id = %s AND user_id = %s AND revoked_at IS NULL AND expires_at > now() "
            "ORDER BY created_at DESC, id DESC",
            (org_id, user_id),
        ).fetchall()
    return [_token(r) for r in rows]


def create_token(org_id: str, user_id: str, name: str, scopes: list[str]) -> CreatedToken:
    """Mint a token. The secret is in this response only; the database keeps its SHA-256 hash."""
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    created = datetime.now(UTC).replace(microsecond=0)
    with db.connect() as conn:
        row = conn.execute(
            "INSERT INTO api_tokens (id, org_id, user_id, name, prefix, last4, secret_hash, scopes, "
            "created_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {_TOKEN_COLUMNS}",
            (
                f"pat_{secrets.token_hex(6)}",
                org_id,
                user_id,
                name,
                secret[:TOKEN_PREFIX_SHOWN],
                secret[-4:],
                hashlib.sha256(secret.encode("utf-8")).hexdigest(),
                list(scopes),
                created,
                created + timedelta(days=TOKEN_DAYS),
            ),
        ).fetchone()
        conn.commit()
    return CreatedToken(token=_token(row), secret=secret)


def revoke_token(org_id: str, user_id: str, token_id: str) -> None:
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE api_tokens SET revoked_at = now() "
            "WHERE id = %s AND org_id = %s AND user_id = %s AND revoked_at IS NULL RETURNING id",
            (token_id, org_id, user_id),
        ).fetchone()
        conn.commit()
    if row is None:
        raise ApiProblem(404, "NOT_FOUND", f"No token {token_id}.")


# --- usage and attention -------------------------------------------------------------------------------


def _ledger_txn(row: dict) -> LedgerTxn:
    ai, tools, human = int(row["ai"]), int(row["tools"]), int(row["human"])
    return LedgerTxn(
        id=f"txn_{row['id']}",
        at=iso(row["created_at"]),
        kind="run",
        description=row["title"] or row["pack_slug"],
        run_id=row["id"],
        amount=Money(amount_minor=ai + tools + human),
        status="POSTED" if row["status"] in TERMINAL_RUN_STATUSES else "PENDING",
        lines=[
            LedgerLine(account="AI usage", debit=ai),
            LedgerLine(account="Tool usage", debit=tools),
            LedgerLine(account="Human review", debit=human),
        ],
        spent=Spent(
            ai=Money(amount_minor=ai), tools=Money(amount_minor=tools), human=Money(amount_minor=human)
        ),
    )


def usage(org_id: str) -> tuple[Organization, list[LedgerTxn]]:
    """The org (cap and this month's spend) and one ledger line per run, newest first."""
    with db.connect() as conn:
        org = _organization(conn, org_id)
        rows = conn.execute(
            f"SELECT id, pack_slug, status, created_at, projection ->> 'title' AS title, {_AI} AS ai, "
            f"{_TOOLS} AS tools, {_HUMAN} AS human FROM runs WHERE org_id = %s "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (org_id, LEDGER_LIMIT),
        ).fetchall()
    return org, [_ledger_txn(r) for r in rows]


def _open_tasks(conn, org_id: str, kind: str) -> dict | None:
    """The newest open task of this kind with how many are open (`n`); None when none are."""
    return conn.execute(
        "SELECT t.payload ->> 'title' AS title, t.created_at, count(*) OVER () AS n "
        "FROM run_tasks t JOIN runs r ON r.id = t.run_id "
        "WHERE r.org_id = %s AND t.kind = %s AND t.status = %s "
        "ORDER BY t.created_at DESC, t.id DESC LIMIT 1",
        (org_id, kind, OPEN_STATUSES[kind]),
    ).fetchone()


def _task_item(newest: dict | None, actor: str, one: str, many: str, href: str) -> list[AttentionItem]:
    if newest is None:
        return []
    n = int(newest["n"])
    return [
        AttentionItem(
            actor=actor,
            title=one if n == 1 else many.format(n=n),
            detail=newest["title"] or "",
            href=href,
            when=iso(newest["created_at"]),
        )
    ]


def _failed_runs(conn, org_id: str) -> list[AttentionItem]:
    rows = conn.execute(
        "SELECT id, projection ->> 'title' AS title, projection ->> 'summary' AS summary, updated_at "
        "FROM runs WHERE org_id = %s AND status = 'FAILED' AND updated_at >= %s "
        "ORDER BY updated_at DESC, id DESC LIMIT %s",
        (org_id, datetime.now(UTC) - timedelta(days=FAILED_RUN_DAYS), FAILED_RUN_LIMIT),
    ).fetchall()
    return [
        AttentionItem(
            actor="system",
            title=f"{r['title'] or 'A run'} failed",
            detail=r["summary"] or "The run stopped before it finished.",
            href=f"/app/runs/{r['id']}",
            when=iso(r["updated_at"]),
        )
        for r in rows
    ]


def _spend_item(org: Organization) -> list[AttentionItem]:
    cap, spent = org.monthly_cap.amount_minor, org.month_spent.amount_minor
    if cap <= 0 or spent * 100 < cap * SPEND_WARN_PERCENT:
        return []
    percent = spent * 100 // cap
    return [
        AttentionItem(
            actor="policy",
            title=f"{percent}% of this month's cap is spent",
            detail=f"{money_text(spent)} of {money_text(cap)}. New runs stop at the cap.",
            href="/app/usage",
            when=iso(datetime.now(UTC)),
        )
    ]


def attention(org_id: str) -> list[AttentionItem]:
    """Pending approvals, open human tasks, runs failed in the last week and spend at 80% of the cap or
    more, newest first."""
    with db.connect() as conn:
        org = _organization(conn, org_id)
        approvals = _open_tasks(conn, org_id, "approval")
        tasks = _open_tasks(conn, org_id, "human")
        failed = _failed_runs(conn, org_id)
    items = [
        *_task_item(approvals, "buyer", "Approve one action", "Approve {n} actions", "/app/approvals"),
        *_task_item(tasks, "human", "One review task is open", "{n} review tasks are open", "/work"),
        *failed,
        *_spend_item(org),
    ]
    return sorted(items, key=lambda item: item.when, reverse=True)
