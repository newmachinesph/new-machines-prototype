from fastapi import Response

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
def list_connections(_: CurrentActor) -> list[Connection]:
    return get_store().connections


@router.post(
    "/connections/{app_name}:disconnect", operation_id="disconnectConnection", response_model=Connection
)
def disconnect_connection(app_name: str, _: CurrentActor) -> Connection:
    with locked_store():
        conn = find_connection(app_name)
        conn.status = "not_connected"
        conn.grants = []
        return conn


@router.delete("/grants", operation_id="revokeGrant", status_code=204, response_class=Response)
def revoke_grant(app: str, install: str, capability: str, _: CurrentActor) -> Response:
    with locked_store():
        conn = find_connection(app)
        before = len(conn.grants)
        conn.grants = [g for g in conn.grants if not (g.install == install and g.capability == capability)]
        if len(conn.grants) == before:
            raise ApiProblem(404, "NOT_FOUND", "No such grant.")
    return Response(status_code=204)
