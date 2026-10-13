from app import db, live_work, settings, workspace
from app.auth import CurrentActor
from app.errors import ApiProblem
from app.models.org import MemoryItem
from app.models.requests import MemoryReviewRequest
from app.routing import ApiRouter
from app.runtime.memory import READABLE_BY_ORG, SHARED_SOURCES
from app.store import get_store, iso, locked_store

router = ApiRouter(prefix="/v1", tags=["memory"])


def find_memory(memory_id: str) -> MemoryItem:
    item = next((m for m in get_store().memory if m.id == memory_id), None)
    if item is None:
        raise ApiProblem(404, "NOT_FOUND", f"No memory {memory_id}.")
    return item


REAL_ITEMS_LIMIT = 200


def _real_memory(org_id: str) -> list[MemoryItem]:
    spaces = live_work.readable_spaces(org_id)
    if not spaces:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, space, text, source, created_by, created_at FROM memory_items "
            f"WHERE space = ANY(%(spaces)s) AND {READABLE_BY_ORG} AND status <> 'quarantined' "
            "ORDER BY created_at DESC, id DESC LIMIT %(limit)s",
            {
                "spaces": list(spaces),
                "org": org_id,
                "shared": list(SHARED_SOURCES),
                "limit": REAL_ITEMS_LIMIT,
            },
        ).fetchall()
    return [
        MemoryItem(
            id=r["id"],
            text=r["text"],
            scope="Organization",
            scope_name=str(spaces[r["space"]].get("name") or r["space"]),
            state="APPROVED",
            source=live_work.source_label(r["source"])[0],
            proposed_by=r["created_by"],
            created_at=iso(r["created_at"]),
        )
        for r in rows
    ]


@router.get("/memory", operation_id="listMemory", response_model=list[MemoryItem])
def list_memory(actor: CurrentActor) -> list[MemoryItem]:
    """Fixture memory, after the items of real memory spaces when the runtime is on. The live workspace has
    the org's own items and the shared seed and console items only."""
    if workspace.live():
        return live_work.list_memory(actor.org_id)
    real = _real_memory(actor.org_id) if settings.runtime_enabled() else []
    return real + get_store().memory


@router.post(
    "/memory-candidates/{memory_id}:review", operation_id="reviewMemoryCandidate", response_model=MemoryItem
)
def review_memory_candidate(memory_id: str, body: MemoryReviewRequest, actor: CurrentActor) -> MemoryItem:
    if workspace.live():
        if live_work.memory_exists(actor.org_id, memory_id):
            raise ApiProblem(409, "CONFLICT", "Only candidates can be reviewed.")
        raise ApiProblem(404, "NOT_FOUND", f"No memory {memory_id}.")
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
def retract_memory(memory_id: str, actor: CurrentActor) -> MemoryItem:
    """In the live workspace: retract one of the org's own items, so runs no longer recall it."""
    if workspace.live():
        return live_work.retract_memory(actor, memory_id)
    with locked_store():
        item = find_memory(memory_id)
        item.retracted = True
        return item
