"""A demo marketplace pack seen through its pack definition, when one exists for its slug."""

from typing import Literal

from app import settings
from app.models.catalog import Pack, PackConnector
from app.runtime.drivers import SandboxDriver, driver_for

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
    """Whether a connector's calls would run against sandbox data, as `gateway.runs_simulated` predicts it:
    always in sandbox mode, never in live mode, and in auto mode when it is not connected. One instance
    serves one request and checks each connector once, so a listing asks Composio at most once per
    connector."""

    def __init__(self, mode: str | None = None) -> None:
        self.mode = mode or settings.connector_mode()
        self._seen: dict[str, bool] = {}

    def __call__(self, key: str, body: dict) -> bool:
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
