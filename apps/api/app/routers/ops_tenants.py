"""Operator console: customer tenants. Suspending a tenant locks it out of every customer route (see
`auth.get_actor`); the demo tenant's numbers and lists come from the live customer store. In the live
workspace the tenants are the `orgs` rows in Postgres (`app.ops_live`)."""

import hashlib
import secrets
import string
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import Query

from app import db, ops_live, workspace
from app.auth import CurrentOps, OpsWriter
from app.errors import NO_CHANGE, NOT_AVAILABLE_LIVE, ApiProblem, conflicts
from app.models.common import Money
from app.models.ops import (
    CreateTenantRequest,
    OpsRun,
    ReasonRequest,
    SetPlanRequest,
    SetSpendCapRequest,
    Tenant,
    TenantConnection,
    TenantDetail,
    TenantPlan,
    TenantSeedDetail,
    TenantStatus,
    UsagePoint,
)
from app.models.org import Member
from app.routers.ops_params import PathId
from app.routing import ApiRouter
from app.store import Store, iso, locked_store

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

ID_ALPHABET = string.ascii_lowercase + string.digits
ID_ATTEMPTS = 50
RECENT_RUNS = 10
USAGE_DAYS = 14
USAGE_LAST_DAY = date(2026, 10, 12)  # the demo's "today", as in the run fixtures
DAYS_INTO_MONTH = USAGE_LAST_DAY.day
SEATS_BY_PLAN: dict[TenantPlan, int] = {"Starter": 3, "Pro": 10, "Enterprise": 25}


def dollars(minor: int) -> str:
    return f"${minor / 100:,.2f}"


def find_tenant(store: Store, tenant_id: str) -> Tenant:
    tenant = store.tenants.get(tenant_id)
    if tenant is None:
        raise ApiProblem(404, "NOT_FOUND", f"No tenant {tenant_id}.")
    return tenant


def is_demo(store: Store, tenant: Tenant) -> bool:
    return tenant.id == store.org.id


def tenant_view(store: Store, tenant: Tenant) -> Tenant:
    """A copy made under the lock, so serialization never sees a half-applied mutation. The demo tenant's
    counts and spend are read from the live customer store, so a member invited in the customer app shows
    up here."""
    if not is_demo(store, tenant):
        return tenant.model_copy()
    return tenant.model_copy(
        update={
            "members": len(store.members),
            "packs_installed": sum(p.installed for p in store.packs),
            "connectors": len(store.connections),
            "monthly_cap": store.org.monthly_cap,
            "month_spent": store.org.month_spent,
        }
    )


def usage_by_day(tenant: Tenant) -> list[UsagePoint]:
    """Simulated: 14 days around the tenant's average daily spend this month, the same on every call."""
    average = tenant.month_spent.amount_minor / DAYS_INTO_MONTH
    points = []
    for back in range(USAGE_DAYS - 1, -1, -1):
        day = (USAGE_LAST_DAY - timedelta(days=back)).isoformat()
        jitter = hashlib.sha256(f"{tenant.id}:{day}".encode()).digest()[0] / 255  # 0..1
        points.append(UsagePoint(day=day, amount_minor=round(average * (0.4 + 1.2 * jitter))))
    return points


def tenant_detail(store: Store, tenant: Tenant) -> TenantDetail:
    view = tenant_view(store, tenant)
    if is_demo(store, tenant):
        members = list(store.members)
        packs = [p.slug for p in store.packs if p.installed]
        connections = [TenantConnection.of(c) for c in store.connections]
        runs = [OpsRun.of(r, tenant.id, tenant.name) for r in store.run_summaries[:RECENT_RUNS]]
    else:
        seeded = store.tenant_details.get(tenant.id)
        members = list(seeded.members_list) if seeded else []
        packs = list(seeded.installed_packs) if seeded else []
        connections = list(seeded.connectors_list) if seeded else []
        mine = sorted((r for r in store.ops_runs if r.tenant_id == tenant.id), key=lambda r: r.started_at)
        runs = [r.model_copy() for r in reversed(mine)][:RECENT_RUNS]
    return TenantDetail(
        **view.model_dump(),
        members_list=members,
        installed_packs=packs,
        connectors_list=connections,
        recent_runs=runs,
        usage_by_day=usage_by_day(view),
        simulated=True,
    )


