"""Run snapshots: the latest published versions of a pack and everything it references, pinned for one run.

Shape: {"org_id", "versions": [{kind, key, version, digest}], "defs": {kind: {key: {"body", "files"}}},
"overrides": {connector: {action_class: decision}}, "disabled": [connector]}. A workflow reads definitions
only from its snapshot, so a later publish never changes a run that has already started.
"""

import copy

from app.defs import registry
from app.defs.registry import Version

ORG_PLACEHOLDER = "{org}"  # contract templates name the buyer organisation with this literal
MODELS_KEY = "default"


class _Pinner:
    def __init__(self, conn) -> None:
        self._conn = conn
        self.pinned: dict[tuple[str, str], Version] = {}

    def pin(self, kind: str, key: str) -> dict:
        """Pin the latest version of kind/key and return its body. LookupError when it does not exist."""
        if (kind, key) not in self.pinned:
            version = registry.latest(self._conn, kind, key)
            if version is None:
                raise LookupError(f"{kind}/{key} is not published")
            self.pinned[(kind, key)] = version
        return self.pinned[(kind, key)].body


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


def build_snapshot(conn, pack_slug: str, org_id: str, overrides: dict, disabled: set[str]) -> dict:
    """Resolve and pin `pack_slug` for `org_id`. LookupError for an unknown pack, a missing reference, or a
    definition another org owns privately (an org can only ever run what it may see).

    Runs on the caller's connection and never commits.
    """
    pin = _Pinner(conn)
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
    if hidden := registry.hidden_from(conn, list(pin.pinned), org_id):
        kind, key = hidden[0]
        raise LookupError(f"{kind}/{key} is not available to {org_id}")

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
