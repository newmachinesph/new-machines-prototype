"""Operator console: reviewers (the workforce), cross-tenant runs, platform guardrails and billing."""

from typing import Annotated

from fastapi import Query

from app.auth import CurrentOps, OpsActor, OpsWriter
from app.errors import ApiProblem
from app.models.ops import (
    BillingSummary,
    Guardrail,
    OpsRun,
    Reason,
    ReasonRequest,
    Reviewer,
    ReviewerLevel,
    ReviewerStatus,
    SetGuardrailRequest,
    SetLevelRequest,
)
from app.models.runs import RunStatus
from app.routers.ops_params import PathId
from app.routers.ops_tenants import dollars
from app.routing import ApiRouter
from app.store import Store, locked_store, utc_now

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

NO_CHANGE = "NO_CHANGE"
USD_MINOR = "usd_minor"


# Reviewers ---------------------------------------------------------------------------------------------


def find_reviewer(store: Store, reviewer_id: str) -> Reviewer:
    reviewer = store.reviewers.get(reviewer_id)
    if reviewer is None:
        raise ApiProblem(404, "NOT_FOUND", f"No reviewer {reviewer_id}.")
    return reviewer


def move_reviewer(
    reviewer_id: str,
    reason: Reason,
    actor: OpsActor,
    verb: str,
    allowed: ReviewerStatus,
    target: ReviewerStatus,
) -> Reviewer:
    """One status step: check the current status, change it, audit it, all under the lock."""
    with locked_store() as store:
        reviewer = find_reviewer(store, reviewer_id)
        before = reviewer.status
        if before != allowed:
            raise ApiProblem(409, "INVALID_TRANSITION", f"A {before} reviewer cannot be moved with {verb}.")
        reviewer.status = target
        suffix = ""
        if verb == "approve":
            reviewer.level = "trainee"
            suffix = " (trainee)"
        summary = f"Status {before} → {target}{suffix}"
        store.audit(actor, f"reviewer.{verb}", "reviewer", reviewer.id, reason, summary)
        return reviewer.model_copy()


@router.get("/reviewers", operation_id="opsListReviewers", response_model=list[Reviewer])
def ops_list_reviewers(_: CurrentOps, status: ReviewerStatus | None = None) -> list[Reviewer]:
    with locked_store() as store:
        return [r.model_copy() for r in store.reviewers.values() if status is None or r.status == status]


@router.post("/reviewers/{reviewer_id}:approve", operation_id="opsApproveReviewer", response_model=Reviewer)
def ops_approve_reviewer(reviewer_id: PathId, body: ReasonRequest, actor: OpsWriter) -> Reviewer:
    return move_reviewer(reviewer_id, body.reason, actor, "approve", "applicant", "active")


@router.post("/reviewers/{reviewer_id}:suspend", operation_id="opsSuspendReviewer", response_model=Reviewer)
def ops_suspend_reviewer(reviewer_id: PathId, body: ReasonRequest, actor: OpsWriter) -> Reviewer:
    return move_reviewer(reviewer_id, body.reason, actor, "suspend", "active", "suspended")


@router.post(
    "/reviewers/{reviewer_id}:reinstate", operation_id="opsReinstateReviewer", response_model=Reviewer
)
def ops_reinstate_reviewer(reviewer_id: PathId, body: ReasonRequest, actor: OpsWriter) -> Reviewer:
    return move_reviewer(reviewer_id, body.reason, actor, "reinstate", "suspended", "active")


@router.post("/reviewers/{reviewer_id}:setLevel", operation_id="opsSetReviewerLevel", response_model=Reviewer)
def ops_set_reviewer_level(reviewer_id: PathId, body: SetLevelRequest, actor: OpsWriter) -> Reviewer:
    with locked_store() as store:
        reviewer = find_reviewer(store, reviewer_id)
        if reviewer.status != "active":
            raise ApiProblem(
                409,
                "INVALID_TRANSITION",
                f"Only an active reviewer has a level; this one is {reviewer.status}.",
            )
        before: ReviewerLevel = reviewer.level
        if before == body.level:
            raise ApiProblem(409, NO_CHANGE, f"{reviewer.name} is already {before}.")
        reviewer.level = body.level
        store.audit(
            actor,
            "reviewer.set_level",
            "reviewer",
            reviewer.id,
            body.reason,
            f"Level {before} → {body.level}",
        )
        return reviewer.model_copy()


# Runs --------------------------------------------------------------------------------------------------


def all_runs(store: Store) -> list[OpsRun]:
    """The demo tenant's real runs mapped across, plus the seeded runs of the other tenants. Newest first."""
    demo = store.tenants.get(store.org.id)
    demo_name = demo.name if demo else store.org.name
    runs = [OpsRun.of(r, store.org.id, demo_name) for r in store.run_summaries]
    runs += [r.model_copy() for r in store.ops_runs]
    return sorted(runs, key=lambda r: r.started_at, reverse=True)


@router.get("/runs", operation_id="opsListRuns", response_model=list[OpsRun])
def ops_list_runs(
    _: CurrentOps,
    status: RunStatus | None = None,
    tenant: Annotated[str | None, Query(max_length=100)] = None,
) -> list[OpsRun]:
    with locked_store() as store:
        return [
            r
            for r in all_runs(store)
            if (status is None or r.status == status) and (tenant is None or r.tenant_id == tenant)
        ]


# Guardrails --------------------------------------------------------------------------------------------


def shown(guardrail: Guardrail, value: int) -> str:
    return dollars(value) if guardrail.unit == USD_MINOR else str(value)


@router.get("/guardrails", operation_id="opsListGuardrails", response_model=list[Guardrail])
def ops_list_guardrails(_: CurrentOps) -> list[Guardrail]:
    with locked_store() as store:
        return [g.model_copy() for g in store.guardrails.values()]


@router.post("/guardrails/{key}:set", operation_id="opsSetGuardrail", response_model=Guardrail)
def ops_set_guardrail(key: PathId, body: SetGuardrailRequest, actor: OpsWriter) -> Guardrail:
    with locked_store() as store:
        guardrail = store.guardrails.get(key)
        if guardrail is None:
            raise ApiProblem(404, "NOT_FOUND", f"No guardrail {key}.")
        if body.value is not None and guardrail.kind != "limit":
            raise ApiProblem(422, "SCHEMA_INVALID", f"{guardrail.label} has no value; set enabled instead.")
        changes: list[str] = []
        if body.enabled is not None and body.enabled != guardrail.enabled:
            changes.append(f"Enabled {_onoff(guardrail.enabled)} → {_onoff(body.enabled)}")
        if body.value is not None and body.value != guardrail.value:
            before = shown(guardrail, guardrail.value or 0)
            changes.append(f"Limit {before} → {shown(guardrail, body.value)}")
        if not changes:
            raise ApiProblem(409, NO_CHANGE, f"{guardrail.label} already has those settings.")
        if body.enabled is not None:
            guardrail.enabled = body.enabled
        if body.value is not None:
            guardrail.value = body.value
        guardrail.updated_at = utc_now()
        guardrail.updated_by = actor.email
        store.audit(actor, "guardrail.set", "guardrail", key, body.reason, "; ".join(changes))
        return guardrail.model_copy()


def _onoff(flag: bool) -> str:
    return "on" if flag else "off"


# Billing (simulated, read-only) ------------------------------------------------------------------------


@router.get("/billing", operation_id="opsGetBilling", response_model=BillingSummary)
def ops_get_billing(_: CurrentOps) -> BillingSummary:
    with locked_store() as store:
        return store.billing.model_copy(deep=True)
