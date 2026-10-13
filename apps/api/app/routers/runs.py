from typing import Annotated

from fastapi import Header

from app import real_runs, settings
from app.auth import Actor, CurrentActor
from app.errors import ApiProblem, Problem
from app.idempotency import once
from app.models.catalog import Pack
from app.models.common import Money
from app.models.requests import StartRunRequest
from app.models.runs import Receipt, Run, RunEdge, RunNode, RunSummary, Spent, Stages, TimelineEvent
from app.routers.catalog import find_pack
from app.routing import ApiRouter
from app.store import Store, get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["runs"])

NOW = "2026-10-12T16:40:00Z"
UNAVAILABLE = "The workflow engine is unavailable (RUNTIME_UNAVAILABLE)."


def find_run(run_id: str) -> Run:
    run = get_store().runs.get(run_id)
    if run is None:
        raise ApiProblem(404, "NOT_FOUND", f"No run {run_id}.")
    return run


def _startable_pack(store: Store, slug: str) -> Pack:
    """The pack to run, after the platform guardrail and the hire check. Call inside `locked_store()`."""
    if store.guardrails["pause_all_runs"].enabled:
        raise ApiProblem(409, "PLATFORM_PAUSED", "New Machines has paused all new runs. Try again later.")
    pack = find_pack(slug)
    if not pack.installed:
        raise ApiProblem(403, "POLICY_DENIED", f"Hire {pack.name} before starting a run.")
    return pack


def _new_run(body: StartRunRequest) -> Run:
    with locked_store() as store:
        pack = _startable_pack(store, body.pack_slug)
        run_id = f"run_{store.next_run}"
        store.next_run += 1
        zero = Money(amount_minor=0)
        run = Run(
            id=run_id,
            pack_slug=pack.slug,
            title=f"{pack.name}: {body.input}",
            status="RUNNING",
            started_at=NOW,
            started_by="You",
            input=body.input,
            workflow_ref=f"wf_{pack.slug.replace('-', '_')}@{pack.version}",
            contract_ref="contract_demo@1",
            budget=Money(amount_minor=body.budget_minor),
            spent=Spent(ai=zero, human=zero, tools=zero),
            stages=Stages(executed="pending", verified="pending", accepted="pending", settlement="pending"),
            summary="Started. Reading the input.",
            nodes=[
                RunNode(
                    id="start",
                    type="trigger",
                    label="Start",
                    subtitle="Started by you",
                    actor="buyer",
                    status="COMPLETED",
                    x=0,
                    y=0,
                ),
                RunNode(
                    id="read",
                    type="connector",
                    label="Read the input",
                    subtitle=body.input,
                    actor="machine",
                    status="RUNNING",
                    x=210,
                    y=0,
                ),
            ],
            edges=[RunEdge(from_="start", to="read", taken=True)],
            timeline=[
                TimelineEvent(
                    at=NOW,
                    actor="buyer",
                    who="You",
                    title="Started the run",
                    detail=body.note or f"Budget up to ${body.budget_minor / 100:.2f}.",
                    node_id="start",
                )
            ],
        )
        store.runs[run_id] = run
        store.run_summaries.insert(0, run.summary_row())
        return run


def _new_real_run(body: StartRunRequest, actor: Actor) -> Run:
    with locked_store() as store:
        _startable_pack(store, body.pack_slug)
        catalog = list(store.connector_catalog.values())
    return real_runs.start_real_run(body, actor, catalog)


@router.get("/workflow-runs", operation_id="listWorkflowRuns", response_model=list[RunSummary])
def list_workflow_runs(actor: CurrentActor) -> list[RunSummary]:
    """Real runs (newest first, when the runtime is on), then the fixtures."""
    real = real_runs.real_summaries(actor.org_id) if settings.runtime_enabled() else []
    return real + get_store().run_summaries


@router.get("/workflow-runs/{run_id}", operation_id="getWorkflowRun", response_model=Run)
def get_workflow_run(run_id: str, actor: CurrentActor) -> Run:
    real = real_runs.real_run(actor.org_id, run_id) if settings.runtime_enabled() else None
    return real or find_run(run_id)


@router.get("/workflow-runs/{run_id}/receipt", operation_id="getWorkflowRunReceipt", response_model=Receipt)
def get_workflow_run_receipt(run_id: str, actor: CurrentActor) -> Receipt:
    """The work receipt of a real run: pinned versions, entries and whether the hash chain verifies."""
    found = real_runs.receipt_of(actor.org_id, run_id) if settings.runtime_enabled() else None
    if found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No receipt for {run_id}. Only real runs have one.")
    return found


@router.post(
    "/workflow-runs",
    operation_id="startWorkflowRun",
    response_model=Run,
    status_code=202,
    responses={503: {"model": Problem, "description": UNAVAILABLE}},
)
def start_workflow_run(
    body: StartRunRequest,
    actor: CurrentActor,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Run:
    """Returns 202: the run is registered and started, not finished (API.md section 3). With the runtime on,
    a pack that has a definition runs for real on Temporal; any other pack keeps the fixture behaviour."""
    if real_runs.has_pack(body.pack_slug):
        return once("start-run", actor, idempotency_key, body, lambda: _new_real_run(body, actor))
    return once("start-run", actor, idempotency_key, body, lambda: _new_run(body))
