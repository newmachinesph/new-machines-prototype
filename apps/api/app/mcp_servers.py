"""An org's own MCP servers, connected as custom connectors (live workspace). Adding one lists its tools under
the server-address rules (`custom_mcp.safety`), sorts them (`custom_mcp.tools`), seals the token
(`secrets_box`), publishes an org-owned connector definition with `transport: mcp`, and writes the org's
`connections` row (mode 'mcp', its account id the server id), which is what runs route through.

Owners and admins change servers; any member lists them. The token is never returned, logged or shown again.
No lock is held while a server answers. Lock order: the org's MCP lock, its server row, the registry, then
the (org, app) lock and the connection row."""

import logging
import secrets
from dataclasses import dataclass, field, replace
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

import psycopg.errors
from psycopg.types.json import Jsonb

from app import db, live_connections, secrets_box, workspace
from app.auth import Actor
from app.custom_mcp import client, safety, tools
from app.defs import owners, registry
from app.defs.model import Bundle, Definition, path_for
from app.defs.validate import validate_bundle
from app.errors import ApiProblem
from app.models.mcp import AddMcpServerRequest, McpServer, McpTool

log = logging.getLogger(__name__)

ID_PREFIX = "mcp_"
KEY_TRIES = 99
SUFFIX_ROOM = 3  # "-99"
MANAGERS = workspace.INVITER_ROLES
REMOVED = "removed"
UNREACHABLE, ADDRESS_REFUSED = "unreachable", "address_refused"  # mcp_servers.last_error

FORBIDDEN_DETAIL = "Only an owner or admin can change the org's MCP servers."
UNREACHABLE_DETAIL = (
    "The server did not answer as an MCP server. Check the address and the token, then try again."
)
URL_REFUSED_DETAIL = "This address cannot be used. Use an https address on the public internet."
NO_TOOLS_DETAIL = "The server lists no tools your packs can use."
NAME_TAKEN_DETAIL = "You already have a server with this name. Choose another name."
TOOL_BLOCKED_DETAIL = "A blocked tool cannot be switched on."
SECRETS_DETAIL = "Your own MCP servers cannot be connected right now. Try again later."
BAD_HEADER_REASON = "bad_header"
BAD_HEADER_DETAIL = "headerName: not a header name or token this server connection can use"
NOT_FOUND_DETAIL = "There is no MCP server with this id."
NO_TOOL_DETAIL = "This server has no tool with this id."

_COLUMNS = (
    "id, org_id, connector_key, name, url, header_name, token_ciphertext, token_last4, status, tools, "
    "tools_listed_at, last_error, created_at"
)


@dataclass(frozen=True)
class ServerRow:
    id: str
    org_id: str
    connector_key: str
    name: str
    url: str
    header_name: str
    token_ciphertext: bytes | None
    token_last4: str | None
    status: str
    tools: list[dict]
    tools_listed_at: datetime | None
    last_error: str | None
    created_at: datetime


@dataclass(frozen=True)
class Reach:
    """What one call needs. Never log it: it holds the token."""

    url: str
    header_name: str
    token: str = field(repr=False)


class ServerGone(Exception):
    """The server was removed, or does not back this connector."""


class ToolOff(Exception):
    """The tool is switched off, blocked, or no longer listed."""


def _row(r: dict) -> ServerRow:
    sealed = r["token_ciphertext"]
    return ServerRow(
        **{
            **r,
            "token_ciphertext": bytes(sealed) if sealed is not None else None,
            "tools": list(r["tools"] or []),
        }
    )


def _sorted(server: ServerRow) -> list[tools.SortedTool]:
    return [tools.SortedTool.from_stored(t) for t in server.tools]


