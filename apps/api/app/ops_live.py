"""The operator console over live Postgres (NM_WORKSPACE=live): tenants are the `orgs` rows.

Every read of an org-scoped table is filtered by the org it describes, so no figure of one tenant counts
another's rows. Each function takes an open psycopg connection; an action writes its change and its
`ops_audit` entry and leaves the commit to the caller, so both land in one transaction.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app import live_connections, ops_state, publisher_stats, workspace
from app.defs import registry
from app.errors import NO_CHANGE, ApiProblem
from app.models.common import Money, money_text
from app.models.ops import (
    AttentionSeverity,
    ConnectorDefaults,
    ConnectorEntry,
    HourPoint,
    OpsAttentionItem,
    OpsKpis,
    OpsOverview,
    OpsRole,
    OpsRun,
    PackCount,
    Tenant,
    TenantConnection,
    TenantDetail,
    TenantHealth,
    TenantPlan,
    TenantStatus,
    UsagePoint,
)
from app.models.runs import Run
from app.run_tasks import OPEN_STATUSES, release_claims
from app.runtime import gateway, routes
from app.runtime.drivers import MCP_TRANSPORT, PLATFORM_MCP_DRIVER
from app.runtime.projection import TERMINAL_RUN_STATUSES
from app.store import iso, locked_store

log = logging.getLogger(__name__)

REGION = workspace.REGION  # one region for the customer app and the console
COUNTRY = "--"  # orgs carry no country yet
# orgs.plan as the console's plan. "trial", which every org starts on, and anything unknown read as Starter.
PLANS: dict[str, TenantPlan] = {"starter": "Starter", "pro": "Pro", "enterprise": "Enterprise"}
DEFAULT_PLAN: TenantPlan = "Starter"
RUN_WINDOW_DAYS = 30
RECENT_RUNS = 10
USAGE_DAYS = 14
AT_RISK_SPEND_SHARE = 0.9  # at risk from 90% of the monthly cap spent
AT_RISK_SUCCESS_RATE = 0.8  # or below 80% of finished runs completed
SHORT_WORDS = 2
SUSPENDED = "suspended"
ACTIVE = "active"
TRIAL_PLAN = "trial"

# Attention thresholds, shared with the demo overview (`routers.ops_overview`).
CONNECTOR_ERROR_RATE = 0.05  # a connector failing at least this share of today's calls
CAP_WATCH = 0.8  # a tenant that spent at least this share of its monthly cap (info)
CAP_CRITICAL = 0.9  # ... or this share (warn)
SEVERITY_RANK: dict[AttentionSeverity, int] = {"critical": 0, "warn": 1, "info": 2}

RECENT_AUDIT = 8
TOP_PACKS = 5
SUCCESS_WINDOW_DAYS = 7
HOURS = 24
LIVE_PROVIDER = "Composio"
LIVE_AUTH = "oauth_managed"
# An MCP server, an org's own (`transport: mcp`) or the platform's (`driver: mcp`): a secret header, no OAuth.
MCP_PROVIDER, MCP_AUTH = "MCP", "api_key"
# A connection row counts as connected only when a run could reach the app through it: the rule
# `live_connections.shown_status` shows as connected or sandbox, in SQL.
ROUTABLE = routes.ROUTABLE_SQL.format(c="c")
# A connector's category, from the first of its tools' capabilities whose domain (the part before the
# first ".") is listed here.
CATEGORIES = {
    "mail": "Communication",
    "sheets": "Spreadsheets",
    "orders": "Commerce",
    "shop": "Commerce",
    "payments": "Payments",
    "invoices": "Payments",
}
UNCATEGORIZED = "Other"
# The overview fields still read from fixtures in the live workspace.
LIVE_SIMULATED_FIELDS = ["kpis.platformDailyCap", "kpis.incidentsOpen", "publisherEarningsMonth"]
PLATFORM_DAILY_CAP = "platform_daily_ai_cap"

# One row per org with its counts. Each subquery is correlated on `o.id`, so it reads that org's rows only.
_TENANTS = f"""
SELECT * FROM (
  SELECT o.id, o.name, o.plan, o.status, o.created_at, o.monthly_cap_minor,
    COALESCE((SELECT m.email FROM org_members m
               WHERE m.org_id = o.id AND m.role = 'owner' AND m.status IN ('active', 'invited')
               ORDER BY m.status <> 'active', m.created_at, m.email LIMIT 1), '') AS owner_email,
    (SELECT count(*) FROM org_members m
      WHERE m.org_id = o.id AND m.status IN ('active', 'invited')) AS seats,
    (SELECT count(*) FROM org_members m WHERE m.org_id = o.id AND m.status = 'active') AS members,
    (SELECT count(*) FROM runs r WHERE r.org_id = o.id AND r.created_at >= %(since)s) AS runs30d,
    (SELECT count(*) FROM runs r
      WHERE r.org_id = o.id AND r.created_at >= %(since)s AND r.status = 'COMPLETED') AS completed,
    (SELECT count(*) FROM runs r
      WHERE r.org_id = o.id AND r.created_at >= %(since)s AND r.status = 'FAILED') AS failed,
    (SELECT count(*) FROM run_tasks t JOIN runs r ON r.id = t.run_id
      WHERE r.org_id = o.id AND t.kind = 'human' AND t.status = %(open)s) AS open_human_tasks,
    (SELECT count(*) FROM installations i WHERE i.org_id = o.id) AS packs_installed,
    (SELECT count(*) FROM connections c
      WHERE c.org_id = o.id AND {ROUTABLE}) AS connectors,
    (SELECT a.reason FROM ops_audit a
      WHERE a.target_type = 'tenant' AND a.target_id = o.id AND a.action = 'tenant.suspend'
      ORDER BY a.at DESC, a.id DESC LIMIT 1) AS suspend_reason
  FROM orgs o
) t
"""


def _short(name: str) -> str:
    return "".join(word[0] for word in name.split()[:SHORT_WORDS]).upper()


def _success_rate(completed: int, failed: int) -> float:
    finished = completed + failed
    return completed / finished if finished else 1.0


def _health(spent: int, cap: int, success_rate: float) -> TenantHealth:
    if spent >= AT_RISK_SPEND_SHARE * cap or success_rate < AT_RISK_SUCCESS_RATE:
        return "at_risk"
    return "healthy"


def _tenant(row: dict, spent: int) -> Tenant:
    """A `_TENANTS` row and what the org spent this month (`workspace.month_spent_by_org`)."""
    cap = int(row["monthly_cap_minor"])
    rate = _success_rate(int(row["completed"]), int(row["failed"]))
    status: TenantStatus = row["status"]
    return Tenant(
        id=row["id"],
        name=row["name"],
        short=_short(row["name"]),
        plan=PLANS.get(str(row["plan"]).lower(), DEFAULT_PLAN),
        status=status,
        region=REGION,
        country=COUNTRY,
        owner_email=row["owner_email"],
        seats=int(row["seats"]),
        members=int(row["members"]),
        created_at=iso(row["created_at"]),
        monthly_cap=Money(amount_minor=cap),
        month_spent=Money(amount_minor=spent),
        runs30d=int(row["runs30d"]),
        success_rate=rate,
        open_human_tasks=int(row["open_human_tasks"]),
        packs_installed=int(row["packs_installed"]),
        connectors=int(row["connectors"]),
        health=_health(spent, cap, rate),
        notes="",
        suspended_reason=row["suspend_reason"] if status == SUSPENDED else None,
    )


def _params(**extra) -> dict:
    since = datetime.now(UTC) - timedelta(days=RUN_WINDOW_DAYS)
    return {"since": since, "open": OPEN_STATUSES["human"], **extra}


def list_tenants(conn, status: str | None, q: str | None) -> list[Tenant]:
    """Every org, oldest first. `status` keeps one status; `q` keeps the orgs whose name, id or owner email
    contains it, ignoring case."""
    needle = (q or "").strip().lower() or None
    rows = conn.execute(
        _TENANTS + "WHERE (%(status)s::text IS NULL OR t.status = %(status)s) "
        "AND (%(q)s::text IS NULL OR strpos(lower(t.name), %(q)s) > 0 OR strpos(lower(t.id), %(q)s) > 0 "
        "OR strpos(lower(t.owner_email), %(q)s) > 0) "
        "ORDER BY t.created_at, t.id",
        _params(status=status, q=needle),
    ).fetchall()
    spent = workspace.month_spent_by_org(conn)
    return [_tenant(r, spent.get(r["id"], 0)) for r in rows]


def _find(conn, org_id: str) -> Tenant:
    row = conn.execute(_TENANTS + "WHERE t.id = %(org)s", _params(org=org_id)).fetchone()
    if row is None:
        raise ApiProblem(404, "NOT_FOUND", f"No tenant {org_id}.")
    return _tenant(row, workspace.month_spent(conn, org_id))


def _recent_runs(conn, tenant: Tenant) -> list[OpsRun]:
    rows = conn.execute(
        "SELECT id, projection FROM runs WHERE org_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
        (tenant.id, RECENT_RUNS),
    ).fetchall()
    runs = []
    for row in rows:
        try:
            summary = Run.model_validate(row["projection"]).summary_row()
        except ValidationError:
            log.error("Run %s has a malformed projection; left out of the tenant.", row["id"], exc_info=True)
            continue
        runs.append(OpsRun.of(summary, tenant.id, tenant.name).model_copy(update={"real": True}))
    return runs


def _usage_by_day(conn, org_id: str, today: date) -> list[UsagePoint]:
    """What the org's runs spent on each of the last USAGE_DAYS days (UTC) up to today, zero on days
    without runs."""
    first = today - timedelta(days=USAGE_DAYS - 1)
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)
    rows = conn.execute(
        f"SELECT (created_at AT TIME ZONE 'UTC')::date AS day, SUM({workspace.RUN_SPENT_SQL}) AS spent "
        "FROM runs WHERE org_id = %s AND created_at >= %s GROUP BY 1",
        (org_id, start),
    ).fetchall()
    by_day = {r["day"]: int(r["spent"]) for r in rows}
    days = (first + timedelta(days=n) for n in range(USAGE_DAYS))
    return [UsagePoint(day=d.isoformat(), amount_minor=by_day.get(d, 0)) for d in days]


def _tenant_connection(org_id: str, row: dict[str, Any]) -> TenantConnection:
    """One connection row as the console shows it: the status the web list shows (`shown_status`, so a
    connected row that `routes.route_of` cannot reach needs signing in again) and its mode. A disconnected
    row keeps its last mode in the table, but the console reports none, as the web list does."""
    disconnected = row["status"] == "not_connected"
    return TenantConnection(
        app=row["app"],
        status=live_connections.shown_status(org_id, row),
        mode=None if disconnected else row["mode"],
    )


def get_tenant(conn, org_id: str) -> TenantDetail:
    """One org with its members, hired packs, app connections, newest runs and real per-day spend."""
    tenant = _find(conn, org_id)
    packs = conn.execute(
        "SELECT pack_slug FROM installations WHERE org_id = %s ORDER BY installed_at, pack_slug", (org_id,)
    ).fetchall()
    connections = conn.execute(
        "SELECT app, status, mode, account_id FROM connections WHERE org_id = %s ORDER BY app", (org_id,)
    ).fetchall()
    return TenantDetail(
        **tenant.model_dump(),
        members_list=workspace.org_members(conn, org_id),
        installed_packs=[r["pack_slug"] for r in packs],
        connectors_list=[_tenant_connection(org_id, r) for r in connections],
        recent_runs=_recent_runs(conn, tenant),
        usage_by_day=_usage_by_day(conn, org_id, datetime.now(UTC).date()),
        simulated=False,
    )


# --- actions --------------------------------------------------------------------------------------------


def _locked(conn, org_id: str) -> dict:
    """The org row, locked until the transaction ends so two operators cannot both act on the old state."""
    row = conn.execute(
        "SELECT id, name, status, monthly_cap_minor FROM orgs WHERE id = %s FOR UPDATE", (org_id,)
    ).fetchone()
    if row is None:
        raise ApiProblem(404, "NOT_FOUND", f"No tenant {org_id}.")
    return row


def _set_status(
    conn, org: dict, target: str, verb: str, actor_email: str, reason: str, actor_role: OpsRole | None
) -> Tenant:
    """Move a locked org (`_locked`) to `target` and audit it as tenant.<verb>."""
    org_id, before = org["id"], org["status"]
    conn.execute("UPDATE orgs SET status = %s WHERE id = %s", (target, org_id))
    data = {"summary": f"Status {before} → {target}", "before": before, "after": target}
    ops_state.audit(
        conn, actor_email, f"tenant.{verb}", "tenant", org_id, reason, data, actor_role=actor_role
    )
    return _find(conn, org_id)


def suspend(conn, org_id: str, actor_email: str, reason: str, *, actor_role: OpsRole | None = None) -> Tenant:
    """Lock the org out of every customer route at once (`auth._live_actor`). Its tasks leave the reviewer
    network, so the open ones network reviewers claimed go back to the queue for the org's team. The org row
    is locked before its tasks, the lock order of `app.review_routing`. 409 ALREADY_SUSPENDED."""
    org = _locked(conn, org_id)
    if org["status"] == SUSPENDED:
        raise ApiProblem(409, "ALREADY_SUSPENDED", f"{org['name']} is already suspended.")
    release_claims(conn, org_id=org_id, via="network")
    return _set_status(conn, org, SUSPENDED, "suspend", actor_email, reason, actor_role)


def reactivate(
    conn, org_id: str, actor_email: str, reason: str, *, actor_role: OpsRole | None = None
) -> Tenant:
    """Let a suspended org back in. 409 NOT_SUSPENDED."""
    org = _locked(conn, org_id)
    if org["status"] != SUSPENDED:
        raise ApiProblem(409, "NOT_SUSPENDED", f"{org['name']} is not suspended.")
    return _set_status(conn, org, ACTIVE, "reactivate", actor_email, reason, actor_role)


def set_cap(
    conn, org_id: str, cap_minor: int, actor_email: str, reason: str, *, actor_role: OpsRole | None = None
) -> Tenant:
    """Set the org's monthly spend cap, which the customer app reads and new runs are checked against.
    409 NO_CHANGE."""
    before = int(_locked(conn, org_id)["monthly_cap_minor"])
    if cap_minor == before:
        raise ApiProblem(409, NO_CHANGE, f"The monthly cap is already {money_text(before)}.")
    conn.execute("UPDATE orgs SET monthly_cap_minor = %s WHERE id = %s", (cap_minor, org_id))
    data = {
        "summary": f"Monthly cap {money_text(before)} → {money_text(cap_minor)}",
        "before": before,
        "after": cap_minor,
    }
    action = "tenant.set_spend_cap"
    ops_state.audit(conn, actor_email, action, "tenant", org_id, reason, data, actor_role=actor_role)
    return _find(conn, org_id)


# --- connectors -----------------------------------------------------------------------------------------


def _aware(now: datetime) -> datetime:
    """`now` itself; ValueError when it has no timezone, since every window is a UTC one."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now


