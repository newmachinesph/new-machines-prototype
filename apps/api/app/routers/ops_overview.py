"""Operator console: the overview. In the demo workspace the attention list and the counts are derived from
the store, so approving the last pack in review removes its item, and the run and spend figures are
simulated. The live workspace reads them from Postgres (`ops_live.overview`)."""

from datetime import UTC, datetime

from app import db, ops_live, workspace
from app.auth import CurrentOps
from app.models.common import Money
from app.models.ops import (
    HourPoint,
    OpsAttentionItem,
    OpsKpis,
    OpsOverview,
)
from app.ops_live import (
    CAP_CRITICAL,
    CAP_WATCH,
    CONNECTOR_ERROR_RATE,
    PLATFORM_DAILY_CAP,
    RECENT_AUDIT,
    sorted_attention,
)
from app.routers.ops_tenants import dollars, tenant_view
from app.routing import ApiRouter
from app.store import Store, locked_store

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

NOW = "2026-10-12T16:40:00Z"  # the demo's "now", for items that have no event time of their own
OPEN_TASK_STATES = {"OFFERED", "CLAIMED", "SUBMITTED", "VALIDATING"}
SIMULATED_FIELDS = ["kpis.runsToday", "kpis.runSuccessRate7d", "kpis.aiSpendToday", "runsByHour"]
# Simulated and deterministic: each hour's share of a day's runs (UTC), peaking mid-morning.
HOUR_WEIGHTS = [1, 1, 1, 1, 2, 3, 5, 8, 11, 13, 14, 13, 11, 10, 11, 12, 10, 7, 5, 4, 3, 2, 2, 1]
RUNS_PER_DAY = 540
FAILED_SHARE = 0.03
WAITING_SHARE = 0.08
AI_SPEND_TODAY_MINOR = 31840
RUN_SUCCESS_RATE_7D = 0.964


def runs_by_hour() -> list[HourPoint]:
    total_weight = sum(HOUR_WEIGHTS)
    points = []
    for hour, weight in enumerate(HOUR_WEIGHTS):
        runs = round(RUNS_PER_DAY * weight / total_weight)
        failed = round(runs * FAILED_SHARE) + (1 if hour % 7 == 3 else 0)
        waiting = round(runs * WAITING_SHARE)
        points.append(
            HourPoint(hour=hour, completed=max(runs - failed - waiting, 0), failed=failed, waiting=waiting)
        )
    return points


def attention_items(store: Store) -> list[OpsAttentionItem]:
    items: list[OpsAttentionItem] = []
    for listing in store.pack_listings.values():
        if listing.status == "in_review":
            items.append(
                OpsAttentionItem(
                    kind="pack_review",
                    title=f"Review {listing.name} v{listing.version}",
                    detail=f"Submitted by {listing.publisher}.",
                    href=f"/marketplace/{listing.slug}",
                    severity="info",
                    at=listing.submitted_at or listing.updated_at,
                )
            )
    for reviewer in store.reviewers.values():
        if reviewer.status == "applicant":
            items.append(
                OpsAttentionItem(
                    kind="reviewer_application",
                    title=f"{reviewer.name} applied as a reviewer",
                    detail=f"{reviewer.country}: {', '.join(reviewer.skills)}.",
                    href="/workforce?tab=applicants",
                    severity="info",
                    at=reviewer.joined_at,
                )
            )
    for connector in store.connector_catalog.values():
        check = connector.last_health_check
        failing = check is not None and not check.ok
        if connector.error_rate >= CONNECTOR_ERROR_RATE or failing:
            cause = "last health check failed" if failing else "above the 5% limit"
            items.append(
                OpsAttentionItem(
                    kind="connector_error",
                    title=f"{connector.app} connector is failing",
                    detail=f"Error rate {connector.error_rate:.1%}, {cause}.",
                    href=f"/connectors?c={connector.id}",
                    severity="warn",
                    at=check.at if check else NOW,
                )
            )
    for tenant in store.tenants.values():
        view = tenant_view(store, tenant)
        cap = view.monthly_cap.amount_minor
        spent = view.month_spent.amount_minor
        if view.status != "churned" and cap > 0 and spent / cap >= CAP_WATCH:
            share = spent / cap
            items.append(
                OpsAttentionItem(
                    kind="tenant_cap",
                    title=f"{view.short} is at {share:.0%} of its monthly cap",
                    detail=f"{dollars(spent)} of {dollars(cap)} spent.",
                    href=f"/tenants/{view.id}",
                    severity="warn" if share >= CAP_CRITICAL else "info",
                    at=NOW,
                )
            )
        if view.health == "at_risk":
            items.append(
                OpsAttentionItem(
                    kind="tenant_at_risk",
                    title=f"{view.short} is at risk",
                    detail=view.notes or "Health is at risk.",
                    href=f"/tenants/{view.id}",
                    severity="info",
                    at=NOW,
                )
            )
    for incident in store.incidents:
        if incident.status != "resolved":
            items.append(
                OpsAttentionItem(
                    kind="incident",
                    title=f"{incident.id}: {incident.title}",
                    detail=f"{incident.severity}, {incident.status}. Affects {', '.join(incident.services)}.",
                    href="/health",
                    severity="critical" if incident.severity == "sev1" else "info",
                    at=incident.started_at,
                )
            )
    return sorted_attention(items)


@router.get("/overview", operation_id="opsGetOverview", response_model=OpsOverview)
def ops_get_overview(_: CurrentOps) -> OpsOverview:
    if workspace.live():
        with db.connect() as conn:
            return ops_live.overview(conn, datetime.now(UTC))
    with locked_store() as store:
        cap = store.guardrails[PLATFORM_DAILY_CAP].value or 0
        hours = runs_by_hour()
        kpis = OpsKpis(
            active_tenants=sum(t.status == "active" for t in store.tenants.values()),
            trial_tenants=sum(t.status == "trial" for t in store.tenants.values()),
            runs_today=sum(h.completed + h.failed + h.waiting for h in hours),
            run_success_rate7d=RUN_SUCCESS_RATE_7D,
            open_human_tasks=sum(t.state in OPEN_TASK_STATES for t in store.tasks.values()),
            pending_approvals=sum(a.status == "PENDING" for a in store.approvals),
            ai_spend_today=Money(amount_minor=AI_SPEND_TODAY_MINOR),
            platform_daily_cap=Money(amount_minor=cap),
            incidents_open=sum(i.status != "resolved" for i in store.incidents),
        )
        recent = sorted(reversed(store.audit_log), key=lambda e: e.at, reverse=True)[:RECENT_AUDIT]
        return OpsOverview(
            kpis=kpis,
            attention=attention_items(store),
            recent_audit=[e.model_copy() for e in recent],
            runs_by_hour=hours,
            simulated_fields=SIMULATED_FIELDS,
        )
