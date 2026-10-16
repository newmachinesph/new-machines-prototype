"""MCP connectors: the mapping a `driver: mcp` connector tool carries (`mcp`: the MCP tool to call, a
collection and a query or update with `{{argument}}` placeholders), one streamable-HTTP session per call
through the official SDK, and the Extended JSON the MongoDB MCP server answers with turned into plain JSON.
The session obeys one total deadline, a response size cap and no redirects; errors carry the failure's type
name only, never the address, the token or the server's text."""

import json
import logging
import math
import re
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams

from app import mcp_logging  # noqa: F401  (quiets the SDK and httpx loggers on import)
from app.custom_mcp.safety import CappedTransport
from app.defs.mcp_mapping import ARGUMENT_FIELDS, NOW, PLACEHOLDER, key_placeholders, placeholders

__all__ = ["ARGUMENT_FIELDS", "NOW", "placeholders"]

CONNECTION_ID = "preconfigured"  # the MongoDB MCP server's name for the connection string it was started with
DOCUMENTS = "documents"  # the key the server's find and aggregate results carry their documents under
MATCHED = "matchedCount"  # the key an update result counts the documents it applied to under
APPLIED_LIMITS = "appliedLimits"  # the server names the limits that cut a read short here
# One total deadline per session (initialize and the request together). A tool-call activity times out at
# 45 s (`worker.workflow._TOOL_TIMEOUT`), so the call has to end well inside that.
PROBE_TIMEOUT_S = 5.0  # `tools/list`, the check that the server answers
CALL_TIMEOUT_S = 25.0  # one tool call
MAX_PAGES = 5  # tools/list pages read at most
# The operator chooses this URL, so it is not pinned to public addresses; the response size is still capped.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024  # a window of 2000 orders is about 2 MB

_WHOLE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
_ISO_SECONDS = "%Y-%m-%dT%H:%M:%SZ"


log = logging.getLogger(__name__)


class PlaceholderError(ValueError):
    """A placeholder names no argument of the call, or the mapping or an argument uses one wrongly."""


class ResultError(ValueError):
    """The server answered, but not with a result the mapping can shape."""


class McpError(Exception):
    """The server did not answer as expected: no answer, an HTTP error, too slow, too large, or not MCP. The
    message is the failure's type name only."""


# --- placeholders -----------------------------------------------------------------------------------


def render(value: Any, values: dict) -> Any:
    """`value` with every `{{name}}` placeholder filled from `values`: a string that is one placeholder
    becomes the value itself (its JSON type kept), one embedded in text its text. An unknown name is an
    error, and so is a placeholder in a dict key: a key names a field or an operator, and an argument must
    never choose one."""
    if isinstance(value, str):
        whole = _WHOLE.match(value)
        if whole:
            return values[_lookup(whole.group(1), values)]
        return PLACEHOLDER.sub(lambda m: _text(values[_lookup(m.group(1), values)]), value)
    if isinstance(value, dict):
        if any(PLACEHOLDER.search(str(k)) for k in value):
            raise PlaceholderError("a placeholder cannot stand in a field name")
        return {k: render(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, values) for v in value]
    return value


def _lookup(name: str, values: dict) -> str:
    if name not in values:
        raise PlaceholderError(f"argument {name!r} was not given")
    return name


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _plain_argument(name: str, value: Any) -> None:
    """An argument is data, never query structure: no object (it could carry operators) and no string that
    starts with `$` (an operator or a field path), also inside a list."""
    if isinstance(value, dict):
        raise PlaceholderError(f"argument {name!r} cannot be an object")
    if isinstance(value, str) and value.startswith("$"):
        raise PlaceholderError(f"argument {name!r} cannot start with '$'")
    if isinstance(value, float) and not math.isfinite(value):
        raise PlaceholderError(f"argument {name!r} must be a finite number")
    if isinstance(value, list):
        for item in value:
            _plain_argument(name, item)


