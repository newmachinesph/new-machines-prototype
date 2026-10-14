"""Operator console: reviewers (the workforce), cross-tenant runs, platform guardrails and billing."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import Query

from app import db, ops_reviewers, ops_state, real_runs, settings, workspace
from app.auth import CurrentOps, OpsActor, OpsWriter
from app.errors import NO_CHANGE, NOT_AVAILABLE_LIVE, ApiProblem, conflicts
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
from app.models.runs import RunStatus, RunSummary
from app.routers.ops_params import PathId
from app.routers.ops_tenants import dollars
from app.routing import ApiRouter
from app.store import Store, iso, locked_store, utc_now

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

USD_MINOR = "usd_minor"
LIVE_REVIEWERS = "In the live workspace, network reviewers join from the reviewer portal and have no level."


# Reviewers ---------------------------------------------------------------------------------------------


def find_reviewer(store: Store, reviewer_id: str) -> Reviewer:
    reviewer = store.reviewers.get(reviewer_id)
    if reviewer is None:
        raise ApiProblem(404, "NOT_FOUND", f"No reviewer {reviewer_id}.")
    return reviewer


def refuse_live_reviewer_writes() -> None:
    """Approve and set level have no live meaning (no applicants, no levels): refused there, no audit."""
    if workspace.live():
        raise ApiProblem(409, NOT_AVAILABLE_LIVE, LIVE_REVIEWERS)


def _live_move(
    reviewer_id: str,
    reason: Reason,
    actor: OpsActor,
    verb: str,
    allowed: ReviewerStatus,
    target: ReviewerStatus,
) -> Reviewer:
    """A network reviewer's status step in the live workspace (`ops_reviewers.move`), committed."""
    with db.connect() as conn:
        reviewer = ops_reviewers.move(
            conn, reviewer_id, verb, allowed, target, actor.email, reason, actor_role=actor.role
        )
        conn.commit()
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
    refuse_live_reviewer_writes()
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
    """The reviewer workforce: the New Machines reviewer network in the live workspace, the fixture pool in
    the demo."""
    if workspace.live():
        with db.connect() as conn:
            return ops_reviewers.list_reviewers(conn, status)
    with locked_store() as store:
        return [r.model_copy() for r in store.reviewers.values() if status is None or r.status == status]


@router.post(
    "/reviewers/{reviewer_id}:approve",
    operation_id="opsApproveReviewer",
    responses=conflicts(NOT_AVAILABLE_LIVE, "INVALID_TRANSITION"),
    response_model=Reviewer,
)
def ops_approve_reviewer(reviewer_id: PathId, body: ReasonRequest, actor: OpsWriter) -> Reviewer:
    return move_reviewer(reviewer_id, body.reason, actor, "approve", "applicant", "active")


@router.post(
    "/reviewers/{reviewer_id}:suspend",
    operation_id="opsSuspendReviewer",
    responses=conflicts("INVALID_TRANSITION"),
    response_model=Reviewer,
)
def ops_suspend_reviewer(reviewer_id: PathId, body: ReasonRequest, actor: OpsWriter) -> Reviewer:
    """Stop offering the reviewer tasks. In the live workspace, their open network claims return to the
    queue."""
    if workspace.live():
        return _live_move(reviewer_id, body.reason, actor, "suspend", "active", "suspended")
    return move_reviewer(reviewer_id, body.reason, actor, "suspend", "active", "suspended")


@router.post(
    "/reviewers/{reviewer_id}:reinstate",
    operation_id="opsReinstateReviewer",
    responses=conflicts("INVALID_TRANSITION"),
    response_model=Reviewer,
)
def ops_reinstate_reviewer(reviewer_id: PathId, body: ReasonRequest, actor: OpsWriter) -> Reviewer:
    """Offer a suspended reviewer tasks again."""
    if workspace.live():
        return _live_move(reviewer_id, body.reason, actor, "reinstate", "suspended", "active")
    return move_reviewer(reviewer_id, body.reason, actor, "reinstate", "suspended", "active")


@router.post(
    "/reviewers/{reviewer_id}:setLevel",
    operation_id="opsSetReviewerLevel",
    responses=conflicts(NOT_AVAILABLE_LIVE, "INVALID_TRANSITION", NO_CHANGE),
    response_model=Reviewer,
)
def ops_set_reviewer_level(reviewer_id: PathId, body: SetLevelRequest, actor: OpsWriter) -> Reviewer:
    refuse_live_reviewer_writes()
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


