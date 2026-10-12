from app.auth import CurrentActor
from app.errors import ApiProblem
from app.models.org import MemoryItem
from app.models.requests import MemoryReviewRequest
from app.routing import ApiRouter
from app.store import get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["memory"])


def find_memory(memory_id: str) -> MemoryItem:
    item = next((m for m in get_store().memory if m.id == memory_id), None)
    if item is None:
        raise ApiProblem(404, "NOT_FOUND", f"No memory {memory_id}.")
    return item


@router.get("/memory", operation_id="listMemory", response_model=list[MemoryItem])
def list_memory(_: CurrentActor) -> list[MemoryItem]:
    return get_store().memory


@router.post(
    "/memory-candidates/{memory_id}:review", operation_id="reviewMemoryCandidate", response_model=MemoryItem
)
def review_memory_candidate(memory_id: str, body: MemoryReviewRequest, _: CurrentActor) -> MemoryItem:
    with locked_store():
        item = find_memory(memory_id)
        if item.state != "CANDIDATE":
            raise ApiProblem(409, "CONFLICT", "Only candidates can be reviewed.")
        if body.decision == "reject":
            item.state = "REJECTED"
            return item
        item.state = "APPROVED"
        if body.text:
            item.text = body.text
        if item.conflicts_with:
            find_memory(item.conflicts_with).state = "CORRECTED"
        return item


@router.post("/memory/{memory_id}:retract", operation_id="retractMemory", response_model=MemoryItem)
def retract_memory(memory_id: str, _: CurrentActor) -> MemoryItem:
    with locked_store():
        item = find_memory(memory_id)
        item.retracted = True
        return item
