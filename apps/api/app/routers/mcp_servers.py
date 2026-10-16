"""An org's own MCP servers (live workspace): owners and admins add, refresh, switch tools, replace the token
and remove; any member lists them."""

from typing import Annotated

from fastapi import Path, Response

from app import mcp_servers, workspace
from app.auth import Actor, CurrentActor
from app.errors import TITLES, ApiProblem, Problem, conflicts
from app.models.mcp import AddMcpServerRequest, McpServer, ReplaceMcpTokenRequest
from app.routers.org import _scope
from app.routing import ApiRouter

router = ApiRouter(prefix="/v1/organizations/{org_id}/mcp-servers", tags=["mcp-servers"])

LIVE_ONLY = "Your own MCP servers are part of the live workspace."
ServerId = Annotated[str, Path(pattern=r"^mcp_[0-9a-f]{12}$")]
ToolId = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
SERVER_PROBLEMS = {
    422: {
        "model": Problem,
        "description": f"{TITLES[422]} (MCP_UNREACHABLE, MCP_URL_REFUSED, MCP_NO_TOOLS).",
    },
    503: {
        "model": Problem,
        "description": "Tokens cannot be sealed or opened right now (SECRETS_UNAVAILABLE).",
    },
}


def _live(org_id: str, actor: Actor) -> None:
    if not workspace.live():
        raise ApiProblem(404, "NOT_FOUND", LIVE_ONLY)
    _scope(org_id, actor)


@router.get("", operation_id="listMcpServers", response_model=list[McpServer])
def list_mcp_servers(org_id: str, actor: CurrentActor) -> list[McpServer]:
    """The org's MCP servers that are not removed, with their sorted tools. Any member."""
    _live(org_id, actor)
    return mcp_servers.list_servers(actor)


@router.post(
    "",
    operation_id="addMcpServer",
    response_model=McpServer,
    status_code=201,
    responses={**conflicts("NAME_TAKEN"), **SERVER_PROBLEMS},
)
def add_mcp_server(org_id: str, body: AddMcpServerRequest, actor: CurrentActor) -> McpServer:
    """Connect the org's own MCP server: https only, on a public address. Its tools are listed and sorted into
    read (runs freely), write (asks first) and blocked (never offered), then published as a private connector
    for the org's Studio packs. Owners and admins."""
    _live(org_id, actor)
    return mcp_servers.add(actor, body)


@router.post(
    "/{server_id}:refresh",
    operation_id="refreshMcpServer",
    response_model=McpServer,
    responses=SERVER_PROBLEMS,
)
def refresh_mcp_server(org_id: str, server_id: ServerId, actor: CurrentActor) -> McpServer:
    """List the server's tools again; the connector gets a new version only when they changed."""
    _live(org_id, actor)
    return mcp_servers.refresh(actor, server_id)


@router.post("/{server_id}/tools/{tool_id}:off", operation_id="switchMcpToolOff", response_model=McpServer)
def switch_mcp_tool_off(org_id: str, server_id: ServerId, tool_id: ToolId, actor: CurrentActor) -> McpServer:
    """Switch one tool off: packs can no longer use it."""
    _live(org_id, actor)
    return mcp_servers.switch_tool(actor, server_id, tool_id, False)


@router.post(
    "/{server_id}/tools/{tool_id}:on",
    operation_id="switchMcpToolOn",
    response_model=McpServer,
    responses=conflicts("TOOL_BLOCKED"),
)
def switch_mcp_tool_on(org_id: str, server_id: ServerId, tool_id: ToolId, actor: CurrentActor) -> McpServer:
    """Switch one tool back on. A blocked tool cannot be switched on (409 TOOL_BLOCKED)."""
    _live(org_id, actor)
    return mcp_servers.switch_tool(actor, server_id, tool_id, True)


@router.post(
    "/{server_id}:replace-token",
    operation_id="replaceMcpServerToken",
    response_model=McpServer,
    responses=SERVER_PROBLEMS,
)
def replace_mcp_server_token(
    org_id: str, server_id: ServerId, body: ReplaceMcpTokenRequest, actor: CurrentActor
) -> McpServer:
    """Replace the token, once the server lists its tools with the new one."""
    _live(org_id, actor)
    return mcp_servers.replace_token(actor, server_id, body.token)


@router.delete("/{server_id}", operation_id="removeMcpServer", status_code=204, response_class=Response)
def remove_mcp_server(org_id: str, server_id: ServerId, actor: CurrentActor) -> Response:
    """Remove the server: its token is deleted and its connection is no longer connected. Runs already
    started keep the connector version they pinned, but their calls fail."""
    _live(org_id, actor)
    mcp_servers.remove(actor, server_id)
    return Response(status_code=204)
