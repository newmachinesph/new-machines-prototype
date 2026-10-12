from typing import Annotated

from fastapi import Header

from app.auth import CurrentActor
from app.errors import ApiProblem
from app.idempotency import once
from app.models.common import Money
from app.models.requests import StartRunRequest
from app.models.runs import Run, RunEdge, RunNode, RunSummary, Spent, Stages, TimelineEvent
from app.routers.catalog import find_pack
from app.routing import ApiRouter
from app.store import get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["runs"])

NOW = "2026-10-12T16:40:00Z"


def find_run(run_id: str) -> Run:
    run = get_store().runs.get(run_id)
    if run is None:
        raise ApiProblem(404, "NOT_FOUND", f"No run {run_id}.")
    return run


def _new_run(body: StartRunRequest) -> Run:
    with locked_store() as store:
        pack = find_pack(body.pack_slug)
        if not pack.installed:
            raise ApiProblem(403, "POLICY_DENIED", f"Hire {pack.name} before starting a run.")
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


@router.get("/workflow-runs", operation_id="listWorkflowRuns", response_model=list[RunSummary])
def list_workflow_runs(_: CurrentActor) -> list[RunSummary]:
    return get_store().run_summaries


@router.get("/workflow-runs/{run_id}", operation_id="getWorkflowRun", response_model=Run)
def get_workflow_run(run_id: str, _: CurrentActor) -> Run:
    return find_run(run_id)


@router.post("/workflow-runs", operation_id="startWorkflowRun", response_model=Run, status_code=202)
def start_workflow_run(
    body: StartRunRequest,
    actor: CurrentActor,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Run:
    """Returns 202: the run is registered and started, not finished (API.md section 3)."""
    return once("start-run", actor, idempotency_key, body, lambda: _new_run(body))
