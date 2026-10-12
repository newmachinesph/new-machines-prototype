from app.auth import CurrentActor
from app.errors import ApiProblem
from app.models.requests import SubmitReviewRequest
from app.models.work import Earning, HumanTask
from app.routing import ApiRouter
from app.store import get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["reviewers"])


def find_task(task_id: str) -> HumanTask:
    task = get_store().tasks.get(task_id)
    if task is None:
        raise ApiProblem(404, "NOT_FOUND", f"No task {task_id}.")
    return task


@router.get("/human-tasks/eligible", operation_id="listEligibleHumanTasks", response_model=list[HumanTask])
def list_eligible_human_tasks(_: CurrentActor) -> list[HumanTask]:
    # Offers show sanitized metadata only; records arrive with the task itself (API.md section 3).
    return [t.model_copy(update={"records": []}) for t in get_store().tasks.values() if t.state == "OFFERED"]


@router.get("/human-tasks/{task_id}", operation_id="getHumanTask", response_model=HumanTask)
def get_human_task(task_id: str, _: CurrentActor) -> HumanTask:
    return find_task(task_id)


@router.get("/reviewer/earnings", operation_id="listEarnings", response_model=list[Earning])
def list_earnings(_: CurrentActor) -> list[Earning]:
    return get_store().earnings


@router.post("/human-tasks/{task_id}:claim", operation_id="claimHumanTask", response_model=HumanTask)
def claim_human_task(task_id: str, _: CurrentActor) -> HumanTask:
    with locked_store():
        task = find_task(task_id)
        if task.state not in {"OFFERED", "EXPIRED", "CLAIMED"}:
            raise ApiProblem(409, "CONFLICT", "This task can no longer be claimed.")
        task.state = "CLAIMED"
        return task


@router.post("/human-tasks/{task_id}:submit", operation_id="submitHumanTask", response_model=HumanTask)
def submit_human_task(task_id: str, body: SubmitReviewRequest, _: CurrentActor) -> HumanTask:
    with locked_store():
        task = find_task(task_id)
        if task.state != "CLAIMED":
            raise ApiProblem(409, "CONFLICT", "Claim the task before submitting a review.")
        task.state = "SUBMITTED"
        return task