def shown_url(url: str) -> str:
    """The address without its query or fragment, which may hold a key."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _shown(server: ServerRow) -> McpServer:
    listed = _sorted(server)
    return McpServer(
        id=server.id,
        name=server.name,
        url=shown_url(server.url),
        header_name=server.header_name,
        token_last4=server.token_last4,
        status=server.status,
        connector_key=server.connector_key,
        tool_count=len(tools.usable(listed)),
        tools=[
            McpTool(
                id=t.id, name=t.name, description=t.description, tool_class=t.tool_class, why=t.why, on=t.on
            )
            for t in listed
        ],
        tools_listed_at=server.tools_listed_at,
        last_error=server.last_error,
        created_at=server.created_at,
    )


def _require_manager(actor: Actor) -> None:
    if actor.role not in MANAGERS:
        raise ApiProblem(403, "FORBIDDEN", FORBIDDEN_DETAIL)


def _secrets_problem() -> ApiProblem:
    return ApiProblem(503, "SECRETS_UNAVAILABLE", SECRETS_DETAIL)


def _require_key() -> None:
    try:
        secrets_box.require_key()
    except secrets_box.SecretsUnavailable:
        log.error("NM_SECRETS_KEY is missing or unusable: MCP servers cannot be connected")
        raise _secrets_problem() from None


def _seal(token: str, server_id: str) -> bytes:
    try:
        return secrets_box.seal(token, server_id)
    except secrets_box.SecretsUnavailable:
        raise _secrets_problem() from None


def _token(server: ServerRow) -> str:
    if server.token_ciphertext is None:
        raise ApiProblem(404, "NOT_FOUND", NOT_FOUND_DETAIL)
    try:
        return secrets_box.open_sealed(server.token_ciphertext, server.id)
    except secrets_box.SecretsUnavailable, secrets_box.SecretUnreadable:
        log.error("The token of MCP server %s cannot be opened with NM_SECRETS_KEY", server.id)
        raise _secrets_problem() from None


def _listed(url: str, header_name: str, token: str, server_id: str | None = None) -> list[tools.ListedTool]:
    """The server's tools, or a 422 problem. With `server_id`, a failure also marks that server failing."""
    try:
        return client.list_tools(url, header_name, token)
    except safety.UrlRefused as refused:
        if str(refused) == BAD_HEADER_REASON:  # the request models stop these first
            raise ApiProblem(422, "SCHEMA_INVALID", BAD_HEADER_DETAIL) from None
        problem, code = ApiProblem(422, "MCP_URL_REFUSED", URL_REFUSED_DETAIL), ADDRESS_REFUSED
    except client.McpUnreachable:
        problem, code = ApiProblem(422, "MCP_UNREACHABLE", UNREACHABLE_DETAIL), UNREACHABLE
    if server_id is not None:
        note_failure(server_id, code)
    raise problem


def _with_tools(sorted_tools: list[tools.SortedTool]) -> list[tools.SortedTool]:
    """422 MCP_NO_TOOLS unless at least one tool is not blocked."""
    if not any(t.tool_class != "blocked" for t in sorted_tools):
        raise ApiProblem(422, "MCP_NO_TOOLS", NO_TOOLS_DETAIL)
    return sorted_tools


def _lock_org(conn, org_id: str) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"mcp:{org_id}",))


def _find(conn, org_id: str, server_id: str, *, lock: bool = False) -> ServerRow:
    sql = f"SELECT {_COLUMNS} FROM mcp_servers WHERE id = %s AND org_id = %s AND status <> 'removed'"
    row = conn.execute(sql + (" FOR UPDATE" if lock else ""), (server_id, org_id)).fetchone()
    if row is None:
        raise ApiProblem(404, "NOT_FOUND", NOT_FOUND_DETAIL)
    return _row(row)


def _name_taken(conn, org_id: str, name: str) -> bool:
    """Another live server of the org has the name, or a connector the org may see that is not its own (a
    platform app) is called that, so names never shadow each other in the connections views."""
    folded = name.casefold()
    rows = conn.execute(
        "SELECT name FROM mcp_servers WHERE org_id = %s AND status <> 'removed'", (org_id,)
    ).fetchall()
    if any(str(r["name"]).casefold() == folded for r in rows):
        return True
    return any(
        v.kind == "connector"
        and not owners.in_org(v.key, org_id)
        and str(v.body.get("app") or "").casefold() == folded
        for v in registry.latest_visible(conn, org_id)
    )


