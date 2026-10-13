"""Operator console ("ops") wire models: responses and request bodies for everything under /v1/ops."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from app.models.catalog import Pack, TaxonomyEntry
from app.models.common import Model, Money, Opt, RequestModel
from app.models.org import Connection, Member
from app.models.runs import Receipt, Run, RunStatus, RunSummary

OpsRole = Literal["owner", "admin", "support"]
TenantPlan = Literal["Starter", "Pro", "Enterprise"]
TenantStatus = Literal["active", "trial", "suspended", "churned"]
TenantHealth = Literal["healthy", "watch", "at_risk"]
AuditTargetType = Literal[
    "tenant", "pack", "connector", "reviewer", "guardrail", "incident", "definition", "memory"
]

# Every ops mutation names why it was made; surrounding whitespace is dropped before the length check.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
MAX_CAP_MINOR = 10_000_000


# Operators ---------------------------------------------------------------------------------------------


class OpsMe(Model):
    user_id: str
    email: str
    role: OpsRole


class OpsTeamMember(Model):
    email: str
    name: str
    role: OpsRole
    last_active_at: str
    mfa: bool


class AuditEntry(Model):
    id: str
    at: str
    actor_email: str
    actor_role: OpsRole
    action: str  # "<target type>.<verb>", for example "tenant.suspend"
    target_type: AuditTargetType
    target_id: str
    reason: str
    summary: str  # the before/after, for example "Status active → suspended"


# Runs across tenants -----------------------------------------------------------------------------------


class OpsRun(Model):
    id: str
    tenant_id: str
    tenant_name: str
    pack: str  # the pack slug, so the console can link to /packs/{slug}
    status: RunStatus
    started_at: str
    cost: Money
    waiting_on: Literal["human", "approval", "policy"] | Opt = None
    duration_seconds: int | Opt = None
    real: bool = False  # run by the runtime (has a projection and a receipt at /v1/ops/runs/{id})

    @classmethod
    def of(cls, run: RunSummary, tenant_id: str, tenant_name: str) -> OpsRun:
        """A customer run as the console sees it: one total cost, and the duration once it has ended."""
        duration = None
        if run.ended_at:
            duration = int((_parse(run.ended_at) - _parse(run.started_at)).total_seconds())
        return cls(
            id=run.id,
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            pack=run.pack_slug,
            status=run.status,
            started_at=run.started_at,
            cost=Money(
                amount_minor=sum(m.amount_minor for m in (run.spent.ai, run.spent.human, run.spent.tools))
            ),
            waiting_on="human" if run.status == "WAITING_FOR_HUMAN" else None,
            duration_seconds=duration,
        )


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


# Tenants -----------------------------------------------------------------------------------------------


class Tenant(Model):
    id: str
    name: str
    short: str
    plan: TenantPlan
    status: TenantStatus
    region: str
    country: str
    owner_email: str
    seats: int
    members: int
    created_at: str
    monthly_cap: Money
    month_spent: Money
    runs30d: int = Field(alias="runs30d")
    success_rate: float = Field(ge=0, le=1)
    open_human_tasks: int
    packs_installed: int
    connectors: int
    health: TenantHealth
    notes: str
    trial_ends_at: str | Opt = None
    suspended_reason: str | Opt = None


class TenantConnection(Model):
    app: str
    status: Literal["connected", "not_connected", "sandbox", "needs_reauth"]

    @classmethod
    def of(cls, connection: Connection) -> TenantConnection:
        return cls(app=connection.app, status=connection.status)


class UsagePoint(Model):
    day: str  # YYYY-MM-DD
    amount_minor: int


class TenantDetail(Tenant):
    members_list: list[Member]
    installed_packs: list[str]  # pack slugs
    connectors_list: list[TenantConnection]
    recent_runs: list[OpsRun]
    usage_by_day: list[UsagePoint]
    simulated: Literal[True]  # usageByDay is simulated


class TenantSeedDetail(Model):
    """The detail lists for a seeded tenant other than the demo one, whose lists come from the live store."""

    members_list: list[Member]
    installed_packs: list[str]
    connectors_list: list[TenantConnection]


class TenantSeed(Tenant):
    """Fixture shape only: a tenant plus its seeded detail lists."""

    detail: TenantSeedDetail | Opt = None


# Requests ----------------------------------------------------------------------------------------------


class ReasonRequest(RequestModel):
    reason: Reason


class CreateTenantRequest(RequestModel):
    name: Name
    short: ShortText
    plan: TenantPlan
    region: ShortText
    country: str = Field(pattern=r"^[A-Z]{2}$")
    owner_email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=254)
    monthly_cap_minor: int = Field(ge=0, le=MAX_CAP_MINOR)
    trial_days: int | Opt = Field(default=None, ge=1, le=90)
    reason: Reason


class SetPlanRequest(RequestModel):
    plan: TenantPlan
    reason: Reason


class SetSpendCapRequest(RequestModel):
    monthly_cap_minor: int = Field(ge=0, le=MAX_CAP_MINOR)
    reason: Reason


# Marketplace listings ----------------------------------------------------------------------------------

PackStatus = Literal["draft", "in_review", "published", "deprecated", "rejected"]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", min_length=1, max_length=60)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class PackListing(Model):
    slug: str
    name: str
    version: str
    publisher: str
    category: str
    status: PackStatus
    risk_class: Literal["low", "medium", "high"]
    certified: bool
    installs: int
    runs30d: int = Field(alias="runs30d")
    success_rate: float = Field(ge=0, le=1)
    price_note: str
    submitted_at: str | Opt = None
    updated_at: str
    connectors: list[str]  # app names
    review_notes: str | Opt = None
    # From the pack definition, named from the taxonomy (none for listings without a pack definition).
    function: TaxonomyEntry | Opt = None
    industries: list[TaxonomyEntry] = Field(default_factory=list)


class PackHistoryEntry(Model):
    at: str
    by: str
    action: str
    note: str


class PackListingDetail(PackListing):
    pack: Pack
    history: list[PackHistoryEntry]


class PackListingSeed(PackListing):
    """Fixture shape only. A seeded pack not in `packs.json` carries its full customer `Pack` here."""

    history: list[PackHistoryEntry]
    pack: Pack | Opt = None


class PackConnectorInput(RequestModel):
    app: ShortText
    access: Literal["read", "write (approval)", "write"]


class CreatePackRequest(RequestModel):
    name: Name
    slug: Slug
    publisher: Name
    category: ShortText
    outcome: Text
    description: Text
    risk_class: Literal["low", "medium", "high"]
    connectors: list[PackConnectorInput] = Field(max_length=20)
    human_review: Text
    reason: Reason


# Connector catalog -------------------------------------------------------------------------------------

Decision = Literal["permit", "require_approval", "deny"]
ConnectorProvider = Literal["Composio", "Native", "Mock"]
ConnectorAuth = Literal["oauth_managed", "oauth_own_app", "api_key"]
ConnectorStatus = Literal["enabled", "beta", "disabled"]


class ConnectorDefaults(Model):
    read: Decision
    write: Decision
    delete: Decision
    money: Decision


class HealthCheck(Model):
    at: str
    ok: bool
    latency_ms: int
    note: str | Opt = None


class ConnectorEntry(Model):
    id: str
    app: str
    category: str
    provider: ConnectorProvider
    auth_type: ConnectorAuth
    status: ConnectorStatus
    tenants_connected: int
    calls_today: int
    error_rate: float = Field(ge=0, le=1)
    last_health_check: HealthCheck
    defaults: ConnectorDefaults
    scopes: list[str]


class Toolkit(Model):
    """A Composio toolkit that can be added to the catalog (simulated discovery)."""

    slug: str
    name: str
    category: str
    auth_type: ConnectorAuth


class AddConnectorRequest(RequestModel):
    toolkit_slug: Slug
    status: Literal["enabled", "beta"]
    reason: Reason


class ConnectorDefaultsInput(RequestModel):
    read: Decision
    write: Decision
    delete: Decision
    money: Decision


class SetDefaultsRequest(RequestModel):
    defaults: ConnectorDefaultsInput
    reason: Reason


# Workforce ---------------------------------------------------------------------------------------------

ReviewerLevel = Literal["trainee", "qualified", "senior"]
ReviewerStatus = Literal["applicant", "active", "suspended"]


class Reviewer(Model):
    id: str
    name: str
    email: str
    country: str
    languages: list[str]
    skills: list[str]
    level: ReviewerLevel
    status: ReviewerStatus
    tasks_done30d: int = Field(alias="tasksDone30d")
    accuracy: float = Field(ge=0, le=1)
    median_minutes: int
    earnings30d: Money = Field(alias="earnings30d")
    joined_at: str
    queue: int


class SetLevelRequest(RequestModel):
    level: ReviewerLevel
    reason: Reason


# Guardrails --------------------------------------------------------------------------------------------

GuardrailKind = Literal["kill_switch", "flag", "limit"]
GUARDRAIL_MAX_VALUE = 10_000_000


class Guardrail(Model):
    key: str
    kind: GuardrailKind
    label: str
    description: str
    enabled: bool
    value: int | Opt = None
    unit: str | Opt = None
    updated_at: str
    updated_by: str
    scope: Literal["platform"] = "platform"


class SetGuardrailRequest(RequestModel):
    enabled: bool | Opt = None
    value: int | Opt = Field(default=None, ge=0, le=GUARDRAIL_MAX_VALUE)
    reason: Reason

    @model_validator(mode="after")
    def _sets_something(self) -> SetGuardrailRequest:
        if self.enabled is None and self.value is None:
            raise ValueError("Set at least one of enabled or value.")
        return self


# Billing (simulated) -----------------------------------------------------------------------------------


class Invoice(Model):
    id: str
    tenant_id: str
    tenant_name: str
    period: str
    amount: Money
    status: Literal["paid", "open", "overdue", "void"]


class Payout(Model):
    id: str
    reviewer_id: str
    reviewer_name: str
    amount: Money
    status: Literal["scheduled", "paid", "held"]


class BillingSummary(Model):
    mrr: Money
    arr: Money
    ai_cost_month: Money
    gross_margin: float = Field(ge=0, le=1)
    reviewer_payouts_month: Money
    invoices: list[Invoice]
    payouts: list[Payout]
    simulated: Literal[True] = True


# Health and incidents (simulated) ----------------------------------------------------------------------

ServiceState = Literal["operational", "degraded", "outage"]
IncidentSeverity = Literal["sev1", "sev2", "sev3"]
IncidentStatus = Literal["investigating", "monitoring", "resolved"]


class ServiceStatus(Model):
    key: str
    name: str
    status: ServiceState
    latency_p95_ms: int
    uptime30d: float = Field(alias="uptime30d", ge=0, le=1)
    note: str | Opt = None


class IncidentUpdate(Model):
    at: str
    by: str
    text: str


class Incident(Model):
    id: str
    title: str
    severity: IncidentSeverity
    status: IncidentStatus
    started_at: str
    resolved_at: str | Opt = None
    services: list[str]
    updates: list[IncidentUpdate]


class OpsHealth(Model):
    services: list[ServiceStatus]
    incidents: list[Incident]
    simulated: Literal[True] = True


class DeclareIncidentRequest(RequestModel):
    title: Name
    severity: IncidentSeverity
    services: list[ShortText] = Field(min_length=1, max_length=10)
    reason: Reason


class UpdateIncidentRequest(RequestModel):
    status: IncidentStatus
    text: Text
    reason: Reason


# Overview ----------------------------------------------------------------------------------------------

AttentionKind = Literal[
    "pack_review", "reviewer_application", "connector_error", "tenant_cap", "incident", "tenant_at_risk"
]
AttentionSeverity = Literal["info", "warn", "critical"]


class OpsAttentionItem(Model):
    kind: AttentionKind
    title: str
    detail: str
    href: str
    severity: AttentionSeverity
    at: str


class OpsKpis(Model):
    active_tenants: int
    trial_tenants: int
    runs_today: int
    run_success_rate7d: float = Field(alias="runSuccessRate7d", ge=0, le=1)
    open_human_tasks: int
    pending_approvals: int
    ai_spend_today: Money
    platform_daily_cap: Money
    incidents_open: int


class HourPoint(Model):
    hour: int = Field(ge=0, le=23)
    completed: int
    failed: int
    waiting: int


class OpsOverview(Model):
    kpis: OpsKpis
    attention: list[OpsAttentionItem]
    recent_audit: list[AuditEntry]
    runs_by_hour: list[HourPoint]
    simulated_fields: list[str]  # the kpis and series that are simulated, not derived from the store


# Definitions (config as code) --------------------------------------------------------------------------

DefinitionKind = Literal[
    "taxonomy", "models", "pack", "workflow", "contract", "agent", "connector", "decision_rules",
    "memory_space", "schema",
]  # fmt: skip
DefinitionSource = Literal["file", "console"]
MAX_DEFINITION_TEXT = 64 * 1024  # characters, for the main file and for each extra file
DefinitionText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_DEFINITION_TEXT)]
DefinitionFileText = Annotated[str, StringConstraints(max_length=MAX_DEFINITION_TEXT)]


class DefinitionRef(Model):
    """A pointer to another definition: its kind and key."""

    kind: DefinitionKind
    key: str


class DefinitionSummary(Model):
    """The latest (or a chosen) version of one definition. `name` is the body's name, else its app
    (connector) or question (decision rules), else the key."""

    kind: DefinitionKind
    key: str
    name: str
    version: int
    digest: str
    source: DefinitionSource
    published_by: str
    published_at: str


class VersionMeta(Model):
    version: int
    digest: str
    source: DefinitionSource
    published_by: str
    reason: str
    published_at: str


class DefinitionDetail(Model):
    """One definition at one version. `yaml` is the main file as exported (JSON for a schema); `files` holds
    the Markdown files of an agent by path relative to its folder. `body` is the same main file parsed, so a
    client can read fields without a YAML parser. `refs` are the definitions this one refers to and
    `used_by` those that refer to it, both computed from the latest versions."""

    summary: DefinitionSummary
    versions: list[VersionMeta]  # newest first
    yaml: str
    body: dict[str, Any]
    files: dict[str, str]
    refs: list[DefinitionRef]
    used_by: list[DefinitionRef]


class DefinitionIssue(Model):
    """One validation error. `kind`/`key` name the definition it was found in, which can be another one."""

    kind: str
    key: str
    path: str  # a location inside the definition, e.g. "nodes[2].routes.ok"
    message: str


class ValidateDefinitionRequest(RequestModel):
    """The edited main file (YAML; JSON for a schema) plus the agent's Markdown files by relative path. The
    `kind` and `key` inside the YAML, when present, must equal the URL's."""

    yaml: DefinitionText
    files: dict[str, DefinitionFileText] = Field(default_factory=dict, max_length=50)


class PublishDefinitionRequest(ValidateDefinitionRequest):
    """`base_version` is the latest version the edit started from (0 for a new definition). When sent, the
    publish is refused with 409 VERSION_CONFLICT if someone has published since."""

    reason: Reason
    base_version: int | Opt = Field(default=None, ge=0)


class ValidateDefinitionResult(Model):
    ok: bool
    errors: list[DefinitionIssue]


class DefinitionExport(Model):
    files: dict[str, str]  # path relative to the definitions root -> text


# Memory ------------------------------------------------------------------------------------------------

MAX_MEMORY_TEXT = 2000
MemoryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MEMORY_TEXT)
]


class MemorySpace(Model):
    key: str
    name: str
    description: str
    item_count: int
    version: int


class MemorySpaceItem(Model):
    id: str
    space: str
    text: str
    source: str  # "seed", "console" or "agent"
    created_by: str
    created_at: str


class AddMemoryItemRequest(RequestModel):
    text: MemoryText
    reason: Reason


# A real run -------------------------------------------------------------------------------------------


class OpsRunDetail(Model):
    """A real run's projection together with its work receipt (hash chain verified now)."""

    run: Run
    receipt: Receipt
