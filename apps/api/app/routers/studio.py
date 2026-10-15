"""The Studio (sub-project C): an org builds its own agents and Workflow Packs. Live workspace only (404 in
the demo); every route is scoped to the caller's org. Saves are POST, as the API allows GET, POST and
DELETE."""

from typing import Annotated

from fastapi import Path, Query

from app import studio, workspace
from app.auth import Actor, CurrentActor
from app.errors import TITLES, ApiProblem, Problem, conflicts
from app.models.runs import Run
from app.models.studio import (
    AgentDraft,
    BuilderCheck,
    ImportedWorkflow,
    ImportWorkflowRequest,
    PackDraft,
    Palette,
    SandboxRunRequest,
    SaveAgentRequest,
    SavePackRequest,
    StudioAgent,
    StudioAgentSummary,
    StudioPack,
    StudioPackSummary,
    WorkflowYaml,
)
from app.routers.org import _scope
from app.routers.runs import UNAVAILABLE, _check_live_not_paused
from app.routing import ApiRouter

router = ApiRouter(prefix="/v1/organizations/{org_id}/studio", tags=["studio"])

LIVE_ONLY = "The Studio is part of the live workspace."
KEY_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
StudioKey = Annotated[str, Path(max_length=100, pattern=KEY_PATTERN)]
EditedKey = Annotated[
    str | None,
    Query(
        max_length=100,
        pattern=KEY_PATTERN,
        description="The org's own pack the draft edits, so its current name is not counted against it.",
    ),
]


def _live(org_id: str, actor: Actor) -> None:
    if not workspace.live():
        raise ApiProblem(404, "NOT_FOUND", LIVE_ONLY)
    _scope(org_id, actor)


@router.get("/palette", operation_id="getStudioPalette", response_model=Palette)
def get_studio_palette(org_id: str, actor: CurrentActor) -> Palette:
    """What a pack's steps can use: the agents, app tools, memory and result shapes the org may see."""
    _live(org_id, actor)
    return studio.palette(actor)


@router.get("/agents", operation_id="listStudioAgents", response_model=list[StudioAgentSummary])
def list_studio_agents(org_id: str, actor: CurrentActor) -> list[StudioAgentSummary]:
    """The agents the org built."""
    _live(org_id, actor)
    return studio.list_agents(actor)


@router.post(
    "/agents",
    operation_id="createStudioAgent",
    response_model=StudioAgent,
    status_code=201,
    responses=conflicts("KEY_TAKEN"),
)
def create_studio_agent(org_id: str, body: AgentDraft, actor: CurrentActor) -> StudioAgent:
    """Save a new agent (version 1). 422 INVALID_DEFINITION lists each problem; reviewers get 403."""
    _live(org_id, actor)
    return studio.create_agent(actor, body)


@router.post("/agents:validate", operation_id="validateStudioAgent", response_model=BuilderCheck)
def validate_studio_agent(org_id: str, body: AgentDraft, actor: CurrentActor) -> BuilderCheck:
    """Check an agent draft without saving it."""
    _live(org_id, actor)
    return studio.validate_agent(actor, body)


@router.get("/agents/{key}", operation_id="getStudioAgent", response_model=StudioAgent)
def get_studio_agent(org_id: str, key: StudioKey, actor: CurrentActor) -> StudioAgent:
    _live(org_id, actor)
    return studio.get_agent(actor, key)


@router.post(
    "/agents/{key}",
    operation_id="saveStudioAgent",
    response_model=StudioAgent,
    responses=conflicts("VERSION_CONFLICT", "KEY_TAKEN"),
)
def save_studio_agent(
    org_id: str, key: StudioKey, body: SaveAgentRequest, actor: CurrentActor
) -> StudioAgent:
    """Save the draft as the next version; an unchanged draft keeps the current one. 409 VERSION_CONFLICT when
    `baseVersion` is not the latest."""
    _live(org_id, actor)
    return studio.save_agent(actor, key, body)


@router.get("/packs", operation_id="listStudioPacks", response_model=list[StudioPackSummary])
def list_studio_packs(org_id: str, actor: CurrentActor) -> list[StudioPackSummary]:
    """The Workflow Packs the org built."""
    _live(org_id, actor)
    return studio.list_packs(actor)