def new_tenant_id(store: Store) -> str:
    for _ in range(ID_ATTEMPTS):
        candidate = "org_" + "".join(secrets.choice(ID_ALPHABET) for _ in range(4))
        if candidate not in store.tenants:
            return candidate
    raise RuntimeError("No free tenant id after several attempts.")


def matches(tenant: Tenant, q: str) -> bool:
    needle = q.strip().lower()
    return any(
        needle in field.lower() for field in (tenant.id, tenant.name, tenant.short, tenant.owner_email)
    )


# Reads -------------------------------------------------------------------------------------------------


@router.get("/tenants", operation_id="opsListTenants", response_model=list[Tenant])
def ops_list_tenants(
    _: CurrentOps,
    status: TenantStatus | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[Tenant]:
    if workspace.live():
        with db.connect() as conn:
            return ops_live.list_tenants(conn, status, q)
    with locked_store() as store:
        return [
            tenant_view(store, t)
            for t in store.tenants.values()
            if (status is None or t.status == status) and (not q or matches(t, q))
        ]


@router.get("/tenants/{tenant_id}", operation_id="opsGetTenant", response_model=TenantDetail)
def ops_get_tenant(tenant_id: PathId, _: CurrentOps) -> TenantDetail:
    if workspace.live():
        with db.connect() as conn:
            return ops_live.get_tenant(conn, tenant_id)
    with locked_store() as store:
        return tenant_detail(store, find_tenant(store, tenant_id))


# Mutations ---------------------------------------------------------------------------------------------


def live_action(act: Callable[[Any], Tenant]) -> Tenant:
    """Run one live tenant action (`act(conn)` writes the change and its audit entry) in one transaction."""
    with db.connect() as conn:
        tenant = act(conn)
        conn.commit()
    return tenant


@router.post(
    "/tenants",
    operation_id="opsCreateTenant",
    responses=conflicts(NOT_AVAILABLE_LIVE),
    response_model=Tenant,
    status_code=201,
)
def ops_create_tenant(body: CreateTenantRequest, actor: OpsWriter) -> Tenant:
    if workspace.live():
        raise ApiProblem(409, NOT_AVAILABLE_LIVE, "In the live workspace, orgs are created at sign-up.")
    now = datetime.now(UTC)
    trial_ends_at = None
    if body.trial_days:
        trial_ends_at = iso(now + timedelta(days=body.trial_days))
    with locked_store() as store:
        tenant = Tenant(
            id=new_tenant_id(store),
            name=body.name,
            short=body.short,
            plan=body.plan,
            status="trial" if trial_ends_at else "active",
            region=body.region,
            country=body.country,
            owner_email=body.owner_email,
            seats=SEATS_BY_PLAN[body.plan],
            members=1,
            created_at=iso(now),
            monthly_cap=Money(amount_minor=body.monthly_cap_minor),
            month_spent=Money(amount_minor=0),
            runs30d=0,
            success_rate=0,
            open_human_tasks=0,
            packs_installed=0,
            connectors=0,
            health="healthy",
            notes="",
            trial_ends_at=trial_ends_at,
        )
        owner = Member(
            name=body.owner_email, email=body.owner_email, role="Owner", via="Invite link", pending=True
        )
        store.tenants[tenant.id] = tenant
        store.tenant_details[tenant.id] = TenantSeedDetail(
            members_list=[owner], installed_packs=[], connectors_list=[]
        )
        terms = f"trial {body.trial_days} days" if body.trial_days else "active"
        summary = f"Created {tenant.name} on {tenant.plan}, {terms}, cap {dollars(body.monthly_cap_minor)}"
        store.audit(actor, "tenant.create", "tenant", tenant.id, body.reason, summary)
        return tenant_view(store, tenant)


@router.post(
    "/tenants/{tenant_id}:suspend",
    operation_id="opsSuspendTenant",
    responses=conflicts("ALREADY_SUSPENDED", "INVALID_TRANSITION"),
    response_model=Tenant,
)
def ops_suspend_tenant(tenant_id: PathId, body: ReasonRequest, actor: OpsWriter) -> Tenant:
    if workspace.live():
        return live_action(
            lambda conn: ops_live.suspend(conn, tenant_id, actor.email, body.reason, actor_role=actor.role)
        )
    with locked_store() as store:
        tenant = find_tenant(store, tenant_id)
        if tenant.status == "suspended":
            raise ApiProblem(409, "ALREADY_SUSPENDED", f"{tenant.name} is already suspended.")
        if tenant.status == "churned":
            raise ApiProblem(409, "INVALID_TRANSITION", f"{tenant.name} has churned and cannot be suspended.")
        before = tenant.status
        store.status_before_suspension[tenant.id] = before
        tenant.status = "suspended"
        tenant.suspended_reason = body.reason
        store.audit(actor, "tenant.suspend", "tenant", tenant.id, body.reason, f"Status {before} → suspended")
        return tenant_view(store, tenant)


@router.post(
    "/tenants/{tenant_id}:reactivate",
    operation_id="opsReactivateTenant",
    responses=conflicts("NOT_SUSPENDED"),
    response_model=Tenant,
)
def ops_reactivate_tenant(tenant_id: PathId, body: ReasonRequest, actor: OpsWriter) -> Tenant:
    """The tenant returns to the status it had when suspended. One seeded as suspended becomes active."""
    if workspace.live():
        return live_action(
            lambda conn: ops_live.reactivate(conn, tenant_id, actor.email, body.reason, actor_role=actor.role)
        )
    with locked_store() as store:
        tenant = find_tenant(store, tenant_id)
        if tenant.status != "suspended":
            raise ApiProblem(409, "NOT_SUSPENDED", f"{tenant.name} is not suspended.")
        tenant.status = store.status_before_suspension.pop(tenant.id, "active")
        tenant.suspended_reason = None
        summary = f"Status suspended → {tenant.status}"
        store.audit(actor, "tenant.reactivate", "tenant", tenant.id, body.reason, summary)
        return tenant_view(store, tenant)


@router.post(
    "/tenants/{tenant_id}:setPlan",
    operation_id="opsSetTenantPlan",
    responses=conflicts(NOT_AVAILABLE_LIVE, "INVALID_TRANSITION", NO_CHANGE),
    response_model=Tenant,
)
def ops_set_tenant_plan(tenant_id: PathId, body: SetPlanRequest, actor: OpsWriter) -> Tenant:
    if workspace.live():
        raise ApiProblem(409, NOT_AVAILABLE_LIVE, "In the live workspace, the plan cannot be changed yet.")
    with locked_store() as store:
        tenant = find_tenant(store, tenant_id)
        if tenant.status == "churned":
            raise ApiProblem(409, "INVALID_TRANSITION", f"{tenant.name} has churned and cannot change plan.")
        before = tenant.plan
        if body.plan == before:
            raise ApiProblem(409, NO_CHANGE, f"{tenant.name} is already on {before}.")
        tenant.plan = body.plan
        if is_demo(store, tenant):
            store.org.plan = body.plan
        store.audit(
            actor, "tenant.set_plan", "tenant", tenant.id, body.reason, f"Plan {before} → {body.plan}"
        )
        return tenant_view(store, tenant)


@router.post(
    "/tenants/{tenant_id}:setSpendCap",
    operation_id="opsSetTenantSpendCap",
    responses=conflicts("INVALID_TRANSITION", NO_CHANGE),
    response_model=Tenant,
)
def ops_set_tenant_spend_cap(tenant_id: PathId, body: SetSpendCapRequest, actor: OpsWriter) -> Tenant:
    if workspace.live():
        cap = body.monthly_cap_minor
        return live_action(
            lambda conn: ops_live.set_cap(
                conn, tenant_id, cap, actor.email, body.reason, actor_role=actor.role
            )
        )
    with locked_store() as store:
        tenant = find_tenant(store, tenant_id)
        if tenant.status == "churned":
            raise ApiProblem(
                409, "INVALID_TRANSITION", f"{tenant.name} has churned and cannot change its spend cap."
            )
        before = tenant_view(store, tenant).monthly_cap.amount_minor
        if body.monthly_cap_minor == before:
            raise ApiProblem(409, NO_CHANGE, f"The monthly cap is already {dollars(before)}.")
        cap = Money(amount_minor=body.monthly_cap_minor)
        tenant.monthly_cap = cap
        if is_demo(store, tenant):
            store.org.monthly_cap = cap.model_copy()
        summary = f"Monthly cap {dollars(before)} → {dollars(body.monthly_cap_minor)}"
        store.audit(actor, "tenant.set_spend_cap", "tenant", tenant.id, body.reason, summary)
        return tenant_view(store, tenant)
