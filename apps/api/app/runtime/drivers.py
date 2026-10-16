"""Connector drivers: sandbox responses from definitions, live calls through Composio, or calls to an
org's own MCP server."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import settings

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
    connector_def: dict, mode: str, pack: str | None = None
) -> SandboxDriver | ComposioDriver | UnconnectedDriver:
    """`connector_def` is the connector body. mode: sandbox | live | auto (live if connected). `pack` is the
    run's pack key, for its own sandbox data. An org's own MCP server is reached only through the org's
    connection (`gateway._route_driver`): a run that is not routed answers from samples, or runs nothing
    in live mode."""
    if mode not in ("sandbox", "auto", "live"):
        raise ValueError(f"unknown connector mode {mode!r}")
    if connector_def.get("transport") == MCP_TRANSPORT:
        return UnconnectedDriver() if mode == "live" else SandboxDriver(pack=pack, samples=True)
    if mode == "sandbox":
        return SandboxDriver(pack=pack)
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
