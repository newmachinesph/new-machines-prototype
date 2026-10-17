import secrets

from app import db, live_work, settings, workspace
from app.auth import Actor, CurrentActor
from app.errors import ApiProblem
from app.models.org import MemoryItem, MemorySpaceOption
from app.models.requests import AddMemoryRequest, MemoryReviewRequest
from app.routing import ApiRouter
from app.runtime.memory import READABLE_BY_ORG, SHARED_SOURCES
from app.store import get_store, iso, locked_store, utc_now

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


@router.get("/memory/spaces", operation_id="listMemorySpaces", response_model=list[MemorySpaceOption])
def list_memory_spaces(actor: CurrentActor) -> list[MemorySpaceOption]:
    """The memory spaces the org may add its own memory to: the ones it may read, by name."""
    return live_work.memory_spaces(actor.org_id)


# The fixture store holds items as the customer sees them, so a team item carries its label as its source.
TEAM_LABEL = live_work.SOURCES[live_work.TEAM_SOURCE]
DEMO_TEAM_LIMIT = 20  # team items the demo store keeps; the oldest goes when a newer one arrives


def _demo_memory(body: AddMemoryRequest, actor: Actor) -> MemoryItem:
    """The demo workspace keeps an added memory in the fixture store, in use at once."""
    name = live_work.space_name(body.space, live_work.readable_space(actor.org_id, body.space))
    item = MemoryItem(
        id=f"mem_{secrets.token_hex(6)}",
        text=body.text,
        scope="Organization",
        scope_name=name,
        state="APPROVED",
        source=TEAM_LABEL,
        proposed_by=actor.name or "You",
        created_at=utc_now(),
    )
    with locked_store() as store:
        store.memory.insert(0, item)  # newest first, so the last team item is the oldest
        team = [m for m in store.memory if m.source == TEAM_LABEL]
        if len(team) > DEMO_TEAM_LIMIT:
            store.memory.remove(team[-1])
    return item


@router.post("/memory", operation_id="addMemory", response_model=MemoryItem, status_code=201)
def add_memory(body: AddMemoryRequest, actor: CurrentActor) -> MemoryItem:
    """Add a memory of the org's own, in use from its agents' next run. Owners and admins only (403
    POLICY_DENIED); 422 for a space the org cannot read."""
    live_work.require_manager(actor)
    if workspace.live():
        return live_work.add_memory(actor, body.space, body.text)
    return _demo_memory(body, actor)


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
    """In the live workspace: retract one of the org's own items, so runs no longer recall it. What the team
    added, only an owner or admin retracts."""
    if workspace.live():
        return live_work.retract_memory(actor, memory_id)
    with locked_store():
        item = find_memory(memory_id)
        if item.source == TEAM_LABEL:
            live_work.require_manager(actor, "retract a memory added by your team")
        item.retracted = True
        return item
