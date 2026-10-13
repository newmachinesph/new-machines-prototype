"""Connector drivers: sandbox responses from definitions, or live calls through Composio."""

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
    """Returns the recorded response in definitions/connectors/sandbox/<connector>/<tool id>.json."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or settings.defs_dir() / "connectors" / "sandbox"

    def execute(self, connector: str, tool: dict, args: dict) -> ToolResult:
        tool_id = str(tool.get("id", ""))
        if not (_SAFE_NAME.match(connector) and _SAFE_NAME.match(tool_id)):
            return ToolResult(
                ok=False, data=None, mocked=True, error=f"invalid sandbox tool {connector}.{tool_id}"
            )
        path = self._root / connector / f"{tool_id}.json"
        if not path.is_file():
            return ToolResult(
                ok=False, data=None, mocked=True, error=f"no sandbox response for {connector}.{tool_id}"
            )
        return ToolResult(ok=True, data=json.loads(path.read_text(encoding="utf-8")), mocked=True)


class ComposioDriver:
    """Executes a connector tool's allowlisted Composio slug for the demo user (DEMO_USER_UID)."""

    def __init__(self, client: Any = None, user_id: str | None = None) -> None:
        self._client = client
        self._user_id = user_id

    @property
    def client(self) -> Any:
        if self._client is None:
            from composio import Composio  # reads COMPOSIO_API_KEY from the environment

            self._client = Composio()
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
        try:
            response = self.client.tools.execute(
                slug,
                args,
                user_id=self.user_id,
                version=version,
                # Connector definitions may not pin a toolkit version; then the latest one runs.
                dangerously_skip_version_check=None if version else True,
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


def driver_for(connector_def: dict, mode: str) -> SandboxDriver | ComposioDriver:
    """`connector_def` is the connector body. mode: sandbox | live | auto (live if connected)."""
    if mode == "sandbox":
        return SandboxDriver()
    if mode == "live":
        return ComposioDriver()
    if mode != "auto":
        raise ValueError(f"unknown connector mode {mode!r}")
    live = ComposioDriver()
    try:
        if live.is_connected(connector_def["toolkit"]):
            return live
    except Exception as exc:  # no key, no uid or Composio unreachable: fall back to labelled sandbox data
        log.warning(
            "composio connection check failed for %s: %s", connector_def.get("toolkit"), type(exc).__name__
        )
    return SandboxDriver()
