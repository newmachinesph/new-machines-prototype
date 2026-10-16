"""Connector drivers: sandbox responses from definitions, live calls through Composio, calls to the
platform's MCP server (`driver: mcp`), or calls to an org's own MCP server (`transport: mcp`)."""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import settings
from app.defs import mcp_mapping, owners
from app.runtime import mcp

log = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
META_TOOL_PREFIX = "COMPOSIO_"  # Composio meta tools (multi-execute, remote bash, connections) never run
MCP_TRANSPORT = "mcp"  # connector `transport` of an org's own MCP server (`custom_mcp`)


_URL = re.compile(r"\w+://\S+")
_SAFE_MESSAGE_CHARS = 120


def safe_message(text: object, limit: int = _SAFE_MESSAGE_CHARS) -> str:
    """A short message fit for receipts: no URLs, one line, at most `limit` (default 120) characters."""
    cleaned = " ".join(_URL.sub("", str(text or "")).split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3].rstrip() + "..."
    return cleaned or "the tool call failed"


@dataclass
class ToolResult:
    ok: bool
    data: Any
    mocked: bool
    error: str | None = None


class SandboxDriver:
    """Returns a recorded response: the run's pack's own
    definitions/packs/<pack>/sandbox/<connector>/<tool id>.json when there is one, else the shared
    definitions/connectors/sandbox/<connector>/<tool id>.json. With `samples` (an org's own MCP connector) it
    answers each tool's `sample`, or `{"sandbox": true}`."""

    def __init__(
        self,
        root: Path | None = None,
        pack: str | None = None,
        packs_root: Path | None = None,
        samples: bool = False,
    ) -> None:
        self._root = root or settings.defs_dir() / "connectors" / "sandbox"
        self._packs_root = packs_root or settings.defs_dir() / "packs"
        self._pack = pack if pack and _SAFE_NAME.match(pack) else None
        self._samples = samples  # an org's own MCP connector: answer each tool's `sample`

    @property
    def pack(self) -> str | None:
        return self._pack

    def _path(self, connector: str, tool_id: str) -> Path:
        if self._pack is not None:
            own = self._packs_root / self._pack / "sandbox" / connector / f"{tool_id}.json"
            if own.is_file():
                return own
        return self._root / connector / f"{tool_id}.json"

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        if self._samples:
            sample = tool.get("sample")
            return ToolResult(
                ok=True, data=sample if isinstance(sample, dict) else {"sandbox": True}, mocked=True
            )
        tool_id = str(tool.get("id", ""))
        if not (_SAFE_NAME.match(connector) and _SAFE_NAME.match(tool_id)):
            return ToolResult(
                ok=False, data=None, mocked=True, error=f"invalid sandbox tool {connector}.{tool_id}"
            )
        path = self._path(connector, tool_id)
        if not path.is_file():
            return ToolResult(
                ok=False, data=None, mocked=True, error=f"no sandbox response for {connector}.{tool_id}"
            )
        return ToolResult(ok=True, data=json.loads(path.read_text(encoding="utf-8")), mocked=True)


class ComposioDriver:
    """Executes a connector tool's allowlisted Composio slug for one Composio user: the org's own (live
    workspace, with the connected account its connection row holds) or the demo user (DEMO_USER_UID)."""

    def __init__(self, client: Any = None, user_id: str | None = None, account_id: str | None = None) -> None:
        self._client = client
        self._user_id = user_id
        self._account_id = account_id

    @property
    def account_id(self) -> str | None:
        return self._account_id

    @property
    def client(self) -> Any:
        if self._client is None:
            from composio import Composio  # reads COMPOSIO_API_KEY from the environment

            self._client = Composio(allow_tracking=False)  # no SDK telemetry (call names, error text)
        return self._client

    @property
    def user_id(self) -> str:
        uid = self._user_id or settings.demo_user_uid()
        if not uid:
            raise RuntimeError("DEMO_USER_UID is not set")
        return uid

    def is_connected(self, toolkit: str) -> bool:
        accounts = self.client.connected_accounts.list(
            user_ids=[self.user_id], toolkit_slugs=[toolkit], statuses=["ACTIVE"], limit=1
        )
        return bool(accounts.items)

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        slug = str(tool.get("slug") or "")
        if not slug or slug.upper().startswith(META_TOOL_PREFIX):
            return ToolResult(ok=False, data=None, mocked=False, error=f"tool {slug!r} is not allowlisted")
        version = tool.get("version")
        account = {"connected_account_id": self._account_id} if self._account_id else {}
        try:
            response = self.client.tools.execute(
                slug,
                args,
                user_id=self.user_id,
                version=version,
                # Connector definitions may not pin a toolkit version; then the latest one runs.
                dangerously_skip_version_check=None if version else True,
                **account,
            )
        except Exception as exc:  # the SDK raises for transport/auth errors; report them as a failed call
            log.warning("composio %s.%s failed: %s", connector, tool.get("id"), type(exc).__name__)
            # SDK messages can carry request URLs and payloads, so receipts get the exception type only.
            error = f"{type(exc).__name__}: the {connector} call failed"
            return ToolResult(ok=False, data=None, mocked=False, error=error)
        # Composio wraps every result as {data, successful, error}; callers see the provider data only.
        if not response.get("successful"):
            return ToolResult(
                ok=False,
                data=response.get("data"),
                mocked=False,
                error=f"ToolError: {safe_message(response.get('error'))}",
            )
        return ToolResult(ok=True, data=response.get("data"), mocked=False)


