"""MCP connectors: the mapping a `driver: mcp` connector tool carries (`mcp`: the MCP tool to call, a
collection and a query or update with `{{argument}}` placeholders), one streamable-HTTP session per call
through the official SDK, and the Extended JSON the MongoDB MCP server answers with turned into plain JSON."""

import asyncio
import json
import re
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

CONNECTION_ID = "preconfigured"  # the MongoDB MCP server's name for the connection string it was started with
NOW = "now"  # the one built-in placeholder: the call time, ISO-8601 UTC with milliseconds (an EJSON `$date`)
# The `mcp` fields handed to the MCP tool as arguments, after their placeholders are filled.
ARGUMENT_FIELDS = ("pipeline", "filter", "projection", "limit", "update")
DOCUMENTS = "documents"  # the key the server's find and aggregate results carry their documents under
MATCHED = "matchedCount"  # the key an update result counts the documents it applied to under
APPLIED_LIMITS = "appliedLimits"  # the server names the limits that cut a read short here
TIMEOUT_S = 120.0  # one call's HTTP timeout; a window of orders takes well under that

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_WHOLE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
_WRAPPED = re.compile(r"<untrusted-user-data-[^>]*>(.*?)</untrusted-user-data-[^>]*>", re.DOTALL)
_ISO_SECONDS = "%Y-%m-%dT%H:%M:%SZ"


class PlaceholderError(ValueError):
    """A placeholder names no argument of the call."""


class ResultError(ValueError):
    """The server answered, but not with a result the mapping can shape."""


# --- placeholders -----------------------------------------------------------------------------------


def placeholders(value: Any) -> set[str]:
    """The names of every `{{placeholder}}` in a nested value's strings (dict keys included)."""
    if isinstance(value, str):
        return set(_PLACEHOLDER.findall(value))
    if isinstance(value, dict):
        return set().union(*(placeholders(k) | placeholders(v) for k, v in value.items()))
    if isinstance(value, list):
        return set().union(*(placeholders(v) for v in value))
    return set()


def render(value: Any, values: dict) -> Any:
    """`value` with every `{{name}}` placeholder filled from `values`: a string that is one placeholder
    becomes the value itself (its JSON type kept), one embedded in text its text. An unknown name is an
    error."""
    if isinstance(value, str):
        whole = _WHOLE.match(value)
        if whole:
            return values[_lookup(whole.group(1), values)]
        return _PLACEHOLDER.sub(lambda m: _text(values[_lookup(m.group(1), values)]), value)
    if isinstance(value, dict):
        return {render(k, values): render(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, values) for v in value]
    return value


