from app.auth import CurrentActor
from app.errors import ApiProblem
from app.models.work import Approval
from app.routing import ApiRouter
from app.store import get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["approvals"])


def find_approval(approval_id: str) -> Approval:
    found = next((a for a in get_store().approvals if a.id == approval_id), None)
    if found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No approval {approval_id}.")
    return found


@router.get("/approvals", operation_id="listApprovals", response_model=list[Approval])
def list_approvals(_: CurrentActor) -> list[Approval]:
    return get_store().approvals


def _decide(approval_id: str, status: str) -> Approval:
    with locked_store():
        found = find_approval(approval_id)
        if found.status != "PENDING":
            raise ApiProblem(409, "CONFLICT", f"This approval is already {found.status.lower()}.")
        found.status = status
        return found


@router.post("/approvals/{approval_id}:approve", operation_id="approveApproval", response_model=Approval)
def approve_approval(approval_id: str, _: CurrentActor) -> Approval:
    return _decide(approval_id, "GRANTED")


@router.post("/approvals/{approval_id}:decline", operation_id="declineApproval", response_model=Approval)
def decline_approval(approval_id: str, _: CurrentActor) -> Approval:
    return _decide(approval_id, "DECLINED")