def _day(now: datetime) -> tuple[datetime, datetime]:
    """[00:00 UTC of the day `now` falls on, 00:00 UTC of the next day)."""
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _capabilities(definition: dict) -> list[str]:
    """The definition's tools' capabilities, each once, in tool order."""
    capabilities = (str(tool.get("capability") or "") for tool in definition.get("tools") or [])
    return list(dict.fromkeys(c for c in capabilities if c))


def _category(capabilities: list[str]) -> str:
    domains = (c.partition(".")[0] for c in capabilities)
    return next((CATEGORIES[d] for d in domains if d in CATEGORIES), UNCATEGORIZED)


def _connector_usage(conn, now: datetime) -> tuple[dict[str, int], dict[str, dict]]:
    """({connector key: orgs connected to it}, {connector key: {"calls", "failed"}} over today's tool calls
    the policy permitted), one query each. A connection row names its connector by key, and so does the
    `<connector>.<tool>` ref every tool.call receipt entry carries. A call the policy denied or held for
    approval never reached the connector, so it is neither a call nor an error."""
    connected = conn.execute(
        f"SELECT c.app, count(DISTINCT c.org_id) AS orgs FROM connections c WHERE {ROUTABLE} GROUP BY c.app"
    ).fetchall()
    start, end = _day(now)
    calls = conn.execute(
        "SELECT split_part(data->>'tool_ref', '.', 1) AS connector, count(*) AS calls, "
        "count(*) FILTER (WHERE data->>'ok' = 'false') AS failed "
        "FROM receipt_entries WHERE type = 'tool.call' AND at >= %s AND at < %s "
        "AND data->'policy'->>'verdict' = %s GROUP BY 1",
        (start, end, gateway.PERMIT),
    ).fetchall()
    return {r["app"]: int(r["orgs"]) for r in connected}, {r["connector"]: r for r in calls}