PLATFORM_MCP_DRIVER = "mcp"  # connector `driver` whose tools run on the platform's MCP server (`mcp` mapping)
PLATFORM_LIVE = "live"  # a run's pinned answer from the platform's MCP server: its calls run on the server
PLATFORM_SANDBOX = "sandbox"  # ... or from sandbox data (`gateway.settle_platform_mcp`)
PROBE_TTL_S = 60.0  # how long `auto` mode trusts one answer of the server check
# Tools of the MongoDB MCP server known to only read. A server that lists any other tool was not started
# read-only (or is a newer server nobody has checked), so `auto` mode does not use it.
_READ_ONLY_TOOLS = frozenset(
    {
        "aggregate",
        "find",
        "count",
        "explain",
        "export",
        "db-stats",
        "mongodb-logs",
        "connect",
        "switch-connection",
        "search-knowledge",
    }
)
_READ_ONLY_PREFIXES = (
    "list-",
    "collection-",
    "atlas-list-",
    "atlas-get-",
    "atlas-inspect-",
    "atlas-local-list-",
)


def is_read_only_tool(name: str) -> bool:
    lowered = name.lower()
    return lowered in _READ_ONLY_TOOLS or lowered.startswith(_READ_ONLY_PREFIXES)


class PlatformMcpDriver:
    """Runs a `driver: mcp` connector tool on the MCP server NM_MCP_URL names (the MongoDB MCP server over
    streamable HTTP, read-only): the tool's `mcp` mapping has its `{{argument}}` placeholders filled from the
    call, the MCP tool it names is called, and a read answers `{result_key: documents}`. Writes are refused
    unless NM_MCP_WRITES is on (then a write answers its `result` template once the update matched). The
    mapping is checked here on every call, not only when the definition is published: a pinned run snapshot
    skips the publish-time checks. Receipts carry the failure's type and the connector, never server text."""

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        database: str | None = None,
        client: mcp.McpClient | None = None,
    ) -> None:
        self._client = client or mcp.McpClient(url or settings.mcp_url(), token=token or settings.mcp_token())
        self._database = database or settings.mcp_database()

    @property
    def database(self) -> str:
        return self._database

    def is_available(self) -> bool:
        """Whether the server answers `tools/list` now (the `auto` mode's check) and, with writes off, lists
        no write tool: a server that was not started read-only is not used."""
        try:
            names = self._client.list_tools()
        except Exception as exc:  # unreachable, refused, not an MCP endpoint: the caller falls back
            log.warning("mcp server check failed: %s", type(exc).__name__)
            return False
        if not names:
            return False
        if not settings.mcp_writes() and not all(is_read_only_tool(n) for n in names):
            log.error("mcp server check: the server lists tools that are not known to be read-only")
            return False
        return True

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        spec = tool.get("mcp")
        if not isinstance(spec, dict):
            return _failed(f"ConfigError: tool {connector}.{tool.get('id')} has no mcp mapping")
        if not self._client.configured:
            return _failed(f"ConfigError: the {connector} connection is not set up")
        action_class = tool.get("action_class")
        writes = settings.mcp_writes()
        refused = mcp_mapping.refusal(action_class, spec, writes_enabled=writes)
        if refused:
            log.error("mcp %s.%s refused: %s", connector, tool.get("id"), refused)
            return _failed(f"ConfigError: the {connector} call is not allowed")
        try:
            values = mcp.call_values(tool, args)
            arguments = mcp.arguments(spec, values, self._database)
        except mcp.PlaceholderError as exc:  # its text can name an argument the agent chose
            log.warning("mcp %s.%s mapping failed: PlaceholderError", connector, tool.get("id"))
            log.debug("mcp placeholder: %s", exc)
            return _failed(f"ConfigError: the {connector} call cannot be built from these arguments")
        except (TypeError, ValueError) as exc:  # an argument the mapping cannot take: never an uncaught error
            log.warning("mcp %s.%s mapping failed: %s", connector, tool.get("id"), type(exc).__name__)
            return _failed(f"ConfigError: the {connector} call cannot be built from these arguments")
        filled = mcp_mapping.refusal(action_class, {**arguments, "tool": spec["tool"]}, writes_enabled=writes)
        if filled:  # a filled mapping may still hold an operator or an empty write filter
            log.error("mcp %s.%s refused after filling: %s", connector, tool.get("id"), filled)
            return _failed(f"ConfigError: the {connector} call is not allowed")
        try:
            response = self._client.call_tool(str(spec["tool"]), arguments)
        except Exception as exc:  # transport, auth or protocol errors; their messages can carry the URL
            log.warning("mcp %s.%s failed: %s", connector, tool.get("id"), type(exc).__name__)
            return _failed(f"{type(exc).__name__}: the {connector} call failed")
        if getattr(response, "isError", False):
            # The server's text can carry its host, the database, the collection and query fragments.
            log.warning("mcp %s.%s: the tool answered an error", connector, tool.get("id"))
            kind = "read" if action_class == "read" else "write"
            return _failed(f"ToolError: the {connector} {kind} failed")
        try:
            data = mcp.shape(spec, response, values)
        except (mcp.ResultError, mcp.PlaceholderError) as exc:
            return _failed(f"ToolError: {safe_message(exc)}")
        return ToolResult(ok=True, data=data, mocked=False)


