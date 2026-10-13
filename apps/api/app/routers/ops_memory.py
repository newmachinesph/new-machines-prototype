"""Operator console: memory spaces (defined as `memory_space` definitions) and their items."""

from app import db, ops_state, workspace
from app.auth import CurrentOps, OpsActor, OpsWriter
from app.defs import registry
from app.errors import ApiProblem
from app.models.ops import AddMemoryItemRequest, MemorySpace, MemorySpaceItem, ReasonRequest
from app.routers.ops_params import PathId
from app.routers.ops_runtime import RUNTIME_RESPONSES, require_runtime
from app.routing import ApiRouter
from app.runtime import memory
from app.store import locked_store

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

CONSOLE_SOURCE = "console"
SUMMARY_TEXT_MAX = 80


def require_space(conn, space: str) -> None:
    if registry.latest(conn, "memory_space", space) is None:
        raise ApiProblem(404, "NOT_FOUND", f"No memory space {space}.")


def _clip(text: str) -> str:
    return text if len(text) <= SUMMARY_TEXT_MAX else text[: SUMMARY_TEXT_MAX - 1] + "…"


def _audit_live(conn, actor: OpsActor, action: str, item_id: str, reason: str, summary: str) -> bool:
    """In the live workspace, audit in the write's own transaction (before its commit). False in the demo,
    which audits in the store instead."""
    if not workspace.live():
        return False
    data = {"summary": summary}
    ops_state.audit(conn, actor.email, action, "memory", item_id, reason, data, actor_role=actor.role)
    return True


@router.get(
    "/memory/spaces",
    operation_id="opsListMemorySpaces",
    response_model=list[MemorySpace],
    responses=RUNTIME_RESPONSES,
)
def ops_list_memory_spaces(_: CurrentOps) -> list[MemorySpace]:
    """Every memory space definition with its item count."""
    require_runtime()
    with db.connect() as conn:
        counts = {
            r["space"]: r["n"]
            for r in conn.execute("SELECT space, count(*) AS n FROM memory_items GROUP BY space").fetchall()
        }
        spaces = [v for v in registry.latest_all(conn) if v.kind == "memory_space"]
    return [
        MemorySpace(
            key=v.key,
            name=str(v.body.get("name") or v.key),
            description=str(v.body.get("description") or ""),
            item_count=counts.get(v.key, 0),
            version=v.version,
        )
        for v in spaces
    ]


@router.get(
    "/memory/spaces/{space}/items",
    operation_id="opsListMemoryItems",
    response_model=list[MemorySpaceItem],
    responses=RUNTIME_RESPONSES,
)
def ops_list_memory_items(space: PathId, _: CurrentOps) -> list[MemorySpaceItem]:
    """The space's items, newest first."""
    require_runtime()
    with db.connect() as conn:
        require_space(conn, space)
        return [MemorySpaceItem(**item) for item in memory.list_items(conn, space)]


@router.post(
    "/memory/spaces/{space}/items",
    operation_id="opsAddMemoryItem",
    response_model=MemorySpaceItem,
    status_code=201,
    responses=RUNTIME_RESPONSES,
)
def ops_add_memory_item(space: PathId, body: AddMemoryItemRequest, actor: OpsWriter) -> MemorySpaceItem:
    """Add an item (1 to 2000 characters) to a space. The space must exist as a definition."""
    require_runtime()
    with db.connect() as conn:
        require_space(conn, space)
        item = memory.remember(conn, space, body.text, CONSOLE_SOURCE, actor.email)
        summary = f"Added to {space}: {_clip(body.text)}"
        live = _audit_live(conn, actor, "memory.add", item["id"], body.reason, summary)
        conn.commit()
    if not live:
        with locked_store() as store:
            store.audit(actor, "memory.add", "memory", item["id"], body.reason, summary)
    return MemorySpaceItem(**item)


@router.post(
    "/memory/items/{item_id}:delete",
    operation_id="opsDeleteMemoryItem",
    status_code=204,
    responses=RUNTIME_RESPONSES,
)
def ops_delete_memory_item(item_id: PathId, body: ReasonRequest, actor: OpsWriter) -> None:
    """Remove one item from its space."""
    require_runtime()
    with db.connect() as conn:
        row = conn.execute("SELECT space, text FROM memory_items WHERE id = %s", (item_id,)).fetchone()
        if row is None or not memory.delete_item(conn, item_id):
            raise ApiProblem(404, "NOT_FOUND", f"No memory item {item_id}.")
        summary = f"Removed from {row['space']}: {_clip(row['text'])}"
        live = _audit_live(conn, actor, "memory.delete", item_id, body.reason, summary)
        conn.commit()
    if not live:
        with locked_store() as store:
            store.audit(actor, "memory.delete", "memory", item_id, body.reason, summary)