@router.post(
    "/packs",
    operation_id="createStudioPack",
    response_model=StudioPack,
    status_code=201,
    responses=conflicts("KEY_TAKEN"),
)
def create_studio_pack(org_id: str, body: PackDraft, actor: CurrentActor) -> StudioPack:
    """Save a new pack (version 1), listed only in the org's own marketplace as built by its team. 422
    INVALID_DEFINITION lists each problem with the step it is about (`errors[].key`)."""
    _live(org_id, actor)
    return studio.create_pack(actor, body)


@router.post("/packs:validate", operation_id="validateStudioPack", response_model=BuilderCheck)
def validate_studio_pack(
    org_id: str, body: PackDraft, actor: CurrentActor, key: EditedKey = None
) -> BuilderCheck:
    """Check a pack draft without saving it. Pass `key` when the draft edits a saved pack; without it the
    draft is checked as a new pack, so a saved pack's own name reads as taken."""
    _live(org_id, actor)
    return studio.validate_pack(actor, body, key)


@router.post("/workflow:import", operation_id="importStudioWorkflow", response_model=ImportedWorkflow)
def import_studio_workflow(org_id: str, body: ImportWorkflowRequest, actor: CurrentActor) -> ImportedWorkflow:
    """Read a workflow.yaml as steps. Nothing is saved. 422 INVALID_YAML when it cannot be read."""
    _live(org_id, actor)
    return studio.import_workflow(actor, body)


# Registered before `/packs/{key}`, whose `{key}` would otherwise take "x:test".
@router.post(
    "/packs/{key}:test",
    operation_id="testStudioPack",
    response_model=Run,
    status_code=202,
    responses={
        **conflicts("PLATFORM_PAUSED", "SANDBOX_UNAVAILABLE", "SPEND_CAP", "PACK_UNAVAILABLE"),
        422: {
            "model": Problem,
            "description": f"{TITLES[422]} (INVALID_INPUT, BUDGET_REQUIRED, BUDGET_TOO_HIGH).",
        },
        503: {"model": Problem, "description": UNAVAILABLE},
    },
)
def test_studio_pack(org_id: str, key: StudioKey, body: SandboxRunRequest, actor: CurrentActor) -> Run:
    """Start a sandbox test run of the org's own pack (returns 202: started, not finished). It runs on sandbox
    data without adding the pack and is labelled as a sandbox test. The input must match the pack's input
    schema (422 INVALID_INPUT) and the budget the pack's maximum (422 BUDGET_TOO_HIGH); a pack without a
    maximum needs a budget (422 BUDGET_REQUIRED). The platform pause and the monthly spend cap apply."""
    _live(org_id, actor)
    _check_live_not_paused()
    return studio.sandbox_run(actor, key, body)


@router.get("/packs/{key}/workflow", operation_id="getStudioPackWorkflow", response_model=WorkflowYaml)
def get_studio_pack_workflow(org_id: str, key: StudioKey, actor: CurrentActor) -> WorkflowYaml:
    """The pack's workflow.yaml."""
    _live(org_id, actor)
    return studio.pack_workflow_yaml(actor, key)


@router.get("/packs/{key}", operation_id="getStudioPack", response_model=StudioPack)
def get_studio_pack(org_id: str, key: StudioKey, actor: CurrentActor) -> StudioPack:
    _live(org_id, actor)
    return studio.get_pack(actor, key)


@router.post(
    "/packs/{key}",
    operation_id="saveStudioPack",
    response_model=StudioPack,
    responses=conflicts("VERSION_CONFLICT", "KEY_TAKEN", "RUNS_IN_PROGRESS"),
)
def save_studio_pack(org_id: str, key: StudioKey, body: SavePackRequest, actor: CurrentActor) -> StudioPack:
    """Save the draft as the next version; an unchanged draft keeps the current one. 409 VERSION_CONFLICT when
    `baseVersion` is not the latest. A run already started keeps the version it pinned. A pack the org has
    added keeps its connection grants in step with the save, and cannot be renamed while one of its runs is
    in progress (409 RUNS_IN_PROGRESS)."""
    _live(org_id, actor)
    return studio.save_pack(actor, key, body)