_probe_lock = threading.Lock()
_probe: dict[str, tuple[float, bool]] = {}  # server address -> (checked at, answered)


def reset_probe_cache() -> None:
    with _probe_lock:
        _probe.clear()


def platform_mcp_answers() -> bool:
    """Whether the platform's MCP server is set, answers and is read-only, from the check of the last
    PROBE_TTL_S seconds in this process (a flapping server must not make every call, forecast and catalog
    request open a session)."""
    url = settings.mcp_url()
    if not url:
        return False
    with _probe_lock:
        cached = _probe.get(url)
        if cached and time.monotonic() - cached[0] < PROBE_TTL_S:
            return cached[1]
    answered = PlatformMcpDriver(url=url).is_available()
    with _probe_lock:
        _probe[url] = (time.monotonic(), answered)
    return answered


NOT_CONNECTED = "NotConnected"  # error type: a live-workspace app with no usable connection
ROUTE_CHANGED = "RouteChanged"  # error type: the app's route is not the one pinned when the run started
TOOL_OFF = "ToolOff"  # error type: the org switched the MCP tool off since the run pinned it
SECRETS_UNAVAILABLE = "SecretsUnavailable"  # error type: the MCP server's token cannot be opened now


class UnconnectedDriver:
    """A live-workspace app with no usable connection (not connected, pending, or needing sign-in again):
    nothing runs, and the call fails with a plain reason. A real run never falls back to sandbox data."""

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        error = f"{NOT_CONNECTED}: {connector} is not connected"
        return ToolResult(ok=False, data=None, mocked=False, error=error)


class UnsettledDriver:
    """A platform MCP connector in `auto` mode whose run never settled live or sandbox at its start: nothing
    runs, and the call fails with a fixed reason, rather than probing the server per call."""

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        return _failed(f"ConfigError: the {connector} connection was not settled when the run started")


class RouteChangedDriver:
    """A live-workspace app reconnected another way (sandbox data, a real account, or another account) since
    the run started: nothing runs, so a run never mixes sandbox and real data or two accounts. `app` is the
    app's display name."""

    def __init__(self, app: str) -> None:
        self._app = app

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        error = f"{ROUTE_CHANGED}: {self._app}'s connection changed during this run"
        return ToolResult(ok=False, data=None, mocked=False, error=error)


def _failed(error: str) -> ToolResult:
    return ToolResult(ok=False, data=None, mocked=False, error=error)