def _org_owners(conn) -> dict[str, tuple[str, str]]:
    """{connector key: (org id, org name)} of the connectors orgs own (their MCP servers'), in one query."""
    rows = conn.execute(
        "SELECT o.key, o.owner_id, g.name FROM definition_owners o JOIN orgs g ON g.id = o.owner_id "
        "WHERE o.kind = 'connector' AND o.owner_kind = 'org'"
    ).fetchall()
    return {r["key"]: (r["owner_id"], r["name"]) for r in rows}


def _connectors(conn, now: datetime, key: str | None = None) -> list[ConnectorEntry]:
    definitions = [v for v in registry.latest_of_kind(conn, "connector") if key is None or v.key == key]
    if not definitions:
        return []
    settings = ops_state.connector_settings(conn)
    connected, calls = _connector_usage(conn, now)
    owned = _org_owners(conn)
    entries = []
    for version in definitions:
        body = version.body
        mcp = body.get("transport") == MCP_TRANSPORT or body.get("driver") == PLATFORM_MCP_DRIVER
        owner_id, owner_name = owned.get(version.key, (None, None))
        app = str(body.get("app") or version.key)
        current = ops_state.effective_settings(body, settings.get(version.key))
        usage = calls.get(version.key) or {"calls": 0, "failed": 0}
        total = int(usage["calls"])
        scopes = _capabilities(body)
        entries.append(
            ConnectorEntry(
                id=version.key,
                app=app,
                category=_category(scopes),
                provider=MCP_PROVIDER if mcp else LIVE_PROVIDER,
                auth_type=MCP_AUTH if mcp else LIVE_AUTH,
                status=current["status"],
                tenants_connected=connected.get(version.key, 0),
                calls_today=total,
                error_rate=int(usage["failed"]) / total if total else 0.0,
                last_health_check=None,
                defaults=ConnectorDefaults(**current["defaults"]),
                scopes=scopes,
                owner_org_id=owner_id,
                owner_org_name=owner_name,
            )
        )
    return entries


