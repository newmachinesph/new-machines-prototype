from typing import Literal

from app.models.common import Actor, Model, Money, Opt, RequestModel
from app.models.runs import Spent


class Grant(Model):
    install: str
    capability: str
    access: Literal["read", "write (approval)", "write", "denied"]


class RevokedGrant(Model):
    """A grant a person revoked on a connection (`DELETE /v1/grants`): recomputing the connection's grants
    never brings it back until it is allowed again (`POST /v1/grants`)."""

    install: str
    capability: str


class Connection(Model):
    app: str
    account: str
    status: Literal["connected", "not_connected", "sandbox", "needs_reauth", "pending"]
    provider: Literal["Composio", "Mock"]
    oauth_scopes: list[str]
    grants: list[Grant]
    # Live workspace: what a person revoked on this connection, whatever its status, so the web can offer to
    # allow each one again. Always empty in the demo.
    revoked: list[RevokedGrant] = []
    last_used: str | Opt = None
    health: str | Opt = None
    # Live workspace: the connector definition key (what `:connect` takes) and how the app is reached
    # (sandbox data, or the customer's own account through Composio).
    key: str | Opt = None
    mode: Literal["sandbox", "composio"] | Opt = None
    # Live workspace: set when an action half-succeeded. "sign_in_not_removed": disconnected here, but the
    # account could not be removed at Composio yet (the next connect or disconnect retries).
    notice: Literal["sign_in_not_removed"] | Opt = None


class ConnectRequest(RequestModel):
    """How to connect an app: `live` signs in to the org's own account; `sandbox` serves sandbox data."""

    mode: Literal["live", "sandbox"] = "sandbox"


class ConnectStarted(Connection):
    """A connection just made or started. `redirect_url` (live only) is the app's sign-in page, which returns
    to the web's Connections page with `?connected=<key>`."""

    redirect_url: str | Opt = None


class MemoryItem(Model):
    id: str
    text: str
    scope: Literal["Organization", "Department", "Agent installation", "User", "Task"]
    scope_name: str
    state: Literal["CANDIDATE", "APPROVED", "CORRECTED", "REJECTED", "EXPIRED", "CONTRADICTION"]
    source: str
    source_run: str | Opt = None
    proposed_by: str
    created_at: str
    used_in: int | Opt = None
    conflicts_with: str | Opt = None
    retracted: bool | Opt = None


class LedgerLine(Model):
    account: str
    debit: int | Opt = None
    credit: int | Opt = None


class LedgerTxn(Model):
    id: str
    at: str
    # "run": the live workspace's one line per run, with that run's spend split in `spent`.
    kind: Literal["plan", "ai_usage", "tool_usage", "human_pay", "refund", "hold", "run"]
    description: str
    run_id: str | Opt = None
    amount: Money
    status: Literal["POSTED", "PENDING", "ELIGIBLE", "HELD"]
    lines: list[LedgerLine]
    spent: Spent | Opt = None


class McpToken(Model):
    id: str
    name: str
    last4: str
    scopes: list[str]
    created_at: str
    expires_at: str
    last_used: str
    # The secret's first characters (live workspace), so a token can be recognised without its secret.
    prefix: str | Opt = None


class Member(Model):
    name: str
    email: str
    role: str
    via: str
    pending: bool | Opt = None


class Policy(Model):
    ref: str
    summary: str
    updated: str


class Organization(Model):
    id: str
    name: str
    short: str
    plan: str
    monthly_cap: Money
    month_spent: Money
    region: str


class AttentionItem(Model):
    actor: Actor
    title: str
    detail: str
    href: str
    when: str


MemberRole = Literal["owner", "admin", "member", "reviewer"]


class PendingInvitation(Model):
    """An invitation to another workspace, waiting for the user to accept or decline it."""

    org_id: str
    org_name: str
    role: MemberRole
    invited_at: str


class Me(Model):
    """The signed-in user and the workspace they act in."""

    user_id: str
    email: str | Opt = None
    name: str | Opt = None
    org_id: str
    org_name: str
    role: MemberRole
    # "live": the user's own org on Postgres; "demo": the seeded sample workspace.
    workspace: Literal["demo", "live"] = "demo"
    # Live workspace, verified email only: invitations to the user's email. Always empty in the demo.
    invitations: list[PendingInvitation] = []