class McpDriver:
    """Calls a tool on the org's own MCP server: the server the connection row names, with its token, under
    the server-address rules. The server must belong to the run's org. Nothing runs when the server was
    removed or the tool was switched off since the run pinned it. A failure to answer marks the server
    failing; an answer marks it active again."""

    def __init__(self, server_id: str, *, org_id: str) -> None:
        self._server_id = server_id
        self._org_id = org_id

    @property
    def server_id(self) -> str:
        return self._server_id

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        from app import mcp_servers, secrets_box  # the database and the MCP client load only when used
        from app.custom_mcp import client, safety

        slug = str(tool.get("slug") or "")
        if not (self._server_id and self._org_id):
            return _failed(f"{NOT_CONNECTED}: {connector} is not connected")
        try:
            reach = mcp_servers.reach(self._server_id, connector, slug, org_id=self._org_id)
        except mcp_servers.ServerGone:
            return _failed(f"{NOT_CONNECTED}: {connector} is not connected")
        except mcp_servers.ToolOff:
            return _failed(f"{TOOL_OFF}: {slug} is switched off")
        except secrets_box.SecretsUnavailable, secrets_box.SecretUnreadable:
            log.error("mcp %s: the token cannot be opened", self._server_id)
            return _failed(f"{SECRETS_UNAVAILABLE}: the {connector} token cannot be read right now")
        try:
            outcome = client.call_tool(reach.url, reach.header_name, reach.token, slug, args)
        except safety.UrlRefused as refused:
            if str(refused) == mcp_servers.BAD_HEADER_REASON:  # the stored header or token is unusable
                log.error("mcp %s: the stored header or token cannot be sent", self._server_id)
                return _failed(f"{SECRETS_UNAVAILABLE}: the {connector} token cannot be read right now")
            mcp_servers.note_failure(self._server_id, mcp_servers.ADDRESS_REFUSED)
            return _failed(f"UrlRefused: the {connector} server address is not allowed")
        except client.McpUnreachable as exc:
            log.warning("mcp %s.%s failed: %s", connector, tool.get("id"), exc)
            mcp_servers.note_failure(self._server_id, mcp_servers.UNREACHABLE)
            return _failed(f"McpUnreachable: the {connector} server did not answer")
        mcp_servers.note_answer(self._server_id)
        if not outcome.ok:
            return _failed(f"ToolError: {safe_message(outcome.message)}")
        return ToolResult(ok=True, data=outcome.data, mocked=False)


def is_route_changed(result: ToolResult | None) -> bool:
    """Whether a call failed because its app's route is not the one pinned when the run started."""
    return result is not None and not result.ok and str(result.error or "").startswith(f"{ROUTE_CHANGED}:")


def driver_for(
    connector_def: dict,
    mode: str,
    pack: str | None = None,
    tool: dict | None = None,
    *,
    key: str | None = None,
    platform_mcp: str | None = None,
) -> SandboxDriver | ComposioDriver | UnconnectedDriver | PlatformMcpDriver:
    """`connector_def` is the connector body. mode: sandbox | live | auto (live if connected). `pack` is the
    run's pack key, for its own sandbox data. An org's own MCP server is reached only through the org's
    connection (`gateway._route_driver`): a run that is not routed answers from samples, or runs nothing
    in live mode. A `driver: mcp` connector runs on the platform's MCP server instead of Composio (`auto`:
    when NM_MCP_URL is set and the server answers), except that a `tool` of its without an `mcp` mapping
    (its writes, with the server read-only) answers from its sandbox response in every mode. A run settles
    `auto` once, when it starts, and pins the answer (`platform_mcp`: "live" or "sandbox"), so a server
    that flaps never mixes live and sandbox data in one run. Only a platform connector `key` (one with no
    `--` namespace) may use the platform's server."""
    if mode not in ("sandbox", "auto", "live"):
        raise ValueError(f"unknown connector mode {mode!r}")
    if connector_def.get("transport") == MCP_TRANSPORT:
        return UnconnectedDriver() if mode == "live" else SandboxDriver(pack=pack, samples=True)
    if mode == "sandbox":
        return SandboxDriver(pack=pack)
    if connector_def.get("driver") == PLATFORM_MCP_DRIVER:
        if key is not None and owners.is_reserved(key):  # an org's or developer's connector never gets it
            return UnconnectedDriver()
        if tool is not None and tool.get("mcp") is None:
            return SandboxDriver(pack=pack)
        return _platform_mcp_driver_for(connector_def, mode, pack, platform_mcp)
    if mode == "live":
        return ComposioDriver()
    live = ComposioDriver()
    try:
        if live.is_connected(connector_def["toolkit"]):
            return live
    except Exception as exc:  # no key, no uid or Composio unreachable: fall back to labelled sandbox data
        log.warning(
            "composio connection check failed for %s: %s", connector_def.get("toolkit"), type(exc).__name__
        )
    return SandboxDriver(pack=pack)


def _platform_mcp_driver_for(
    connector_def: dict, mode: str, pack: str | None, pinned: str | None = None
) -> SandboxDriver | PlatformMcpDriver:
    if mode == "live" or pinned == PLATFORM_LIVE:  # a pinned "live" that fails later fails the call
        return PlatformMcpDriver()
    if pinned == PLATFORM_SANDBOX:
        return SandboxDriver(pack=pack)
    if platform_mcp_answers():
        return PlatformMcpDriver()
    if settings.mcp_url():
        log.warning("mcp server unavailable for %s: using sandbox data", connector_def.get("toolkit"))
    return SandboxDriver(pack=pack)