def list_connectors(conn, now: datetime | None = None) -> list[ConnectorEntry]:
    """One entry per connector definition (its latest version, as a run snapshot pins it), by key, with the
    settings Ops persisted and today's usage (UTC). A settings row without a definition is not listed.
    An org's own MCP connector names its org (`owner_org_id`, `owner_org_name`)."""
    return _connectors(conn, _aware(now or datetime.now(UTC)))


def connector(conn, key: str, now: datetime | None = None) -> ConnectorEntry | None:
    """The `list_connectors` entry of one connector; None when no definition has the key."""
    return next(iter(_connectors(conn, _aware(now or datetime.now(UTC)), key)), None)


# --- overview -------------------------------------------------------------------------------------------

_RUN_KPIS = f"""
SELECT count(*) FILTER (WHERE created_at >= %(today)s) AS runs_today,
  count(*) FILTER (WHERE status = 'COMPLETED') AS completed,
  count(*) FILTER (WHERE status = 'FAILED') AS failed,
  COALESCE(SUM({workspace.RUN_AI_SPENT_SQL}) FILTER (WHERE created_at >= %(today)s), 0) AS ai_today
FROM runs WHERE created_at >= %(week)s AND created_at < %(tomorrow)s
"""
_OPEN_TASK = (
    "(t.kind = 'human' AND t.status = %(human)s) OR (t.kind = 'approval' AND t.status = %(approval)s)"
)
# Today's runs by UTC hour. A run that has not ended counts as waiting while its status is a WAITING_* one or
# a task of it is still open; one that is neither (running, verifying) or that was cancelled is in no series.
_RUNS_BY_HOUR = f"""
SELECT extract(hour FROM r.created_at AT TIME ZONE 'UTC')::int AS hour,
  count(*) FILTER (WHERE r.status = 'COMPLETED') AS completed,
  count(*) FILTER (WHERE r.status = 'FAILED') AS failed,
  count(*) FILTER (WHERE r.status <> ALL(%(terminal)s) AND (starts_with(r.status, 'WAITING')
    OR EXISTS (SELECT 1 FROM run_tasks t WHERE t.run_id = r.id AND ({_OPEN_TASK})))) AS waiting
FROM runs r WHERE r.created_at >= %(today)s AND r.created_at < %(tomorrow)s GROUP BY 1
"""


