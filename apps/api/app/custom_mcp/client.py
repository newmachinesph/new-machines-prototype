"""Talking to an org's own MCP server over streamable HTTP (the `mcp` package's client). Each session obeys
`custom_mcp.safety`: the address is checked and pinned once, redirects are not followed, every response is
capped, and the whole session gives up after TIMEOUT_S. Errors carry no address, token or server text, except
a tool's own error text, which callers shorten with `drivers.safe_message`. Sync callers (API handlers, worker
activities) are served on a fresh event loop in a helper thread."""

import json
import re
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import anyio
import anyio.to_thread
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, PaginatedRequestParams, TextContent, Tool

from app import mcp_logging  # noqa: F401  (quiets the SDK and httpx loggers on import)
from app.custom_mcp import safety
from app.custom_mcp.tools import MAX_TOOLS, ListedTool

TIMEOUT_S = 30.0
MAX_PAGES = 20  # tools/list pages read at most


class McpUnreachable(Exception):
    """The server did not answer as an MCP server: no answer, an HTTP error or a redirect, too slow,
    too large, or not MCP. The message is the failure's type name only."""


@dataclass(frozen=True)
class CallOutcome:
    ok: bool
    data: Any
    message: str | None = None  # a failed tool's own error text


HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}$")
HEADER_TOKEN = re.compile(r"^[!-~]{1,4096}$")
RESERVED_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "accept-encoding",
        "content-encoding",
        "te",
        "upgrade",
        "keep-alive",
        "proxy-authorization",
        "cookie",
        "mcp-session-id",
        "mcp-protocol-version",
        "content-type",
        "accept",
        "last-event-id",
        "expect",
        "trailer",
        "proxy-connection",
    }
)
RESERVED_PREFIX = "mcp-"


def is_reserved_header(name: str) -> bool:
    """A header the client sets itself or that would change the request: never the token's carrier."""
    lowered = name.lower()
    return lowered in RESERVED_HEADERS or lowered.startswith(RESERVED_PREFIX)


def auth_headers(header_name: str, token: str) -> dict[str, str]:
    """`Authorization: Bearer <token>`, or the token as it is in any other header. UrlRefused("bad_header")
    when the name is not an RFC 9110 token or is one the client sets itself, or the token is not 1-4096
    visible ASCII characters."""
    if (
        not HEADER_NAME.fullmatch(header_name)
        or is_reserved_header(header_name)
        or not HEADER_TOKEN.fullmatch(token)
    ):
        raise safety.UrlRefused("bad_header")
    if header_name.lower() == "authorization":
        return {"Authorization": f"Bearer {token}"}
    return {header_name: token}


def _inner_transport() -> httpx.AsyncBaseTransport:
    """The network under the pinning and the cap. The tests hand requests to a local server instead."""
    return httpx.AsyncHTTPTransport(retries=0)


def http_client(
    target: safety.Target, headers: dict[str, str], on_too_large: Callable[[], None] | None = None
) -> httpx.AsyncClient:
    transport = safety.CappedTransport(
        safety.PinnedTransport(target, _inner_transport()), on_exceed=on_too_large
    )
    return httpx.AsyncClient(
        transport=transport,
        headers={**headers, "Accept-Encoding": "identity"},
        timeout=httpx.Timeout(TIMEOUT_S),
        follow_redirects=False,
        max_redirects=0,
    )


def _leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaves(inner)]
    return [exc]


def _run[T](url: str, header_name: str, token: str, work: Callable[[ClientSession], Awaitable[T]]) -> T:
    headers = auth_headers(header_name, token)

    async def session() -> T:
        with anyio.fail_after(TIMEOUT_S):  # the address lookup counts against the same deadline
            try:
                target = await anyio.to_thread.run_sync(safety.target, url, abandon_on_cancel=True)
            except OSError:
                raise McpUnreachable("NameResolutionError") from None
            # The MCP client swallows an error raised while it reads a body and then waits for the deadline,
            # so a body over the cap cancels the whole session from here instead.
            with anyio.CancelScope() as guard:
                async with (
                    http_client(target, headers, guard.cancel) as http,
                    streamable_http_client(url, http_client=http) as (read, write, _),
                    ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=TIMEOUT_S)
                    ) as mcp_session,
                ):
                    await mcp_session.initialize()
                    return await work(mcp_session)
            raise McpUnreachable("ResponseTooLarge")

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(anyio.run, session).result()
    except Exception as exc:
        leaves = _leaves(exc)
        refused = next((e for e in leaves if isinstance(e, safety.UrlRefused)), None)
        if refused is not None:
            raise refused from None
        unreachable = next((e for e in leaves if isinstance(e, McpUnreachable)), None)
        if unreachable is not None:
            raise unreachable from None
        raise McpUnreachable(type(leaves[0]).__name__) from None


def _listed(tool: Tool) -> ListedTool:
    hints = tool.annotations
    return ListedTool(
        name=tool.name,
        description=tool.description or "",
        input_schema=tool.inputSchema,
        output_schema=tool.outputSchema,
        read_only=hints.readOnlyHint if hints else None,
        destructive=hints.destructiveHint if hints else None,
    )


def list_tools(url: str, header_name: str, token: str) -> list[ListedTool]:
    """The server's tools: the first MAX_TOOLS it lists."""

    async def work(session: ClientSession) -> list[Tool]:
        found: list[Tool] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
            found.extend(page.tools)
            cursor = page.nextCursor
            if not cursor or len(found) >= MAX_TOOLS:
                break
        return found[:MAX_TOOLS]

    return [_listed(t) for t in _run(url, header_name, token, work)]


def _data(result: CallToolResult) -> Any:
    if result.structuredContent is not None:
        return result.structuredContent
    text = "\n".join(c.text for c in result.content if isinstance(c, TextContent))
    try:
        value = json.loads(text)
    except ValueError:
        return {"text": text}
    return value if isinstance(value, dict) else {"result": value}


def call_tool(url: str, header_name: str, token: str, name: str, args: dict[str, Any]) -> CallOutcome:
    """Call one tool. A result the server marks as an error is a failed outcome with its text."""

    async def work(session: ClientSession) -> CallToolResult:
        return await session.call_tool(name, args)

    result = _run(url, header_name, token, work)
    if result.isError:
        text = " ".join(c.text for c in result.content if isinstance(c, TextContent))
        return CallOutcome(ok=False, data=None, message=text or "the tool failed")
    return CallOutcome(ok=True, data=_data(result))
