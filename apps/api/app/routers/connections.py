from typing import Annotated

from fastapi import Body, Response

from app import live_connections, workspace
from app.auth import CurrentActor
from app.errors import ApiProblem, Problem, conflicts
from app.models.org import Connection, ConnectRequest, ConnectStarted
from app.routing import ApiRouter
from app.store import get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["connections"])

SERVICE_RESPONSES = {
    503: {
        "model": Problem,
        "description": "The connection service did not answer (CONNECTION_SERVICE_UNAVAILABLE).",
    }
}


def find_connection(app_name: str) -> Connection:
    found = next((c for c in get_store().connections if c.app == app_name), None)
    if found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No connection for {app_name}.")
    return found


@router.get("/connections", operation_id="listConnections", response_model=list[Connection])
def list_connections(actor: CurrentActor) -> list[Connection]:
    """In the live workspace: the apps used by the packs the org added, connected or not."""
    if workspace.live():
        return live_connections.list_connections(actor.org_id)
    return get_store().connections


@router.post(
    "/connections/{app_name}:connect",
    operation_id="connectConnection",
    response_model=ConnectStarted,
    responses={**conflicts("CONFLICT", "LIVE_CONNECT_UNAVAILABLE", "NO_LIVE_TOOLKIT"), **SERVICE_RESPONSES},
)
def connect_connection(
    app_name: str, actor: CurrentActor, body: Annotated[ConnectRequest, Body(default_factory=ConnectRequest)]
) -> ConnectStarted:
    """Connect an app (a connector key or app name) for the org. `mode: sandbox` (the default) connects it to
    sandbox data. `mode: live` starts signing in to the org's own account: the connection is pending and
    `redirectUrl` is the app's sign-in page, which returns to the web's Connections page; only an owner or
    admin may, and only they may switch an app connected to the org's own account to sandbox data (403
    FORBIDDEN otherwise). The demo workspace has none to make (409)."""
    if not workspace.live():
        raise ApiProblem(409, "CONFLICT", "The demo workspace's apps are already set up.")
    if body.mode == "live":
        live_connections.require_real_account_role(actor.role)
        return live_connections.connect_live(actor.org_id, actor.user_id, app_name)
    made = live_connections.connect_sandbox(actor.org_id, actor.user_id, app_name, actor.role)
    return ConnectStarted.model_validate(made.model_dump())


@router.post(
    "/connections/{app_name}:sync",
    operation_id="syncConnection",
    response_model=Connection,
    responses={**conflicts("CONFLICT", "LIVE_CONNECT_UNAVAILABLE"), **SERVICE_RESPONSES},
)
def sync_connection(app_name: str, actor: CurrentActor) -> Connection:
    """Live workspace: check the org's own account for an app with Composio, after the person comes back from
    signing in. Connected when the account is active, with the grants of the packs that use the app; not
    connected (or needing sign-in again) when the sign-in failed or expired; still pending while it is in
    progress. The demo workspace has nothing to sync (409)."""
    if not workspace.live():
        raise ApiProblem(409, "CONFLICT", "The demo workspace's apps are already set up.")
    return live_connections.sync(actor.org_id, app_name)


@router.post(
    "/connections/{app_name}:disconnect", operation_id="disconnectConnection", response_model=Connection
)
def disconnect_connection(app_name: str, actor: CurrentActor) -> Connection:
    """Disconnect an app: every pack the org added loses access to it. In the live workspace, an app
    connected to the org's own account (mode composio, whatever its status) is only disconnected by an owner
    or admin (403 FORBIDDEN otherwise); its account is removed at the connection service."""
    if workspace.live():
        return live_connections.disconnect(actor.org_id, app_name, actor.role)
    with locked_store():
        conn = find_connection(app_name)
        conn.status = "not_connected"
        conn.grants = []
        return conn


@router.delete("/grants", operation_id="revokeGrant", status_code=204, response_class=Response)
def revoke_grant(app: str, install: str, capability: str, actor: CurrentActor) -> Response:
    """Revoke one grant: the pack (`install`) may no longer use the `capability` of the `app`. In the live
    workspace only an owner or admin may (403 FORBIDDEN otherwise), and the revocation is remembered until
    it is allowed again."""
    if workspace.live():
        live_connections.require_real_account_role(actor.role)
        live_connections.revoke_grant(actor.org_id, app, install, capability)
        return Response(status_code=204)
    with locked_store():
        conn = find_connection(app)
        before = len(conn.grants)
        conn.grants = [g for g in conn.grants if not (g.install == install and g.capability == capability)]
        if len(conn.grants) == before:
            raise ApiProblem(404, "NOT_FOUND", "No such grant.")
    return Response(status_code=204)


@router.post("/grants", operation_id="allowGrant", response_model=Connection, responses=conflicts("CONFLICT"))
def allow_grant(app: str, install: str, capability: str, actor: CurrentActor) -> Connection:
    """Live workspace: allow a grant a person revoked again (the same `app`, `install` and `capability` as
    revoking it). The revocation is forgotten, and the grant comes back when a pack the org added still uses
    the capability; 404 when the org's connection holds no such revocation. Only an owner or admin may (403
    FORBIDDEN otherwise). The demo workspace remembers no revocations (409)."""
    if not workspace.live():
        raise ApiProblem(409, "CONFLICT", "The demo workspace's grants cannot be allowed again.")
    live_connections.require_real_account_role(actor.role)
    return live_connections.allow_grant(actor.org_id, app, install, capability)