def sorted_attention(items: list[OpsAttentionItem]) -> list[OpsAttentionItem]:
    """Most severe first and, within a severity, newest first."""
    newest = sorted(items, key=lambda i: i.at, reverse=True)
    return sorted(newest, key=lambda i: SEVERITY_RANK[i.severity])  # stable: keeps newest first


def _cap_items(orgs: list[dict], spent: dict[str, int], at: str) -> list[OpsAttentionItem]:
    """Orgs that spent at least CAP_WATCH of their monthly cap (warn from CAP_CRITICAL). No cap, no item;
    a suspended org runs nothing, so it has none either."""
    items = []
    for org in orgs:
        cap = int(org["monthly_cap_minor"] or 0)
        used = spent.get(org["id"], 0)
        if org["status"] == SUSPENDED or cap <= 0 or used / cap < CAP_WATCH:
            continue
        share = used / cap
        items.append(
            OpsAttentionItem(
                kind="tenant_cap",
                title=f"{org['name']} is at {share:.0%} of its monthly cap",
                detail=f"{money_text(used)} of {money_text(cap)} spent.",
                href=f"/tenants/{org['id']}",
                severity="warn" if share >= CAP_CRITICAL else "info",
                at=at,
            )
        )
    return items


def _connector_items(connectors: list[ConnectorEntry], at: str) -> list[OpsAttentionItem]:
    return [
        OpsAttentionItem(
            kind="connector_error",
            title=f"{c.app} connector is failing",
            detail=f"Error rate {c.error_rate:.1%} of {c.calls_today} calls today, "
            f"at or above the {CONNECTOR_ERROR_RATE:.0%} limit.",
            href=f"/connectors?c={c.id}",
            severity="warn",
            at=at,
        )
        for c in connectors
        if c.calls_today and c.error_rate >= CONNECTOR_ERROR_RATE
    ]


