"""Run snapshots: the latest published versions of a pack and everything it references, pinned for one run.

Shape: {"org_id", "versions": [{kind, key, version, digest}], "defs": {kind: {key: {"body", "files"}}},
"overrides": {connector: {action_class: decision}}, "disabled": [connector]}. A workflow reads definitions
only from its snapshot, so a later publish never changes a run that has already started.
"""

import copy

from app.defs import owners, registry
from app.defs.digest import digest
from app.defs.model import Definition
from app.defs.registry import Version

ORG_PLACEHOLDER = "{org}"  # contract templates name the buyer organisation with this literal
MODELS_KEY = "default"
UNSAVED_BY = "listing check"  # published_by of an unsaved definition pinned at version 0


class _Pinner:
    """Pins what `org_id` may see (`registry.visible_version`). `unsaved` definitions come first, at version
    0 and must be keyed in the org's own namespace (ValueError otherwise); `pins` hold an installation to
    exact versions of what it may see, of another workspace's definition only an approved listed one."""

    def __init__(self, conn, org_id: str, pins: dict | None = None, unsaved: dict | None = None) -> None:
        self._conn, self._org = conn, org_id
        self._pins: dict[tuple[str, str], int] = dict(pins or {})
        self._unsaved: dict[tuple[str, str], Definition] = dict(unsaved or {})
        if outside := sorted(f"{k}/{key}" for k, key in self._unsaved if not owners.in_org(key, org_id)):
            raise ValueError(f"unsaved definitions outside {org_id}: {', '.join(outside)}")
        self.pinned: dict[tuple[str, str], Version] = {}

    def pin(self, kind: str, key: str) -> dict:
        """Pin kind/key and return its body. LookupError when it does not exist or the org may not see it."""
        if (kind, key) not in self.pinned:
            self.pinned[(kind, key)] = self._resolve(kind, key)
        return self.pinned[(kind, key)].body

    def _resolve(self, kind: str, key: str) -> Version:
        if (kind, key) in self._unsaved:
            d = self._unsaved[(kind, key)]
            return Version(
                kind, key, 0, digest(d), d.body, dict(d.files), registry.BUILDER, UNSAVED_BY, "", ""
            )
        visible = registry.visible_version(self._conn, kind, key, self._org)
        if visible is None:
            if registry.latest(self._conn, kind, key) is None:
                raise LookupError(f"{kind}/{key} is not published")
            raise LookupError(f"{kind}/{key} is not available to {self._org}")
        if (kind, key) not in self._pins:
            return visible
        pinned = registry.pinnable_version(self._conn, kind, key, self._pins[(kind, key)], self._org)
        if pinned is None:
            raise LookupError(f"{kind}/{key} is not available to {self._org}")
        return pinned


def _connector_of(tool_ref: str) -> str:
    return tool_ref.partition(".")[0]


def _pin_workflow_refs(pin: _Pinner, workflow: dict) -> None:
    for node in workflow.get("nodes") or []:
        cfg = node.get("config") or {}
        kind = node.get("type")
        if kind == "agent":
            pin.pin("agent", cfg["agent"])
            if cfg.get("output_schema"):
                pin.pin("schema", cfg["output_schema"])
        elif kind == "connector":
            pin.pin("connector", _connector_of(cfg["tool"]))
        elif kind == "decision":
            pin.pin("decision_rules", cfg["rules"])
        elif kind == "memory":
            pin.pin("memory_space", cfg["space"])
        elif kind == "verification" and cfg.get("schema"):
            pin.pin("schema", cfg["schema"])


def _pin_agent_refs(pin: _Pinner) -> None:
    agents = [key for (kind, key) in list(pin.pinned) if kind == "agent"]
    for key in agents:
        body = pin.pin("agent", key)
        for tool_ref in (body.get("runtime") or {}).get("tools") or []:
            pin.pin("connector", _connector_of(tool_ref))
        for field in ("input_schema_ref", "output_schema_ref"):
            if body.get(field):
                pin.pin("schema", body[field])


def build_snapshot(
    conn,
    pack_slug: str,
    org_id: str,
    overrides: dict,
    disabled: set[str],
    *,
    pins: dict[tuple[str, str], int] | None = None,
    unsaved: dict[tuple[str, str], Definition] | None = None,
) -> dict:
    """Resolve and pin `pack_slug` for `org_id`. LookupError for an unknown pack, a missing reference, or a
    definition another org owns privately (an org can only ever run what it may see).

    `pins` hold an installation of a listed pack to the versions it was added at; `unsaved` definitions (a
    listing check) are pinned at version 0 and never published. Runs on the caller's connection and never
    commits.
    """
    pin = _Pinner(conn, org_id, pins, unsaved)
    pack = pin.pin("pack", pack_slug)
    workflow = pin.pin("workflow", pack["workflow"])
    contract_key = workflow.get("work_contract_ref") or pack["contract"]
    contract = pin.pin("contract", contract_key)
    for key in pack.get("agents") or []:
        pin.pin("agent", key)
    for key in pack.get("connectors") or []:
        pin.pin("connector", key)
    _pin_workflow_refs(pin, workflow)
    _pin_agent_refs(pin)
    for field in ("input_schema_ref", "output_schema_ref"):
        if contract.get(field):
            pin.pin("schema", contract[field])
    pin.pin("models", MODELS_KEY)

    defs: dict[str, dict] = {}
    versions = []
    for (kind, key), v in sorted(pin.pinned.items()):
        body = copy.deepcopy(v.body)
        if kind == "contract" and body.get("org_id") == ORG_PLACEHOLDER:
            body["org_id"] = org_id
        defs.setdefault(kind, {})[key] = {"body": body, "files": dict(v.files)}
        versions.append({"kind": kind, "key": key, "version": v.version, "digest": v.digest})
    return {
        "org_id": org_id,
        "versions": versions,
        "defs": defs,
        "overrides": copy.deepcopy(overrides or {}),
        "disabled": sorted(disabled or []),
    }