def _free_key(conn, org_id: str, name: str) -> str:
    """The org's first connector key for `name` that no live server holds: <namespace>--<slug>, then -2..."""
    rows = conn.execute(
        "SELECT connector_key FROM mcp_servers WHERE org_id = %s AND status <> 'removed'", (org_id,)
    ).fetchall()
    taken = {r["connector_key"] for r in rows}
    base = owners.slugify(name)[: owners.NAME_MAX - SUFFIX_ROOM].rstrip("-")
    for n in range(1, KEY_TRIES + 1):
        key = owners.org_key(org_id, base if n == 1 else f"{base}-{n}")
        if key not in taken:
            return key
    raise ApiProblem(409, "NAME_TAKEN", NAME_TAKEN_DETAIL)


def _publish(
    conn, actor_id: str, server: ServerRow, sorted_tools: list[tools.SortedTool], reason: str
) -> None:
    """Publish the server's connector when it changed (a run in progress keeps the version it pinned)."""
    body = tools.connector_body(server.name, server.id, sorted_tools, owners.name_of(server.connector_key))
    key = server.connector_key
    d = Definition(kind="connector", key=key, body=body, path=path_for("connector", key))
    if errors := validate_bundle(Bundle(items={("connector", key): d})):
        raise RuntimeError(f"the connector of MCP server {server.id} is invalid: {errors[0].message}")
    registry.publish_if_changed(conn, d, actor_id, reason, source=registry.BUILDER)


def _regrant(conn, org_id: str, key: str) -> None:
    connectors = {v.key: v.body for v in registry.latest_visible(conn, org_id) if v.kind == "connector"}
    live_connections.regrant(conn, connectors, org_id, {key})


def _connect(conn, actor: Actor, server: ServerRow) -> None:
    """The org's connection to the server's connector: connected, mode mcp, account id the server id. Grants
    come from the packs the org added (a revoked one stays revoked)."""
    live_connections.lock_app(conn, actor.org_id, server.connector_key)
    conn.execute(
        "INSERT INTO connections (org_id, app, status, mode, grants, connected_by, account_id) "
        "VALUES (%s, %s, 'connected', 'mcp', '[]'::jsonb, %s, %s) ON CONFLICT (org_id, app) DO UPDATE SET "
        "status = 'connected', mode = 'mcp', grants = '[]'::jsonb, connected_by = EXCLUDED.connected_by, "
        "account_id = EXCLUDED.account_id, connected_at = now()",
        (actor.org_id, server.connector_key, actor.user_id, server.id),
    )
    _regrant(conn, actor.org_id, server.connector_key)


def _store_tools(conn, server: ServerRow, sorted_tools: list[tools.SortedTool], *, listed: bool) -> ServerRow:
    fresh = ", tools_listed_at = now(), status = 'active', last_error = NULL" if listed else ""
    row = conn.execute(
        f"UPDATE mcp_servers SET tools = %s{fresh} WHERE id = %s RETURNING {_COLUMNS}",
        (Jsonb([t.stored() for t in sorted_tools]), server.id),
    ).fetchone()
    return _row(row)


# --- the API ------------------------------------------------------------------------------------------------


def list_servers(actor: Actor) -> list[McpServer]:
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM mcp_servers WHERE org_id = %s AND status <> 'removed' "
            "ORDER BY created_at, id",
            (actor.org_id,),
        ).fetchall()
    return [_shown(_row(r)) for r in rows]


def live_server_ids(conn, org_id: str) -> set[str]:
    """The ids of the org's servers that are not removed."""
    rows = conn.execute(
        "SELECT id FROM mcp_servers WHERE org_id = %s AND status <> 'removed'", (org_id,)
    ).fetchall()
    return {r["id"] for r in rows}


