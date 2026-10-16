"""A demo marketplace pack seen through its pack definition, when one exists for its slug."""

from typing import Literal, Self

from app import settings
from app.defs import owners
from app.models.catalog import Pack, PackConnector
from app.runtime.drivers import PLATFORM_MCP_DRIVER, SandboxDriver, driver_for
from app.runtime.routes import NONE, REAL_MODES, Route, org_routes

Access = Literal["read", "write (approval)", "write"]


def connector_access(body: dict, contract: dict | None = None) -> Access:
    """The marketplace access label of one pack's use of a connector: read when every tool the pack may call
    only reads, write when the connector's defaults permit every other action class among them, write
    (approval) otherwise. The tools are the connector's whose capability the pack's contract authorizes
    (`tool_capabilities`, which the gateway enforces for workflow nodes and agent steps alike); without a
    contract, all of the connector's tools."""
    tools = (
        [t for t in body.get("tools") or [] if isinstance(t, dict)]
        if isinstance(body.get("tools"), list)
        else []
    )
    caps = ((contract or {}).get("authorization") or {}).get("tool_capabilities")
    if isinstance(caps, list):
        tools = [t for t in tools if t.get("capability") in caps]
    classes = {t.get("action_class") for t in tools} - {"read"}
    if not classes:
        return "read"
    defaults = body.get("defaults") if isinstance(body.get("defaults"), dict) else {}
    return "write" if all(defaults.get(c) == "permit" for c in classes) else "write (approval)"


class SandboxForecast:
    """Whether a connector's calls would not reach a real account, for the marketplace's `mocked` label.

    In the live workspace (`for_org`) the org's own connection rows decide, as they decide for its runs
    (`gateway.driver_of`): only an app connected to the org's own account or MCP server is real;
    one connected to sandbox data, or not connected yet, is labelled simulated. Otherwise the connector
    mode decides, as `gateway.runs_simulated` predicts it: always in sandbox mode, never in live mode, and
    in auto mode when it is not connected. One instance serves one request and checks each connector once,
    so a listing asks Composio at most once per connector."""

    def __init__(self, mode: str | None = None, by_app: dict[str, Route] | None = None) -> None:
        self.mode = mode or settings.connector_mode()
        self._by_app = by_app
        self._seen: dict[str, bool] = {}

    @classmethod
    def for_org(cls, org_id: str) -> Self:
        """The forecast of the org's own connections (live workspace)."""
        return cls(by_app=org_routes(org_id))

    def _simulated(self, key: str, body: dict) -> bool:
        if self.mode == "auto" and body.get("driver") == PLATFORM_MCP_DRIVER and not owners.is_reserved(key):
            # The platform's MCP server is a forecast from its configuration alone: a catalog request never
            # opens a session to it.
            return not settings.mcp_url()
        return isinstance(driver_for(body, self.mode, key=key), SandboxDriver)

    def __call__(self, key: str, body: dict) -> bool:
        if self._by_app is not None:
            return self._by_app.get(key, NONE).mode not in REAL_MODES
        if key not in self._seen:
            self._seen[key] = self._simulated(key, body)
        return self._seen[key]


def pack_connectors(
    keys: list[str],
    connectors: dict[str, dict],
    sandboxed: SandboxForecast,
    contract: dict | None = None,
) -> list[PackConnector]:
    """The pack definition's connector keys as marketplace connectors, labelled mocked when their calls
    would serve sandbox data, with the access the pack's own contract gives it."""
    out = []
    for key in keys:
        body = connectors.get(key) or {}
        out.append(
            PackConnector(
                app=str(body.get("app") or key),
                access=connector_access(body, contract),
                mocked=sandboxed(key, body),
            )
        )
    return out


def with_definition(
    pack: Pack,
    body: dict,
    connectors: dict[str, dict],
    sandboxed: SandboxForecast,
    contracts: dict[str, dict] | None = None,
) -> Pack:
    """`pack` with `function`, `industries`, `agents` and `connectors` from its pack definition `body`."""
    update: dict = {
        "function": body.get("function"),
        "industries": [str(i) for i in body.get("industries") or []],
    }
    if isinstance(body.get("agents"), list):
        update["agents"] = [str(a) for a in body["agents"]]
    if isinstance(body.get("connectors"), list):
        ref = body.get("contract") or ""
        update["connectors"] = pack_connectors(
            [str(c) for c in body["connectors"]],
            connectors,
            sandboxed,
            (contracts or {}).get(str(ref)),
        )
    return pack.model_copy(update=update)
