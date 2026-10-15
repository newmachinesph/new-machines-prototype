"""A demo marketplace pack seen through its pack definition, when one exists for its slug."""

from typing import Literal, Self

from app import settings
from app.models.catalog import Pack, PackConnector
from app.runtime.drivers import SandboxDriver, driver_for
from app.runtime.routes import NONE, Route, org_routes

Access = Literal["read", "write (approval)", "write"]


def connector_access(body: dict) -> Access:
    """The marketplace access label: read when every tool only reads, write when the connector's defaults
    permit every other action class it has, write (approval) otherwise."""
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    classes = {t.get("action_class") for t in tools if isinstance(t, dict)} - {"read"}
    if not classes:
        return "read"
    defaults = body.get("defaults") if isinstance(body.get("defaults"), dict) else {}
    return "write" if all(defaults.get(c) == "permit" for c in classes) else "write (approval)"


class SandboxForecast:
    """Whether a connector's calls would not reach a real account, for the marketplace's `mocked` label.

    In the live workspace (`for_org`) the org's own connection rows decide, as they decide for its runs
    (`gateway.driver_of`): only an app connected to the org's own account is real; one connected to sandbox
    data, or not connected yet, is labelled simulated. Otherwise the connector mode decides, as
    `gateway.runs_simulated` predicts it: always in sandbox mode, never in live mode, and in auto mode when it
    is not connected. One instance serves one request and checks each connector once, so a listing asks
    Composio at most once per connector."""

    def __init__(self, mode: str | None = None, by_app: dict[str, Route] | None = None) -> None:
        self.mode = mode or settings.connector_mode()
        self._by_app = by_app
        self._seen: dict[str, bool] = {}

    @classmethod
    def for_org(cls, org_id: str) -> Self:
        """The forecast of the org's own connections (live workspace)."""
        return cls(by_app=org_routes(org_id))

    def __call__(self, key: str, body: dict) -> bool:
        if self._by_app is not None:
            return self._by_app.get(key, NONE).mode != "composio"
        if key not in self._seen:
            self._seen[key] = isinstance(driver_for(body, self.mode), SandboxDriver)
        return self._seen[key]


def pack_connectors(
    keys: list[str], connectors: dict[str, dict], sandboxed: SandboxForecast
) -> list[PackConnector]:
    """The pack definition's connector keys as marketplace connectors, labelled mocked when their calls
    would serve sandbox data."""
    out = []
    for key in keys:
        body = connectors.get(key) or {}
        out.append(
            PackConnector(
                app=str(body.get("app") or key), access=connector_access(body), mocked=sandboxed(key, body)
            )
        )
    return out


def with_definition(pack: Pack, body: dict, connectors: dict[str, dict], sandboxed: SandboxForecast) -> Pack:
    """`pack` with `function`, `industries`, `agents` and `connectors` from its pack definition `body`."""
    update: dict = {
        "function": body.get("function"),
        "industries": [str(i) for i in body.get("industries") or []],
    }
    if isinstance(body.get("agents"), list):
        update["agents"] = [str(a) for a in body["agents"]]
    if isinstance(body.get("connectors"), list):
        update["connectors"] = pack_connectors([str(c) for c in body["connectors"]], connectors, sandboxed)
    return pack.model_copy(update=update)
