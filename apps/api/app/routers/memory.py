from app import db, settings
from app.auth import CurrentActor
from app.defs.current import latest_bodies
from app.errors import ApiProblem
from app.models.org import MemoryItem
from app.models.requests import MemoryReviewRequest
from app.routing import ApiRouter
from app.store import get_store, iso, locked_store

router = ApiRouter(prefix="/v1", tags=["memory"])


def find_memory(memory_id: str) -> MemoryItem:
    item = next((m for m in get_store().memory if m.id == memory_id), None)
    if item is None:
        raise ApiProblem(404, "NOT_FOUND", f"No memory {memory_id}.")
    return item


REAL_ITEMS_LIMIT = 200
SOURCES = {"seed": "Definitions seed"}


def _readable_spaces(org_id: str) -> dict[str, dict]:
    """Memory space definitions this org may read: `readers` lists "*" or the org id."""
    return {
        key: body
        for key, body in latest_bodies("memory_space").items()
        if {"*", org_id} & set(body.get("readers") or [])
    }


def _real_memory(org_id: str) -> list[MemoryItem]:
    spaces = _readable_spaces(org_id)
    if not spaces:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, space, text, source, created_by, created_at FROM memory_items "
            "WHERE space = ANY(%s) ORDER BY created_at DESC, id DESC LIMIT %s",
            (list(spaces), REAL_ITEMS_LIMIT),
        ).fetchall()
    return [
        MemoryItem(
            id=r["id"],
            text=r["text"],
            scope="Organization",
            scope_name=str(spaces[r["space"]].get("name") or r["space"]),
            state="APPROVED",
            source=SOURCES.get(r["source"], r["source"]),
            proposed_by=r["created_by"],
            created_at=iso(r["created_at"]),
        )
        for r in rows
    ]


@router.get("/memory", operation_id="listMemory", response_model=list[MemoryItem])
def list_memory(actor: CurrentActor) -> list[MemoryItem]:
    """Fixture memory, after the items of real memory spaces when the runtime is on."""
    real = _real_memory(actor.org_id) if settings.runtime_enabled() else []
    return real + get_store().memory


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