def _runs_by_hour(conn, params: dict) -> list[HourPoint]:
    rows = {r["hour"]: r for r in conn.execute(_RUNS_BY_HOUR, params).fetchall()}
    zero = {"completed": 0, "failed": 0, "waiting": 0}
    return [
        HourPoint(
            hour=hour,
            completed=int(rows.get(hour, zero)["completed"]),
            failed=int(rows.get(hour, zero)["failed"]),
            waiting=int(rows.get(hour, zero)["waiting"]),
        )
        for hour in range(HOURS)
    ]


def _top_packs(conn, now: datetime) -> list[PackCount]:
    rows = conn.execute(
        "SELECT pack_slug, count(*) AS runs FROM runs WHERE created_at >= %s AND created_at < %s "
        "GROUP BY pack_slug ORDER BY runs DESC, pack_slug LIMIT %s",
        (now - timedelta(days=RUN_WINDOW_DAYS), _day(now)[1], TOP_PACKS),
    ).fetchall()
    names = {
        str(v.body.get("slug") or v.key): str(v.body.get("name") or v.key)
        for v in registry.latest_of_kind(conn, "pack")
    }
    return [
        PackCount(slug=r["pack_slug"], name=names.get(r["pack_slug"], r["pack_slug"]), runs=int(r["runs"]))
        for r in rows
    ]


