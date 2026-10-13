"""What a definition refers to, and what refers to it. Pure functions over a Bundle (no database)."""

from app.defs.model import Bundle, Definition

Ref = tuple[str, str]  # (kind, key)

# workflow node type -> (config field, referenced kind)
_NODE_FIELD_REFS = {
    "agent": ("agent", "agent"),
    "decision": ("rules", "decision_rules"),
    "memory": ("space", "memory_space"),
}
_NODE_SCHEMA_FIELDS = ("schema", "output_schema", "input_schema")


def _tool_connector(tool_ref: object) -> str | None:
    """'<connector>.<tool id>' -> '<connector>'."""
    return tool_ref.partition(".")[0] if isinstance(tool_ref, str) and tool_ref else None


def _workflow_refs(body: dict) -> set[Ref]:
    refs: set[Ref] = set()
    if isinstance(body.get("work_contract_ref"), str):
        refs.add(("contract", body["work_contract_ref"]))
    for node in body.get("nodes") or []:
        config = node.get("config") or {}
        if node.get("type") in _NODE_FIELD_REFS:
            field, kind = _NODE_FIELD_REFS[node["type"]]
            if isinstance(config.get(field), str):
                refs.add((kind, config[field]))
        if node.get("type") == "connector" and (conn := _tool_connector(config.get("tool"))):
            refs.add(("connector", conn))
        refs.update(("schema", config[f]) for f in _NODE_SCHEMA_FIELDS if isinstance(config.get(f), str))
    return refs


def refs_of(d: Definition) -> set[Ref]:
    """The definitions `d` refers to (they may not exist; callers filter against a bundle)."""
    body = d.body
    refs: set[Ref] = set()
    if d.kind == "pack":
        for field in ("workflow", "contract"):
            if isinstance(body.get(field), str):
                refs.add((field, body[field]))
        refs.update(("agent", a) for a in body.get("agents") or [])
        refs.update(("connector", c) for c in body.get("connectors") or [])
    elif d.kind == "workflow":
        refs = _workflow_refs(body)
    elif d.kind == "contract":
        refs.update(
            ("schema", body[f])
            for f in ("input_schema_ref", "output_schema_ref")
            if isinstance(body.get(f), str)
        )
    elif d.kind == "agent":
        runtime = body.get("runtime") or {}
        if runtime.get("model_profile"):
            refs.add(("models", "default"))
        refs.update(("connector", c) for t in runtime.get("tools") or [] if (c := _tool_connector(t)))
        refs.update(
            ("schema", body[f])
            for f in ("input_schema_ref", "output_schema_ref")
            if isinstance(body.get(f), str)
        )
    return refs


def refs_in(bundle: Bundle, kind: str, key: str) -> list[Ref]:
    """Existing definitions that (kind, key) refers to, sorted."""
    d = bundle.get(kind, key)
    return sorted(r for r in refs_of(d) if bundle.get(*r) is not None) if d else []


def used_by(bundle: Bundle, kind: str, key: str) -> list[Ref]:
    """Definitions in the bundle that refer to (kind, key), sorted."""
    return sorted(k for k, d in bundle.items.items() if k != (kind, key) and (kind, key) in refs_of(d))