def call_values(tool: dict, args: dict) -> dict:
    """What a call's placeholders can name: the defaults of the tool's input schema, then the arguments
    given, then the call time (`now`), which an argument cannot override. Raises PlaceholderError for an
    argument that is an object or starts with `$`."""
    properties = (tool.get("input_schema") or {}).get("properties") or {}
    defaults = {name: prop["default"] for name, prop in properties.items() if "default" in prop}
    given = {**defaults, **args}
    for name, value in given.items():
        _plain_argument(str(name), value)
    now = datetime.now(UTC)
    return {**given, NOW: now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"}


def arguments(spec: dict, values: dict, database: str) -> dict:
    """The MCP tool's arguments: the server's preconfigured connection, the database, the mapping's collection
    and its query or update fields with their placeholders filled."""
    if key_placeholders(spec):
        raise PlaceholderError("a placeholder cannot stand in a field name")
    out: dict = {"connectionId": CONNECTION_ID, "database": database, "collection": spec["collection"]}
    for field in ARGUMENT_FIELDS:
        if field in spec:
            out[field] = render(spec[field], values)
    return out


# --- results ----------------------------------------------------------------------------------------


def plain(value: Any) -> Any:
    """Extended JSON as plain JSON: `{"$date": ...}` to an ISO-8601 UTC string (seconds), the wrapped numbers
    to numbers (a decimal stays text, so no precision is lost), `{"$oid": ...}` to its string; everything
    else is walked unchanged. NaN and Infinity are a ResultError."""
    if isinstance(value, dict):
        if len(value) == 1:
            key, inner = next(iter(value.items()))
            if key == "$date":
                return _iso(inner)
            if key in ("$numberInt", "$numberLong"):
                return int(inner)
            if key == "$numberDouble":
                return _finite(float(inner))
            if key == "$numberDecimal":
                _finite(float(inner))
                return str(inner)
            if key == "$oid":
                return str(inner)
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, float):
        return _finite(value)
    return value


def _finite(number: float) -> float:
    if not math.isfinite(number):
        raise ResultError("the result holds a number that is not finite")
    return number


def _iso(inner: Any) -> str | None:
    """A `$date` body (ISO text, milliseconds or `{"$numberLong": ms}`) as ISO-8601 UTC, second precision."""
    if isinstance(inner, dict):
        inner = inner.get("$numberLong")
    if isinstance(inner, str) and not inner.lstrip("-").isdigit():
        parsed = datetime.fromisoformat(inner.replace("Z", "+00:00"))
        parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).strftime(_ISO_SECONDS)
    if inner is None:
        return None
    return datetime.fromtimestamp(int(inner) / 1000, tz=UTC).strftime(_ISO_SECONDS)


def text_of(result: Any) -> str:
    """The text blocks of a call result, joined: what an error result says."""
    return " ".join(str(getattr(c, "text", "")) for c in (getattr(result, "content", None) or []))


def structured_of(result: Any) -> dict | None:
    structured = getattr(result, "structuredContent", None)
    return structured if isinstance(structured, dict) else None


def documents_of(result: Any) -> list:
    """The documents a find or aggregate result carries in its structured content. A result without it is
    refused, not read from its text: the text would skip `appliedLimits`."""
    structured = structured_of(result)
    if structured is None or not isinstance(structured.get(DOCUMENTS), list):
        raise ResultError("the result carries no documents")
    return plain(structured[DOCUMENTS])


def applied_limits(result: Any) -> list[str]:
    """The server limits that cut a read short (`config.maxDocumentsPerQuery`, ...), empty when none did."""
    structured = structured_of(result) or {}
    limits = structured.get(APPLIED_LIMITS)
    return [str(x) for x in limits] if isinstance(limits, list) else []


def shape(spec: dict, result: Any, values: dict) -> Any:
    """A call's data in the connector's shape: a read answers `{result_key: documents}`, a write its `result`
    template filled from the call values once the update matched at least one document (else the server's
    own counts). A result that cannot be shaped is a ResultError, never another exception."""
    try:
        if "result_key" in spec:
            limits = applied_limits(result)
            if limits:
                log.debug("mcp read cut short by: %s", ", ".join(limits))
                raise ResultError("the server returned only part of the result")
            return {spec["result_key"]: documents_of(result)}
        structured = structured_of(result)
        if structured is None:
            raise ResultError("the update answered without a result")
        matched = structured.get(MATCHED)
        if not isinstance(matched, int) or isinstance(matched, bool) or matched < 1:
            raise ResultError("the update matched no document")
        return render(spec["result"], values) if "result" in spec else plain(structured)
    except ResultError, PlaceholderError:
        raise
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        raise ResultError(f"the result cannot be read ({type(exc).__name__})") from None