def all_runs(store: Store, real: Sequence[tuple[str, RunSummary]] = ()) -> list[OpsRun]:
    """Real runs (given, when the runtime is on), the demo tenant's fixture runs, and the seeded runs of the
    other tenants. Newest first."""
    demo = store.tenants.get(store.org.id)
    demo_name = demo.name if demo else store.org.name
    runs = [
        OpsRun.of(r, org_id, t.name if (t := store.tenants.get(org_id)) else org_id).model_copy(
            update={"real": True}
        )
        for org_id, r in real
    ]
    runs += [OpsRun.of(r, store.org.id, demo_name) for r in store.run_summaries]
    runs += [r.model_copy() for r in store.ops_runs]
    return sorted(runs, key=lambda r: r.started_at, reverse=True)


def live_runs(real: Sequence[tuple[str, RunSummary]]) -> list[OpsRun]:
    """The live workspace's runs: real ones only, named after their org. Newest first, as `ops_runs` reads."""
    with db.connect() as conn:
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM orgs").fetchall()}
    return [
        OpsRun.of(r, org_id, names.get(org_id, org_id)).model_copy(update={"real": True})
        for org_id, r in real
    ]


@router.get("/runs", operation_id="opsListRuns", response_model=list[OpsRun])
def ops_list_runs(
    _: CurrentOps,
    status: RunStatus | None = None,
    tenant: Annotated[str | None, Query(max_length=100)] = None,
) -> list[OpsRun]:
    real = real_runs.ops_runs() if settings.runtime_enabled() else []  # before the lock: it reads Postgres
    if workspace.live():
        runs = live_runs(real)
    else:
        with locked_store() as store:
            runs = all_runs(store, real)
    return [
        r
        for r in runs
        if (status is None or r.status == status) and (tenant is None or r.tenant_id == tenant)
    ]


# Guardrails --------------------------------------------------------------------------------------------


def shown(guardrail: Guardrail, value: int) -> str:
    return dollars(value) if guardrail.unit == USD_MINOR else str(value)


def _live_pause(conn, fixture: Guardrail) -> Guardrail:
    """The pause switch as Postgres has it; only the label and description come from the fixture."""
    row = ops_state.pause_setting(conn)
    return fixture.model_copy(
        update={
            "enabled": (row["value"] or {}).get("enabled") is True,
            "updated_at": iso(row["updated_at"]),
            "updated_by": row["updated_by"],
        }
    )


@router.get("/guardrails", operation_id="opsListGuardrails", response_model=list[Guardrail])
def ops_list_guardrails(_: CurrentOps) -> list[Guardrail]:
    """In the live workspace the pause switch is persisted; the other guardrails stay fixtures."""
    with locked_store() as store:
        guardrails = [g.model_copy() for g in store.guardrails.values()]
    if not workspace.live():
        return guardrails
    with db.connect() as conn:
        live = [_live_pause(conn, g) if g.key == ops_state.PAUSE_ALL_RUNS else g for g in guardrails]
        conn.commit()  # pause_setting writes the default row back should it be missing
    return live


def _set_live_pause(body: SetGuardrailRequest, actor: OpsActor) -> Guardrail:
    with locked_store() as store:
        fixture = store.guardrails[ops_state.PAUSE_ALL_RUNS].model_copy()
    if body.value is not None:
        raise ApiProblem(422, "SCHEMA_INVALID", f"{fixture.label} has no value; set enabled instead.")
    if body.enabled is None:
        raise ApiProblem(409, NO_CHANGE, f"{fixture.label} already has those settings.")
    with db.connect() as conn:
        try:
            ops_state.set_paused(conn, body.enabled, actor.email, body.reason, actor_role=actor.role)
        except ops_state.NoChange:
            raise ApiProblem(409, NO_CHANGE, f"{fixture.label} already has those settings.") from None
        conn.commit()
        return _live_pause(conn, fixture)


@router.post(
    "/guardrails/{key}:set",
    operation_id="opsSetGuardrail",
    responses=conflicts(NOT_AVAILABLE_LIVE, NO_CHANGE),
    response_model=Guardrail,
)
def ops_set_guardrail(key: PathId, body: SetGuardrailRequest, actor: OpsWriter) -> Guardrail:
    if workspace.live():
        with locked_store() as store:
            known = key in store.guardrails
        if not known:
            raise ApiProblem(404, "NOT_FOUND", f"No guardrail {key}.")
        if key != ops_state.PAUSE_ALL_RUNS:
            raise ApiProblem(
                409, NOT_AVAILABLE_LIVE, "In the live workspace, only the pause switch can be changed."
            )
        return _set_live_pause(body, actor)
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
