from fastapi import Response

from app import live_connections, workspace
from app.auth import CurrentActor
from app.errors import ApiProblem
from app.models.org import Connection
from app.routing import ApiRouter
from app.store import get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["connections"])


def find_connection(app_name: str) -> Connection:
    found = next((c for c in get_store().connections if c.app == app_name), None)
    if found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No connection for {app_name}.")
    return found


@router.get("/connections", operation_id="listConnections", response_model=list[Connection])
def list_connections(actor: CurrentActor) -> list[Connection]:
    """In the live workspace: the apps the org's hired packs use, connected or not."""
    if workspace.live():
        return live_connections.list_connections(actor.org_id)
    return get_store().connections


@router.post("/connections/{app_name}:connect", operation_id="connectConnection", response_model=Connection)
def connect_connection(app_name: str, actor: CurrentActor) -> Connection:
    """Connect an app (a connector key or app name) for the org. Sandbox connector mode connects it to
    sandbox data; live app connections are not available yet (409). The demo workspace has none to make."""
    if not workspace.live():
        raise ApiProblem(409, "CONFLICT", "The demo workspace's apps are already set up.")
    return live_connections.connect(actor.org_id, actor.user_id, app_name)


@router.post(
    "/connections/{app_name}:disconnect", operation_id="disconnectConnection", response_model=Connection
)
def disconnect_connection(app_name: str, actor: CurrentActor) -> Connection:
    if workspace.live():
        return live_connections.disconnect(actor.org_id, app_name)
    with locked_store():
        conn = find_connection(app_name)
        conn.status = "not_connected"
        conn.grants = []
        return conn


@router.delete("/grants", operation_id="revokeGrant", status_code=204, response_class=Response)
def revoke_grant(app: str, install: str, capability: str, actor: CurrentActor) -> Response:
    if workspace.live():
        live_connections.revoke_grant(actor.org_id, app, install, capability)
        return Response(status_code=204)
    with locked_store():
        conn = find_connection(app)
        before = len(conn.grants)
        conn.grants = [g for g in conn.grants if not (g.install == install and g.capability == capability)]
        if len(conn.grants) == before:
            raise ApiProblem(404, "NOT_FOUND", "No such grant.")
    return Response(status_code=204)