# --- transport --------------------------------------------------------------------------------------


def _leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaves(inner)]
    return [exc]


class McpClient:
    """One MCP session per call over streamable HTTP: initialize, the request, close, all inside one deadline
    (`probe_timeout_s` for the tool list, `call_timeout_s` for a call). `token`, when given, goes as a bearer
    token. Redirects are not followed and a response past MAX_RESPONSE_BYTES (or a compressed one) ends the
    session. The SDK is async; each session runs on its own event loop in a helper thread, so the caller may
    be sync code or already inside a loop. Every failure is an McpError naming only the failure's type."""

    def __init__(
        self,
        url: str | None,
        token: str | None = None,
        *,
        probe_timeout_s: float = PROBE_TIMEOUT_S,
        call_timeout_s: float = CALL_TIMEOUT_S,
    ) -> None:
        self._url = url
        self._token = token
        self._probe_timeout_s = probe_timeout_s
        self._call_timeout_s = call_timeout_s

    @property
    def configured(self) -> bool:
        return bool(self._url)

    def list_tools(self) -> list[str]:
        """The names of the server's tools."""

        async def work(session: ClientSession) -> list[str]:
            names: list[str] = []
            cursor: str | None = None
            for _ in range(MAX_PAGES):
                params = PaginatedRequestParams(cursor=cursor) if cursor else None
                page = await session.list_tools(params=params)
                names.extend(t.name for t in page.tools)
                cursor = page.nextCursor
                if not cursor:
                    return names
            # Names past the last page are unseen, so the write-tool check could not vouch for them.
            raise McpError("TooManyPages")

        return self._run(self._probe_timeout_s, work)

    def call_tool(self, name: str, arguments: dict) -> Any:
        """The SDK's CallToolResult: `isError`, `content` blocks and `structuredContent`."""

        async def work(session: ClientSession) -> Any:
            return await session.call_tool(name, arguments)

        return self._run(self._call_timeout_s, work)

    def _http_client(self, on_too_large: Callable[[], None]) -> httpx.AsyncClient:
        headers = {"Accept-Encoding": "identity"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        transport = CappedTransport(
            httpx.AsyncHTTPTransport(retries=0), limit=MAX_RESPONSE_BYTES, on_exceed=on_too_large
        )
        return httpx.AsyncClient(
            transport=transport,
            headers=headers,
            follow_redirects=False,
            max_redirects=0,  # the SDK follows same-origin redirects up to this many
            timeout=httpx.Timeout(None),
        )

    def _run[T](self, deadline_s: float, work: Callable[[ClientSession], Awaitable[T]]) -> T:
        if not self._url:
            raise McpError("NotConfigured")
        url = self._url

        async def session() -> T:
            with anyio.fail_after(deadline_s):
                # The MCP client swallows an error raised while it reads a body and then waits for the
                # deadline, so a body over the cap cancels the whole session from here instead.
                with anyio.CancelScope() as guard:
                    async with (
                        self._http_client(guard.cancel) as http,
                        streamable_http_client(url, http_client=http) as (read, write, _),
                        ClientSession(
                            read, write, read_timeout_seconds=timedelta(seconds=deadline_s)
                        ) as mcp_session,
                    ):
                        await mcp_session.initialize()
                        return await work(mcp_session)
                raise McpError("ResponseTooLarge")

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(anyio.run, session).result()
        except Exception as exc:
            leaves = _leaves(exc)
            known = next((e for e in leaves if isinstance(e, McpError)), None)
            if known is not None:
                raise known from None
            raise McpError(type(leaves[0]).__name__) from None
