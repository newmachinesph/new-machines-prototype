"""Connector drivers: sandbox responses from definitions, or live calls through Composio or an MCP server."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import settings
from app.runtime import mcp

log = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
META_TOOL_PREFIX = "COMPOSIO_"  # Composio meta tools (multi-execute, remote bash, connections) never run


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
    definitions/connectors/sandbox/<connector>/<tool id>.json."""

    def __init__(
        self, root: Path | None = None, pack: str | None = None, packs_root: Path | None = None
    ) -> None:
        self._root = root or settings.defs_dir() / "connectors" / "sandbox"
        self._packs_root = packs_root or settings.defs_dir() / "packs"
        self._pack = pack if pack and _SAFE_NAME.match(pack) else None

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


MCP = "mcp"  # the connector `driver` whose tools run on an MCP server (`mcp` mapping per tool)


class McpDriver:
    """Runs a `driver: mcp` connector tool on the MCP server NM_MCP_URL names (the MongoDB MCP server over
    streamable HTTP): the tool's `mcp` mapping has its `{{argument}}` placeholders filled from the call, the
    MCP tool it names is called, and a read answers `{result_key: documents}` while a write answers its
    `result` template once the update matched. All mapping lives in the connector definition."""

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
        """Whether the server answers `tools/list` now (the `auto` mode's check)."""
        try:
            return bool(self._client.list_tools())
        except Exception as exc:  # unreachable, refused, not an MCP endpoint: the caller falls back
            log.warning("mcp server check failed: %s", type(exc).__name__)
            return False

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        spec = tool.get("mcp")
        if not isinstance(spec, dict):
            error = f"ConfigError: tool {connector}.{tool.get('id')} has no mcp mapping"
            return ToolResult(ok=False, data=None, mocked=False, error=error)
        if not self._client.configured:
            return ToolResult(ok=False, data=None, mocked=False, error="ConfigError: NM_MCP_URL is not set")
        values = mcp.call_values(tool, args)
        try:
            arguments = mcp.arguments(spec, values, self._database)
        except mcp.PlaceholderError as exc:
            return ToolResult(ok=False, data=None, mocked=False, error=f"ConfigError: {exc}")
        try:
            response = self._client.call_tool(str(spec["tool"]), arguments)
        except Exception as exc:  # transport, auth or protocol errors; their messages can carry the URL
            log.warning("mcp %s.%s failed: %s", connector, tool.get("id"), type(exc).__name__)
            error = f"{type(exc).__name__}: the {connector} call failed"
            return ToolResult(ok=False, data=None, mocked=False, error=error)
        if getattr(response, "isError", False):
            error = f"ToolError: {safe_message(mcp.text_of(response))}"
            return ToolResult(ok=False, data=None, mocked=False, error=error)
        try:
            data = mcp.shape(spec, response, values)
        except (mcp.ResultError, mcp.PlaceholderError) as exc:
            return ToolResult(ok=False, data=None, mocked=False, error=f"ToolError: {safe_message(exc)}")
        return ToolResult(ok=True, data=data, mocked=False)


NOT_CONNECTED = "NotConnected"  # error type: a live-workspace app with no usable connection
ROUTE_CHANGED = "RouteChanged"  # error type: the app's route is not the one pinned when the run started


class UnconnectedDriver:
    """A live-workspace app with no usable connection (not connected, pending, or needing sign-in again):
    nothing runs, and the call fails with a plain reason. A real run never falls back to sandbox data."""

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        error = f"{NOT_CONNECTED}: {connector} is not connected"
        return ToolResult(ok=False, data=None, mocked=False, error=error)


class RouteChangedDriver:
    """A live-workspace app reconnected another way (sandbox data, a real account, or another account) since
    the run started: nothing runs, so a run never mixes sandbox and real data or two accounts. `app` is the
    app's display name."""

    def __init__(self, app: str) -> None:
        self._app = app

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        error = f"{ROUTE_CHANGED}: {self._app}'s connection changed during this run"
        return ToolResult(ok=False, data=None, mocked=False, error=error)


def is_route_changed(result: ToolResult | None) -> bool:
    """Whether a call failed because its app's route is not the one pinned when the run started."""
    return result is not None and not result.ok and str(result.error or "").startswith(f"{ROUTE_CHANGED}:")


def driver_for(
    connector_def: dict, mode: str, pack: str | None = None, tool: dict | None = None
) -> SandboxDriver | ComposioDriver | McpDriver:
    """`connector_def` is the connector body. mode: sandbox | live | auto (live if connected). `pack` is the
    run's pack key, for its own sandbox data. A `driver: mcp` connector runs on the MCP server instead of
    Composio (`auto`: when NM_MCP_URL is set and the server answers), except that a `tool` of its without an
    `mcp` mapping (its writes, with the server read-only) answers from its sandbox response in every mode."""
    if mode == "sandbox":
        return SandboxDriver(pack=pack)
    if mode not in ("live", "auto"):
        raise ValueError(f"unknown connector mode {mode!r}")
    if connector_def.get("driver") == MCP:
        if tool is not None and tool.get("mcp") is None:
            return SandboxDriver(pack=pack)
        return _mcp_driver_for(connector_def, mode, pack)
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


def _mcp_driver_for(connector_def: dict, mode: str, pack: str | None) -> SandboxDriver | McpDriver:
    if mode == "live":
        return McpDriver()
    if settings.mcp_url():
        live = McpDriver()
        if live.is_available():
            return live
        log.warning("mcp server unavailable for %s: using sandbox data", connector_def.get("toolkit"))
    return SandboxDriver(pack=pack)