def _lookup(name: str, values: dict) -> str:
    if name not in values:
        raise PlaceholderError(f"argument {name!r} was not given")
    return name


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def call_values(tool: dict, args: dict) -> dict:
    """What a call's placeholders can name: the call time (`now`), then the defaults of the tool's input
    schema, then the arguments given."""
    properties = (tool.get("input_schema") or {}).get("properties") or {}
    defaults = {name: prop["default"] for name, prop in properties.items() if "default" in prop}
    now = datetime.now(UTC)
    return {NOW: now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z", **defaults, **args}


def arguments(spec: dict, values: dict, database: str) -> dict:
    """The MCP tool's arguments: the server's preconfigured connection, the database, the mapping's collection
    and its query or update fields with their placeholders filled."""
    out: dict = {"connectionId": CONNECTION_ID, "database": database, "collection": spec["collection"]}
    for field in ARGUMENT_FIELDS:
        if field in spec:
            out[field] = render(spec[field], values)
    return out


# --- results ----------------------------------------------------------------------------------------


def plain(value: Any) -> Any:
    """Extended JSON as plain JSON: `{"$date": ...}` to an ISO-8601 UTC string (seconds), the wrapped numbers
    to numbers, `{"$oid": ...}` to its string; everything else is walked unchanged."""
    if isinstance(value, dict):
        if len(value) == 1:
            key, inner = next(iter(value.items()))
            if key == "$date":
                return _iso(inner)
            if key in ("$numberInt", "$numberLong"):
                return int(inner)
            if key in ("$numberDouble", "$numberDecimal"):
                return float(inner)
            if key == "$oid":
                return str(inner)
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


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
    """The documents a find or aggregate result carries: its structured content when the server sends one,
    else the JSON array (or one EJSON document per line) inside its text."""
    structured = structured_of(result)
    if structured is not None and isinstance(structured.get(DOCUMENTS), list):
        return plain(structured[DOCUMENTS])
    for block in getattr(result, "content", None) or []:
        text = str(getattr(block, "text", "") or "")
        wrapped = _WRAPPED.search(text)
        parsed = _parse_documents((wrapped.group(1) if wrapped else text).strip())
        if parsed is not None:
            return plain(parsed)
    raise ResultError("the result carries no documents")


def _parse_documents(text: str) -> list | None:
    """A JSON array, one JSON document, or one document per line; None when the text is not JSON."""
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        try:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        except ValueError:
            return None
    if isinstance(parsed, list):
        return parsed
    return [parsed] if isinstance(parsed, dict) else None


def applied_limits(result: Any) -> list[str]:
    """The server limits that cut a read short (`config.maxDocumentsPerQuery`, ...), empty when none did."""
    structured = structured_of(result) or {}
    limits = structured.get(APPLIED_LIMITS)
    return [str(x) for x in limits] if isinstance(limits, list) else []


def shape(spec: dict, result: Any, values: dict) -> Any:
    """A call's data in the connector's shape: a read answers `{result_key: documents}`, a write its `result`
    template filled from the call values once the update matched a document (else the server's own counts)."""
    if "result_key" in spec:
        limits = applied_limits(result)
        if limits:
            raise ResultError(f"the server returned only part of the result ({', '.join(limits)})")
        return {spec["result_key"]: documents_of(result)}
    structured = structured_of(result) or {}
    if structured.get(MATCHED) == 0:
        raise ResultError("the update matched no document")
    return render(spec["result"], values) if "result" in spec else plain(structured)


# --- transport --------------------------------------------------------------------------------------


class McpClient:
    """One MCP session per call over streamable HTTP: initialize, the request, close. `token`, when given,
    goes as a bearer token. The SDK is async; a call runs on its own event loop (on a helper thread when the
    calling thread already runs one)."""

    def __init__(self, url: str | None, token: str | None = None, timeout_s: float = TIMEOUT_S) -> None:
        self._url = url
        self._token = token
        self._timeout_s = timeout_s

    @property
    def configured(self) -> bool:
        return bool(self._url)

    def list_tools(self) -> list[str]:
        return self._run(self._list_tools())

    def call_tool(self, name: str, arguments: dict) -> Any:
        """The SDK's CallToolResult: `isError`, `content` blocks and `structuredContent`."""
        return self._run(self._call_tool(name, arguments))

    @asynccontextmanager
    async def _session(self):
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        if not self._url:
            raise RuntimeError("NM_MCP_URL is not set")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else None
        timeout = httpx.Timeout(self._timeout_s, read=self._timeout_s)
        async with (
            create_mcp_http_client(headers=headers, timeout=timeout) as http,
            streamable_http_client(self._url, http_client=http) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    async def _list_tools(self) -> list[str]:
        async with self._session() as session:
            listed = await session.list_tools()
            return [t.name for t in listed.tools]

    async def _call_tool(self, name: str, arguments: dict) -> Any:
        async with self._session() as session:
            return await session.call_tool(name, arguments)

    @staticmethod
    def _run(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        outcome: dict = {}

        def runner() -> None:
            try:
                outcome["value"] = asyncio.run(coro)
            except BaseException as exc:  # re-raised on the calling thread
                outcome["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]
