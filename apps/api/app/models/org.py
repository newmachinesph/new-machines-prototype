from typing import Literal

from app.models.common import Actor, Model, Money, Opt


class Grant(Model):
    install: str
    capability: str
    access: Literal["read", "write (approval)", "denied"]


class Connection(Model):
    app: str
    account: str
    status: Literal["connected", "not_connected", "sandbox", "needs_reauth"]
    provider: Literal["Composio", "Mock"]
    oauth_scopes: list[str]
    grants: list[Grant]
    last_used: str | Opt = None
    health: str | Opt = None


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
    kind: Literal["plan", "ai_usage", "tool_usage", "human_pay", "refund", "hold"]
    description: str
    run_id: str | Opt = None
    amount: Money
    status: Literal["POSTED", "PENDING", "ELIGIBLE", "HELD"]
    lines: list[LedgerLine]


class McpToken(Model):
    id: str
    name: str
    last4: str
    scopes: list[str]
    created_at: str
    expires_at: str
    last_used: str


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