def add(actor: Actor, body: AddMcpServerRequest) -> McpServer:
    """Connect a server: list and sort its tools, store it with its sealed token, publish its connector and
    connect it. 409 NAME_TAKEN, 422 MCP_URL_REFUSED / MCP_UNREACHABLE / MCP_NO_TOOLS,
    503 SECRETS_UNAVAILABLE."""
    _require_manager(actor)
    _require_key()
    with db.connect() as conn:
        if _name_taken(conn, actor.org_id, body.name):
            raise ApiProblem(409, "NAME_TAKEN", NAME_TAKEN_DETAIL)
    sorted_tools = _with_tools(tools.sort_tools(_listed(body.url, body.header_name, body.token)))
    server_id = f"{ID_PREFIX}{secrets.token_hex(6)}"
    sealed = _seal(body.token, server_id)
    with db.connect() as conn:
        _lock_org(conn, actor.org_id)
        if _name_taken(conn, actor.org_id, body.name):
            raise ApiProblem(409, "NAME_TAKEN", NAME_TAKEN_DETAIL)
        key = _free_key(conn, actor.org_id, body.name)
        registry.claim(conn, "connector", key, owners.org_owner(actor.org_id), actor.user_id)
        try:
            row = conn.execute(
                "INSERT INTO mcp_servers (id, org_id, connector_key, name, url, header_name, "
                "token_ciphertext, "
                "token_last4, tools, tools_listed_at, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s) "
                f"RETURNING {_COLUMNS}",
                (
                    server_id,
                    actor.org_id,
                    key,
                    body.name,
                    body.url,
                    body.header_name,
                    sealed,
                    secrets_box.last4(body.token),
                    Jsonb([t.stored() for t in sorted_tools]),
                    actor.user_id,
                ),
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise ApiProblem(409, "NAME_TAKEN", NAME_TAKEN_DETAIL) from None
        server = _row(row)
        _publish(conn, actor.user_id, server, sorted_tools, f"Connected the MCP server {body.name}")
        _connect(conn, actor, server)
        conn.commit()
    return _shown(server)


def refresh(actor: Actor, server_id: str) -> McpServer:
    """List the tools again. Switches and ids carry over by tool name; the connector gets a new version only
    when something changed. The re-sorted tools are always stored, even when none is left to use, so a tool
    that is now blocked stops being callable. A failure marks the server failing."""
    _require_manager(actor)
    _require_key()
    with db.connect() as conn:
        server = _find(conn, actor.org_id, server_id)
    listed = _listed(server.url, server.header_name, _token(server), server_id=server.id)
    with db.connect() as conn:
        _lock_org(conn, actor.org_id)
        current = _find(conn, actor.org_id, server_id, lock=True)
        sorted_tools = tools.sort_tools(listed, current.tools)  # all blocked is fine: it must be stored
        server = _store_tools(conn, current, sorted_tools, listed=True)
        _publish(conn, actor.user_id, server, sorted_tools, f"Refreshed the tools of {server.name}")
        _regrant(conn, actor.org_id, server.connector_key)
        conn.commit()
    return _shown(server)


def switch_tool(actor: Actor, server_id: str, tool_id: str, on: bool) -> McpServer:
    """Switch one tool on or off; a blocked tool cannot be switched on (409 TOOL_BLOCKED)."""
    _require_manager(actor)
    with db.connect() as conn:
        _lock_org(conn, actor.org_id)
        server = _find(conn, actor.org_id, server_id, lock=True)
        current = _sorted(server)
        found = next((t for t in current if t.id == tool_id), None)
        if found is None:
            raise ApiProblem(404, "NOT_FOUND", NO_TOOL_DETAIL)
        if on and found.tool_class == "blocked":
            raise ApiProblem(409, "TOOL_BLOCKED", TOOL_BLOCKED_DETAIL)
        changed = [replace(t, on=on, admin_off=not on) if t.id == tool_id else t for t in current]
        server = _store_tools(conn, server, changed, listed=False)
        _publish(conn, actor.user_id, server, changed, f"Switched {found.name} {'on' if on else 'off'}")
        _regrant(conn, actor.org_id, server.connector_key)
        conn.commit()
    return _shown(server)


def replace_token(actor: Actor, server_id: str, token: str) -> McpServer:
    """Replace the token once the server lists its tools with the new one (the old one stays otherwise)."""
    _require_manager(actor)
    _require_key()
    with db.connect() as conn:
        server = _find(conn, actor.org_id, server_id)
    _listed(server.url, server.header_name, token)
    sealed = _seal(token, server.id)
    with db.connect() as conn:
        _lock_org(conn, actor.org_id)
        _find(conn, actor.org_id, server_id, lock=True)
        row = conn.execute(
            "UPDATE mcp_servers SET token_ciphertext = %s, token_last4 = %s, status = 'active', "
            "last_error = NULL "
            f"WHERE id = %s RETURNING {_COLUMNS}",
            (sealed, secrets_box.last4(token), server.id),
        ).fetchone()
        conn.commit()
    return _shown(_row(row))


def remove(actor: Actor, server_id: str) -> None:
    """Forget the token, mark the server removed and its connection not connected, with no grants. The
    connector's versions stay for runs that pinned them; their calls now fail, and new runs cannot start."""
    _require_manager(actor)
    with db.connect() as conn:
        _lock_org(conn, actor.org_id)
        server = _find(conn, actor.org_id, server_id, lock=True)
        conn.execute(
            "UPDATE mcp_servers SET status = 'removed', token_ciphertext = NULL, token_last4 = NULL "
            "WHERE id = %s",
            (server.id,),
        )
        live_connections.lock_app(conn, actor.org_id, server.connector_key)
        conn.execute(
            "UPDATE connections SET status = 'not_connected', grants = '[]'::jsonb, account_id = NULL "
            "WHERE org_id = %s AND app = %s",
            (actor.org_id, server.connector_key),
        )
        conn.commit()


# --- runtime ------------------------------------------------------------------------------------------------


def reach(server_id: str, connector_key: str, slug: str, *, org_id: str) -> Reach:
    """What a call to tool `slug` of `connector_key` needs, read now. Raises ServerGone when the server was
    removed, belongs to another org (an empty `org_id` matches none) or backs another connector, ToolOff
    when the tool is not usable, and the secrets_box errors when the token cannot be opened."""
    with db.connect() as conn:
        row = conn.execute(f"SELECT {_COLUMNS} FROM mcp_servers WHERE id = %s", (server_id,)).fetchone()
    if row is None:
        raise ServerGone(server_id)
    server = _row(row)
    if server.status == REMOVED or server.connector_key != connector_key or server.token_ciphertext is None:
        raise ServerGone(server_id)
    if not org_id or server.org_id != org_id:
        raise ServerGone(server_id)
    tool = next((t for t in server.tools if t.get("name") == slug), None)
    if tool is None or not tool.get("on") or tool.get("tool_class") == "blocked":
        raise ToolOff(slug)
    return Reach(server.url, server.header_name, secrets_box.open_sealed(server.token_ciphertext, server.id))


def note_failure(server_id: str, code: str) -> None:
    """The server did not answer (`UNREACHABLE`) or its address was refused (`ADDRESS_REFUSED`)."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE mcp_servers SET status = 'failing', last_error = %s "
            "WHERE id = %s AND status <> 'removed'",
            (code, server_id),
        )
        conn.commit()


def note_answer(server_id: str) -> None:
    """A failing server answered again."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE mcp_servers SET status = 'active', last_error = NULL "
            "WHERE id = %s AND status = 'failing'",
            (server_id,),
        )
        conn.commit()
