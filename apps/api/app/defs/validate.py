"""Bundle validation: JSON Schema per kind, then cross references and CEL compilation."""

import json
from collections.abc import Iterator
from functools import cache
from pathlib import Path, PurePosixPath

import celpy
from jsonschema import Draft202012Validator

from app import settings
from app.defs import owners
from app.defs.model import Bundle, DefError, Definition, path_for
from app.defs.owners import SEPARATOR

SCHEMA_FILES = {
    "taxonomy": "nm.taxonomy.v1",
    "models": "nm.model_profiles.v1",
    "pack": "nm.pack.v1",
    "workflow": "nm.workflow.v1",
    "contract": "nm.work_contract.v1",
    "agent": "nm.agent.manifest.v1.1",
    "connector": "nm.connector.v1",
    "decision_rules": "nm.decision_rules.v1",
    "memory_space": "nm.memory_space.v1",
}
NODE_TYPES = {
    "trigger",
    "memory",
    "connector",
    "agent",
    "decision",
    "human_workforce",
    "approval",
    "verification",
    "end",
}
# body field that must equal the definition key
ID_FIELDS = {"workflow": "workflow_id", "contract": "contract_id", "agent": "agent_id", "pack": "slug"}
# node type -> (config field, referenced kind)
NODE_REFS = {
    "agent": ("agent", "agent"),
    "decision": ("rules", "decision_rules"),
    "memory": ("space", "memory_space"),
}

LISTING_CHECK = "listing-check"  # the reserved name of a submission's check pack (see studio.CHECK_NAME)

# kinds with a same-named cross-reference method on _Checker
CROSS_REF_KINDS = {"pack", "workflow", "contract", "agent", "decision_rules"}

_CEL_ENV = celpy.Environment()