def _platform_daily_cap() -> int:
    """The platform's daily AI cap, still a fixture guardrail (LIVE_SIMULATED_FIELDS)."""
    with locked_store() as store:
        return store.guardrails[PLATFORM_DAILY_CAP].value or 0


def overview(conn, now: datetime) -> OpsOverview:
    """The overview over every org's rows, one query per metric family. Day windows start at 00:00 UTC of
    `now`'s day; the success rate covers the last SUCCESS_WINDOW_DAYS days, the top packs RUN_WINDOW_DAYS."""
    _aware(now)
    today, tomorrow = _day(now)
    params = {
        "today": today,
        "tomorrow": tomorrow,
        "week": now - timedelta(days=SUCCESS_WINDOW_DAYS),
        "terminal": sorted(TERMINAL_RUN_STATUSES),
        "human": OPEN_STATUSES["human"],
        "approval": OPEN_STATUSES["approval"],
    }
    orgs = conn.execute(
        "SELECT id, name, plan, status, monthly_cap_minor FROM orgs ORDER BY created_at, id"
    ).fetchall()
    runs = conn.execute(_RUN_KPIS, params).fetchone()
    tasks = conn.execute(
        "SELECT count(*) FILTER (WHERE kind = 'human' AND status = %(human)s) AS human, "
        "count(*) FILTER (WHERE kind = 'approval' AND status = %(approval)s) AS approvals FROM run_tasks",
        params,
    ).fetchone()
    spent = workspace.month_spent_by_org(conn, now=now)
    at = iso(now)
    kpis = OpsKpis(
        active_tenants=sum(o["status"] == ACTIVE for o in orgs),
        trial_tenants=sum(str(o["plan"]).lower() == TRIAL_PLAN for o in orgs),
        runs_today=int(runs["runs_today"]),
        run_success_rate7d=_success_rate(int(runs["completed"]), int(runs["failed"])),
        open_human_tasks=int(tasks["human"]),
        pending_approvals=int(tasks["approvals"]),
        ai_spend_today=Money(amount_minor=int(runs["ai_today"])),
        platform_daily_cap=Money(amount_minor=_platform_daily_cap()),
        incidents_open=0,
    )
    in_review, earned = publisher_stats.ops_numbers(conn, now)
    attention = _cap_items(orgs, spent, at) + _connector_items(_connectors(conn, now), at)
    return OpsOverview(
        kpis=kpis,
        attention=sorted_attention(attention),
        recent_audit=[ops_state.audit_entry(r) for r in ops_state.list_audit(conn, RECENT_AUDIT)],
        runs_by_hour=_runs_by_hour(conn, params),
        simulated_fields=list(LIVE_SIMULATED_FIELDS),
        top_packs=_top_packs(conn, now),
        spend_month=Money(amount_minor=sum(spent.values())),
        listings_in_review=in_review,
        publisher_earnings_month=Money(amount_minor=earned),
    )