@cache
def _validator(kind: str, schemas_dir: str) -> Draft202012Validator:
    schema = json.loads((Path(schemas_dir) / f"{SCHEMA_FILES[kind]}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _loc(parts) -> str:
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out.lstrip(".") or "(root)"


def compile_cel(expr: str) -> str | None:
    """Return an error message when `expr` (leading `=` already stripped) is not valid CEL."""
    try:
        _CEL_ENV.compile(expr)
    except celpy.CELParseError as exc:
        text = str(exc).strip()
        return text.splitlines()[0] if text else "invalid CEL"
    return None


def _cel_strings(value, where: str):
    """Yield (location, expression) for every string starting with '=' in a nested value."""
    if isinstance(value, str):
        if value.startswith("="):
            yield where, value[1:]
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _cel_strings(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _cel_strings(v, f"{where}[{i}]")


def _view_cel(view: dict) -> Iterator[tuple[str, str]]:
    """(location, expression) for the fields of a pack's deliverable view that the projection evaluates:
    the summary, each fact's value and the item fields. `kind` and fact labels are shown as written."""
    at = "deliverable_view"
    fields = [(f"{at}.summary", view.get("summary"))]
    fields += [(f"{at}.facts[{i}].value", f.get("value")) for i, f in enumerate(view.get("facts") or [])]
    items = view.get("items") or {}
    fields += [(f"{at}.items.{k}", items.get(k)) for k in ("from", "label", "detail")]
    for where, value in fields:
        if isinstance(value, str) and value.startswith("="):
            yield where, value[1:]


class _Checker:
    def __init__(self, bundle: Bundle):
        self.b = bundle
        self.ok: set[tuple[str, str]] = set()  # definitions that passed their schema check
        self.errors: list[DefError] = []

    def err(self, d: Definition, message: str) -> None:
        self.errors.append(DefError(d.kind, d.key, d.path, message))

    def ok_get(self, kind: str, key: str) -> Definition | None:
        """Like bundle.get, but only for schema-valid definitions, whose bodies are safe to read."""
        return self.b.get(kind, key) if (kind, key) in self.ok else None

    def has(self, kind: str, key: str) -> bool:
        return self.b.get(kind, key) is not None

    def schema(self, d: Definition) -> bool:
        """Schema, id-field and file-location checks. True when the definition is structurally sound."""
        before = len(self.errors)
        validator = (
            Draft202012Validator(Draft202012Validator.META_SCHEMA)
            if d.kind == "schema"
            else _validator(d.kind, str(settings.schemas_dir()))
        )
        for e in sorted(validator.iter_errors(d.body), key=lambda e: list(map(str, e.absolute_path))):
            self.err(d, f"{_loc(e.absolute_path)}: {e.message}")
        expected = path_for(d.kind, d.key)
        if d.path and d.path != expected:
            self.err(d, f"file is at {d.path} but kind/key require {expected}")
        field = ID_FIELDS.get(d.kind)
        if field and d.body.get(field) != d.key:
            self.err(d, f"{field}: must equal key {d.key!r}")
        return len(self.errors) == before

    def connector_tool(self, ref: str):
        """Resolve '<connector>.<tool id>' to a tool dict, or None."""
        conn_key, _, tool_id = ref.partition(".")
        conn = self.ok_get("connector", conn_key)
        if conn is None:
            return None
        return next((t for t in conn.body.get("tools", []) if t["id"] == tool_id), None)

    def pack(self, d: Definition) -> None:
        body = d.body
        taxonomy = self.ok_get("taxonomy", "default")
        if taxonomy is None:
            self.err(d, "taxonomy/default is missing")
        else:
            fn_ids = {f["id"] for f in taxonomy.body.get("functions", [])}
            ind_ids = {i["id"] for i in taxonomy.body.get("industries", [])}
            if body["function"] not in fn_ids:
                self.err(d, f"function: {body['function']!r} is not in the taxonomy")
            for i, ind in enumerate(body["industries"]):
                if ind not in ind_ids:
                    self.err(d, f"industries[{i}]: {ind!r} is not in the taxonomy")
        for field in ("workflow", "contract"):
            if not self.has(field, body[field]):
                self.err(d, f"{field}: {field} {body[field]!r} does not exist")
        for i, a in enumerate(body["agents"]):
            if not self.has("agent", a):
                self.err(d, f"agents[{i}]: agent {a!r} does not exist")
        for i, c in enumerate(body["connectors"]):
            if not self.has("connector", c):
                self.err(d, f"connectors[{i}]: connector {c!r} does not exist")
        for where, expr in _view_cel(body.get("deliverable_view") or {}):
            if (msg := compile_cel(expr)) is not None:
                self.err(d, f"{where}: CEL does not compile: {msg}")

    def workflow(self, d: Definition) -> None:
        body = d.body
        nodes = body["nodes"]
        ids = [n["id"] for n in nodes]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            self.err(d, f"nodes: duplicate node id {dup!r}")
        by_id = {n["id"]: n for n in nodes}
        entry = body["entry_node_id"]
        if entry not in by_id:
            self.err(d, f"entry_node_id: node {entry!r} does not exist")
        elif by_id[entry]["type"] != "trigger":
            self.err(d, f"entry_node_id: node {entry!r} must be of type trigger")
        if not self.has("contract", body["work_contract_ref"]):
            self.err(d, f"work_contract_ref: contract {body['work_contract_ref']!r} does not exist")
        for i, n in enumerate(nodes):
            at = f"nodes[{i}] ({n['id']})"
            if n["type"] not in NODE_TYPES:
                self.err(d, f"{at}.type: {n['type']!r} is not supported (allowed: {sorted(NODE_TYPES)})")
            for label, target in (n.get("routes") or {}).items():
                if target not in by_id:
                    self.err(d, f"{at}.routes.{label}: target node {target!r} does not exist")
            self.node_refs(d, n, at)
            self.decision_routes(d, n, at)
            for where, expr in _cel_strings(n["config"], f"{at}.config"):
                if (msg := compile_cel(expr)) is not None:
                    self.err(d, f"{where}: CEL does not compile: {msg}")

    def decision_routes(self, d: Definition, n: dict, at: str) -> None:
        """A decision whose rules ask the decision model must route every outcome it can take, its fallback
        included, so a model failure always ends somewhere safe instead of in a configuration error."""
        if n["type"] != "decision":
            return
        rules = self.ok_get("decision_rules", str((n.get("config") or {}).get("rules")))
        if rules is None or not rules.body.get("evaluator"):
            return
        body = rules.body
        wanted = {r["route"] for r in body["rules"]} | {body["default"]["route"]}
        wanted.add(body["evaluator"]["on_error"]["route"])
        for route in sorted(wanted - set(n.get("routes") or {})):
            self.err(
                d, f"{at}.routes: decision {rules.key!r} can take route {route!r}, which this node lacks"
            )

    def node_refs(self, d: Definition, n: dict, at: str) -> None:
        cfg = n["config"]
        if n["type"] in NODE_REFS:
            field, kind = NODE_REFS[n["type"]]
            ref = cfg.get(field)
            if not isinstance(ref, str) or not self.has(kind, ref):
                self.err(d, f"{at}.config.{field}: {kind} {ref!r} does not exist")
            elif n["type"] == "agent":
                self.agent_inputs(d, cfg, ref, at)
        elif n["type"] == "connector":
            ref = cfg.get("tool")
            if not isinstance(ref, str) or self.connector_tool(ref) is None:
                self.err(d, f"{at}.config.tool: connector tool {ref!r} does not exist")

    def agent_inputs(self, d: Definition, cfg: dict, agent_key: str, at: str) -> None:
        """An org-built agent's step must hand the agent something: a missing or empty `inputs` is a problem,
        and so is any input the agent's input schema requires that the step does not map. A Studio-built
        agent's schema (shared/agent-input) requires nothing, so the first rule is what catches its empty
        step. Inputs given as one expression cannot be checked before the run. Platform agents are left
        alone: their `input_schema_ref` names a pack's run or result shape, not what their step maps. A
        submission's listing-check pack is exempt: it hands the agent the publisher's sample as it is,
        whatever the agent asks for."""
        if SEPARATOR not in agent_key or owners.name_of(d.key) == LISTING_CHECK:
            return
        given = cfg.get("inputs")
        if isinstance(given, str):
            return
        given = given if isinstance(given, dict) else {}
        agent = self.ok_get("agent", agent_key)
        schema = self.ok_get("schema", str(agent.body.get("input_schema_ref"))) if agent else None
        missing = [n for n in (schema.body.get("required") or [] if schema else []) if n not in given]
        for name in missing:
            self.err(
                d,
                f"{at}.config.inputs.{name}: agent {agent_key!r} requires the input {name!r}, "
                "which this step does not map",
            )
        if not given and not missing:
            self.err(d, f"{at}.config.inputs: agent {agent_key!r} gets no inputs, so this step must map some")

    def contract(self, d: Definition) -> None:
        for field in ("input_schema_ref", "output_schema_ref"):
            ref = d.body[field]
            if not self.has("schema", ref):
                self.err(d, f"{field}: schema {ref!r} does not exist")

    def agent(self, d: Definition) -> None:
        rt = d.body["runtime"]
        for i, ref in enumerate(rt.get("tools", [])):
            if self.connector_tool(ref) is None:
                self.err(d, f"runtime.tools[{i}]: tool {ref!r} is not in any connector")
        profile = rt.get("model_profile")
        if profile is not None:
            models = self.ok_get("models", "default")
            if models is None or profile not in models.body.get("profiles", {}):
                self.err(d, f"runtime.model_profile: profile {profile!r} does not exist")
        names = [("runtime.instructions", rt["instructions"])] if "instructions" in rt else []
        names += [(f"runtime.skills[{i}]", s) for i, s in enumerate(rt.get("skills", []))]
        for where, name in names:
            parts = PurePosixPath(name)
            if parts.is_absolute() or ".." in parts.parts:
                self.err(d, f"{where}: path {name!r} must stay inside the agent folder")
            elif name not in d.files:
                self.err(d, f"{where}: file {name!r} is missing")

    def decision_rules(self, d: Definition) -> None:
        for i, rule in enumerate(d.body["rules"]):
            if (msg := compile_cel(rule["when"].removeprefix("="))) is not None:
                self.err(d, f"rules[{i}].when: CEL does not compile: {msg}")
        evaluator = d.body.get("evaluator")
        if not evaluator:
            return
        exprs = [(f"evaluator.{k}", evaluator[k]) for k in ("for_each", "ref", "keep") if k in evaluator]
        exprs += [(f"evaluator.state[{i}]", e) for i, e in enumerate(evaluator["state"])]
        for where, expr in exprs:
            if (msg := compile_cel(expr.removeprefix("="))) is not None:
                self.err(d, f"{where}: CEL does not compile: {msg}")

    def pack_capabilities(self, pack: Definition) -> None:
        """contract.authorization.tool_capabilities must cover every tool the pack's workflow can use."""
        wf = self.ok_get("workflow", pack.body["workflow"])
        contract = self.ok_get("contract", pack.body["contract"])
        if wf is None or contract is None:
            return
        nodes = wf.body.get("nodes", [])
        refs = {
            n["config"]["tool"]
            for n in nodes
            if n.get("type") == "connector" and isinstance(n.get("config", {}).get("tool"), str)
        }
        agent_keys = {n["config"].get("agent") for n in nodes if n.get("type") == "agent"}
        for key in agent_keys | set(pack.body["agents"]):
            agent = self.ok_get("agent", key) if isinstance(key, str) else None
            if agent is not None:
                refs.update(agent.body.get("runtime", {}).get("tools", []))
        needed = {t["capability"] for r in refs if (t := self.connector_tool(r)) is not None}
        granted = set(contract.body.get("authorization", {}).get("tool_capabilities", []))
        if missing := sorted(needed - granted):
            self.err(
                contract,
                f"authorization.tool_capabilities: missing {missing} used by pack {pack.key!r}",
            )


def validate_bundle(bundle: Bundle) -> list[DefError]:
    c = _Checker(bundle)
    valid: list[Definition] = []
    for d in bundle.items.values():
        if d.kind not in SCHEMA_FILES and d.kind != "schema":
            c.err(d, f"unknown definition kind {d.kind!r}")
        elif c.schema(d):
            valid.append(d)
    c.ok = {(d.kind, d.key) for d in valid}
    for d in valid:
        if d.kind in CROSS_REF_KINDS:
            getattr(c, d.kind)(d)
    for d in valid:
        if d.kind == "pack":
            c.pack_capabilities(d)
    return c.errors
