"""Studio drafts to definitions and back, and the builder's own rules. Pure: no database and no I/O.

An org's agent is a manifest v1.1 (google_adk) with instructions.md and one skills/NN-<slug>.md per skill. An
org's pack is a pack, a workflow, a contract, an input schema and one decision rules definition per decision
step: the same shapes as the seed packs, so the validator, the snapshot and PackRunner treat them alike.
"""

import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.defs import owners, unlocks
from app.defs.model import Bundle, DefError, Definition, path_for
from app.models.common import money_text
from app.models.studio import (
    AgentDraft,
    BuilderIssue,
    DecisionDefault,
    DecisionRule,
    DecisionRules,
    InputField,
    PackDraft,
    SkillDraft,
    StepDraft,
)
from app.workspace import REGION

ADAPTER = "google_adk"
AGENT_INPUT, AGENT_RESULT = "shared/agent-input", "shared/agent-result"
TEAM_CAPABILITY = "team.assist"
INSTRUCTIONS = "instructions.md"
SKILLS_DIR = "skills"
SKILL_SLUG_MAX = 30
RETENTION = "retention/30d"
DATA_CLASSES = ("CONFIDENTIAL",)
READ = "read"
AGENT_SCHEMA = "nm.agent.manifest.v1.1"
_HEADING = re.compile(r"\A# (.+)\n")


@dataclass(frozen=True)
class OrgRef:
    """The org a definition is built for: its id (the key namespace) and its name (the publisher shown)."""

    id: str
    name: str

    @property
    def publisher(self) -> str:
        return owners.org_namespace(self.id)


def tool_index(bundle: Bundle) -> dict[str, dict[str, Any]]:
    """Every connector tool by ref (`<connector>.<tool id>`): the tool as defined, plus its app's name."""
    out: dict[str, dict[str, Any]] = {}
    for d in bundle.of("connector"):
        for tool in d.body.get("tools") or []:
            out[f"{d.key}.{tool['id']}"] = {**tool, "app": str(d.body.get("app") or d.key)}
    return out


def readable_spaces(bundle: Bundle) -> list[Definition]:
    """Memory spaces any agent may read (`readers` includes "*"): the ones a team's recall step can use."""
    return [d for d in bundle.of("memory_space") if "*" in (d.body.get("readers") or [])]


# --- agents -------------------------------------------------------------------------------------------------


def _skill_path(index: int, title: str) -> str:
    slug = owners.slugify(title)[:SKILL_SLUG_MAX].rstrip("-")
    return f"{SKILLS_DIR}/{index + 1:02d}-{slug}.md"


def _skill_file(skill: SkillDraft) -> str:
    return f"# {skill.title.strip()}\n\n{skill.text.strip()}\n"


def _skill_of(path: str, text: str) -> SkillDraft:
    """A skill file written by `_skill_file`; without its heading, titled by its file name."""
    heading = _HEADING.match(text)
    if heading:
        return SkillDraft(title=heading.group(1).strip(), text=text[heading.end() :].strip())
    stem = path.rsplit("/", 1)[-1].removesuffix(".md")
    return SkillDraft(title=stem.replace("-", " ").capitalize()[:80], text=text.strip())


def org_key_check(key: str, org: OrgRef) -> None:
    """Raise ValueError unless `key` is in the org's namespace with a valid name: a definition is only ever
    built under the org that owns it."""
    if not owners.in_org(key, org.id):
        raise ValueError(f"key {key!r} is not in the namespace of {org.id}")
    if not owners.is_name(owners.name_of(key)):
        raise ValueError(f"key {key!r} does not end in a valid name")


def agent_definition(
    key: str, org: OrgRef, draft: AgentDraft, tools: dict[str, dict[str, Any]], release: int
) -> Definition:
    """The agent definition of `draft` at release `release` (its version is 1.0.<release>)."""
    org_key_check(key, org)
    skills = {_skill_path(i, s.title): _skill_file(s) for i, s in enumerate(draft.skills)}
    body = {
        "schema_version": AGENT_SCHEMA,
        "agent_id": key,
        "version": f"1.0.{release}",
        "publisher_id": org.publisher,
        "publisher_name": org.name[:80],
        "name": draft.name.strip(),
        "summary": draft.summary.strip(),
        "capabilities": [TEAM_CAPABILITY],
        "runtime": {
            "adapter": ADAPTER,
            "model_profile": draft.model_profile,
            "instructions": INSTRUCTIONS,
            "skills": list(skills),
            "tools": list(draft.tools),
            "max_turns": draft.max_turns,
        },
        "input_schema_ref": AGENT_INPUT,
        "output_schema_ref": AGENT_RESULT,
        "requested_tool_capabilities": sorted({tools[t]["capability"] for t in draft.tools if t in tools}),
        "data_processing": {
            "supported_regions": [REGION],
            "data_classes": list(DATA_CLASSES),
            "retention_policy_ref": RETENTION,
        },
    }
    files = {INSTRUCTIONS: draft.instructions.strip() + "\n", **skills}
    return Definition(kind="agent", key=key, body=body, files=files, path=path_for("agent", key))


def agent_draft(body: dict[str, Any], files: dict[str, str]) -> AgentDraft:
    """The draft an agent definition built by `agent_definition` was made from."""
    runtime = body.get("runtime") or {}
    return AgentDraft(
        name=body["name"],
        summary=body["summary"],
        instructions=files[runtime.get("instructions", INSTRUCTIONS)].strip(),
        model_profile=runtime.get("model_profile", "reasoning"),
        skills=[_skill_of(p, files.get(p, "")) for p in runtime.get("skills") or []],
        tools=list(runtime.get("tools") or []),
        max_turns=runtime.get("max_turns", AgentDraft.model_fields["max_turns"].default),
    )


def agent_issues(draft: AgentDraft, tools: dict[str, dict[str, Any]]) -> list[BuilderIssue]:
    """What the definition schema cannot check: each tool exists, is listed once and only reads. A tool that
    writes belongs in a pack step after an approval."""
    issues = []
    for i, ref in enumerate(draft.tools):
        where = f"tools[{i}]"
        if ref in draft.tools[:i]:
            issues.append(BuilderIssue(path=where, message=f"{ref} is listed twice."))
        elif ref not in tools:
            issues.append(BuilderIssue(path=where, message=f"{ref} is not a tool of any app."))
        elif tools[ref]["action_class"] != READ:
            issues.append(
                BuilderIssue(
                    path=where,
                    message=f"An agent may only read. {ref} changes data in {tools[ref]['app']}; add it to a "
                    "pack as a step after an approval.",
                )
            )
    return issues


# --- packs --------------------------------------------------------------------------------------------------

# The outcomes each step type routes (PackRunner's route keys). A decision's come from its rules; an end has
# none. A connector's success is always "ok" (PackRunner treats "next" the same; imports rename it).
ROUTES: dict[str, tuple[str, ...]] = {
    "trigger": ("next",),
    "memory": ("next",),
    "agent": ("next",),
    "connector": ("ok", "denied", "error"),
    "human_workforce": ("resolved", "rejected", "timeout"),
    "approval": ("granted", "denied", "timeout"),
    "verification": ("pass", "fail"),
    "decision": (),
    "end": (),
}
END_STATUSES = ("COMPLETED", "FAILED")
BLOCKED_CLASSES = {"delete", "money"}  # a pack never deletes records or moves money
DEADLINE_S = 172_800
TIMEOUT_MAX_S = DEADLINE_S  # a review or approval waits at most as long as the run may last
MEMORY_LIMIT_MAX = 50
MAX_ATTEMPTS = 40
CONTRACT_ATTEMPTS = 3
POLICY_REF = "policy/default"
CURRENCY = "USD"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"  # the pattern real_runs.single_date_field reads as a date
TEXT_MAX = 200
SEPARATOR = owners.SEPARATOR
# How the run page shows a team pack's result: the writer's drafts when it ends with them, else the summary
# of whatever it ends with (an agent result has one).
DELIVERABLE_VIEW = {
    "kind": "Result",
    "summary": "=has(deliverable.drafts) ? string(size(deliverable.drafts)) + ' drafts were prepared' + "
    "(mocked ? ' on sandbox data. Nothing was sent.' : ', ready for you to check.') : "
    "(has(deliverable.summary) ? string(deliverable.summary) : 'The run finished.')",
    "facts": [],
    "items": {
        "from": "=has(deliverable.drafts) ? deliverable.drafts : []",
        "label": "=item.to + ' — ' + item.subject",
        "detail": "=item.body",
    },
}
_NODE_AT = re.compile(r"^nodes\[\d+\] \(([^)]+)\)")
_NOT_CODE = re.compile(r"[^A-Z0-9]+")


def rules_key(pack_key: str, step_id: str) -> str:
    """The decision rules of a pack's decision step. Names never contain "--", so this cannot collide."""
    return f"{pack_key}{SEPARATOR}{step_id}"


def input_key(pack_key: str) -> str:
    return f"{pack_key}/input"


def outcomes(step: StepDraft) -> list[str]:
    """The outcomes `step` must route, in order: fixed per type; a decision's from its rules, then its
    default (none without rules)."""
    if step.type == "decision":
        if step.rules is None:
            return []
        routes = [r.route for r in step.rules.rules] + [step.rules.default.route]
        if step.rules.evaluator:  # the route taken when the decision model fails
            routes.append(str((step.rules.evaluator.get("on_error") or {}).get("route") or ""))
        return list(dict.fromkeys(r for r in routes if r))
    return list(ROUTES[step.type])


def _issue(message: str, step: str | None = None, path: str = "pack") -> BuilderIssue:
    return BuilderIssue(path=path, message=message, step=step)


def _structure_issues(
    draft: PackDraft, by_id: dict[str, StepDraft], names: Iterable[str]
) -> list[BuilderIssue]:
    ids = [s.id for s in draft.steps]
    out = [
        _issue(f"Two steps are called {i}.", i, f"steps.{i}")
        for i in sorted({i for i in ids if ids.count(i) > 1})
    ]
    if sum(1 for s in draft.steps if s.type == "trigger") != 1:
        out.append(_issue("A pack has exactly one start step.", path="steps"))
    entry = by_id.get(draft.entry_step)
    if entry is None or entry.type != "trigger":
        out.append(_issue("The pack must start with its start step.", path="entry_step"))
    fields = [f.name for f in draft.input_fields]
    out += [
        _issue(f"Two input fields are called {n}.", path=f"input_fields[{i}]")
        for i, n in enumerate(fields)
        if n in fields[:i]
    ]
    # Connection grants are keyed by pack name, so two packs an org can see never share one.
    name = draft.name.strip()
    if name.casefold() in {n.strip().casefold() for n in names}:
        out.append(
            _issue(f"Another pack is already called {name}. Give this one a different name.", path="name")
        )
    return out


def _route_issues(step: StepDraft, by_id: dict[str, StepDraft], entry: str) -> list[BuilderIssue]:
    at = f"steps.{step.id}.routes"
    if step.type == "end":
        return [_issue("An end step has no outcomes.", step.id, at)] if step.routes else []
    expected = outcomes(step)
    out = []
    for o in expected:
        target, where = step.routes.get(o), f"{at}.{o}"
        if not target:
            out.append(
                _issue(f"The {o} outcome of {step.id} goes nowhere. Connect it to a step.", step.id, where)
            )
        elif target not in by_id:
            out.append(
                _issue(
                    f"The {o} outcome of {step.id} goes to {target}, which does not exist.", step.id, where
                )
            )
        elif target == step.id:
            out.append(_issue(f"The {o} outcome of {step.id} goes back to itself.", step.id, where))
        elif target == entry:
            out.append(_issue(f"The {o} outcome of {step.id} goes back to the start.", step.id, where))
    out += [
        _issue(f"{step.id} has no {o} outcome.", step.id, f"{at}.{o}")
        for o in step.routes
        if o not in expected
    ]
    return out


def _is_expression(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("=")


def _ref(cfg: dict[str, Any], field: str) -> str | None:
    """A reference in a step's config, or None when it is missing or not text (config is client JSON)."""
    value = cfg.get(field)
    return value if isinstance(value, str) else None


def _arg_issues(step_id: str, tool_ref: str, args: Any, schema: dict, at: str) -> list[BuilderIssue]:
    """`args` against the tool's input schema (or one nested object property's): every key is a setting the
    tool has, every required setting is given, and every literal (non-"=") value fits. An expression's value
    is only known at run time, so only its key is checked."""
    if not isinstance(args, dict):
        return [_issue(f"The settings of {step_id} must be named values.", step_id, at)]
    props: dict[str, dict] = schema.get("properties") or {}
    out = []
    if schema.get("additionalProperties") is False:
        out += [
            _issue(f"{tool_ref} has no {k} setting.", step_id, f"{at}.{k}") for k in args if k not in props
        ]
    out += [
        _issue(f"{step_id} needs a value for {k}.", step_id, f"{at}.{k}")
        for k in schema.get("required") or []
        if k not in args
    ]
    for k, value in args.items():
        prop = props.get(k)
        if prop is None or _is_expression(value):
            continue
        if prop.get("type") == "object" and isinstance(value, dict):
            out += _arg_issues(step_id, tool_ref, value, prop, f"{at}.{k}")
            continue
        error = next(iter(Draft202012Validator(prop).iter_errors(value)), None)
        if error is not None:
            out.append(
                _issue(f"The {k} setting of {step_id} is not valid: {error.message}.", step_id, f"{at}.{k}")
            )
    return out


def _connector_issues(step: StepDraft, tools: dict[str, dict], at: str) -> list[BuilderIssue]:
    s, cfg = step.id, step.config
    ref = _ref(cfg, "tool")
    if ref is None or ref not in tools:
        return [_issue(f"Choose the app tool for step {s}.", s, f"{at}.tool")]
    tool = tools[ref]
    if tool["action_class"] in BLOCKED_CLASSES:
        return [_issue(f"{s} uses {ref}. A pack cannot delete records or move money.", s, f"{at}.tool")]
    out = []
    if "for_each" in cfg and not _is_expression(cfg["for_each"]):
        out.append(
            _issue(
                f"The list {s} repeats over must be an expression, such as =nodes.draft.output.drafts.",
                s,
                f"{at}.for_each",
            )
        )
    return out + _arg_issues(s, ref, cfg.get("args") or {}, tool.get("input_schema") or {}, f"{at}.args")


def _agent_step_issues(
    step: StepDraft, agents: dict[str, dict], schemas: set[str], at: str
) -> list[BuilderIssue]:
    """The agent exists and the step's result shape, when it overrides the agent's, is the one the agent
    answers in: a team agent's is always `shared/agent-result`, a seed agent's is its own and no other (the
    sandbox provider has no script for any other). An agent with no result shape of its own takes none."""
    s, cfg = step.id, step.config
    agent = agents.get(_ref(cfg, "agent") or "")
    if agent is None:
        return [_issue(f"Choose the agent for step {s}.", s, f"{at}.agent")]
    override = cfg.get("output_schema")
    if not override:
        return []
    where = f"{at}.output_schema"
    if not isinstance(override, str) or override not in schemas:
        return [_issue(f"The result shape of {s} does not exist.", s, where)]
    own = agent.get("output_schema_ref")
    if override == own:
        return []
    if own == AGENT_RESULT:
        return [
            _issue(
                f"{s} runs an agent your team built, whose result is always the agent result shape.", s, where
            )
        ]
    return [_issue(f"{cfg['agent']} answers only in its own result shape.", s, where)]


def _is_count(value: Any, most: int) -> bool:
    """A whole number from 1 to `most` (a bool is not one, though Python counts it as an int)."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= most


def _task_issues(step: StepDraft, at: str) -> list[BuilderIssue]:
    """A review or approval: titled, a review shows something, and any time limit is a sane number of
    seconds (the runtime adds it to the clock as it is)."""
    s, cfg = step.id, step.config
    what = "review" if step.type == "human_workforce" else "approval"
    out = []
    if not str(cfg.get("title") or "").strip():
        out.append(_issue(f"Give the {what} a title.", s, f"{at}.title"))
    if step.type == "human_workforce" and not cfg.get("show"):
        out.append(_issue("Choose what the reviewer is shown.", s, f"{at}.show"))
    if cfg.get("timeout_s") is not None and not _is_count(cfg["timeout_s"], TIMEOUT_MAX_S):
        out.append(
            _issue(
                f"The time limit of {s} must be a whole number of seconds, from 1 to {TIMEOUT_MAX_S}.",
                s,
                f"{at}.timeout_s",
            )
        )
    return out


def _memory_issues(step: StepDraft, spaces: set[str], at: str) -> list[BuilderIssue]:
    s, cfg = step.id, step.config
    if cfg.get("op", "recall") != "recall":
        return [_issue("A memory step can only recall.", s, f"{at}.op")]
    out = []
    if _ref(cfg, "space") not in spaces:
        out.append(_issue(f"Choose the memory {s} recalls from.", s, f"{at}.space"))
    if cfg.get("limit") is not None and not _is_count(cfg["limit"], MEMORY_LIMIT_MAX):
        out.append(
            _issue(
                f"The number of items {s} recalls must be a whole number from 1 to {MEMORY_LIMIT_MAX}.",
                s,
                f"{at}.limit",
            )
        )
    return out


def _verification_issues(step: StepDraft, schemas: set[str], at: str) -> list[BuilderIssue]:
    s, cfg = step.id, step.config
    checks = cfg.get("checks")
    if not checks and not cfg.get("schema"):
        return [_issue("Add a check or a result shape to verify.", s, at)]
    out = []
    if cfg.get("schema") and _ref(cfg, "schema") not in schemas:
        out.append(_issue(f"The result shape {s} checks against does not exist.", s, f"{at}.schema"))
    if checks and (not isinstance(checks, list) or not all(_is_expression(c) for c in checks)):
        out.append(
            _issue(
                f"The checks of {s} must be a list of expressions, each starting with =.", s, f"{at}.checks"
            )
        )
    return out


def _config_issues(
    step: StepDraft, tools: dict[str, dict], agents: dict[str, dict], spaces: set[str], schemas: set[str]
) -> list[BuilderIssue]:
    cfg, s = step.config, step.id
    at = f"steps.{s}.config"
    match step.type:
        case "connector":
            return _connector_issues(step, tools, at)
        case "agent":
            return _agent_step_issues(step, agents, schemas, at)
        case "memory":
            return _memory_issues(step, spaces, at)
        case "decision":
            if step.rules is None:
                return [_issue(f"Add the rules {s} decides with.", s, f"steps.{s}.rules")]
        case "human_workforce" | "approval":
            return _task_issues(step, at)
        case "verification":
            return _verification_issues(step, schemas, at)
        case "end":
            if cfg.get("status", "COMPLETED") not in END_STATUSES:
                return [_issue("An end step completes or fails the run.", s, f"{at}.status")]
    return []


def _reachable(entry: str, by_id: dict[str, StepDraft]) -> set[str]:
    seen: set[str] = set()
    todo = [entry]
    while todo:
        sid = todo.pop()
        if sid in seen or sid not in by_id:
            continue
        seen.add(sid)
        todo += list(by_id[sid].routes.values())
    return seen


def _completes(step: StepDraft) -> bool:
    return step.type == "end" and step.config.get("status", "COMPLETED") == "COMPLETED"


def _graph_issues(draft: PackDraft, by_id: dict[str, StepDraft]) -> list[BuilderIssue]:
    if draft.entry_step not in by_id:
        return []
    reached = _reachable(draft.entry_step, by_id)
    out = [
        _issue(f"Nothing leads to step {s.id}.", s.id, f"steps.{s.id}")
        for s in draft.steps
        if s.id not in reached
    ]
    if not any(_completes(s) and s.id in reached for s in draft.steps):
        out.append(_issue("The pack never completes. Add an end step that completes the run.", path="steps"))
    return out


def _unlock_issues(
    draft: PackDraft, tools: dict[str, dict], by_id: dict[str, StepDraft]
) -> tuple[list[BuilderIssue], set[str]]:
    """The problems with what approvals also unlock, and the steps whose unlock is sound: a write an approval
    also unlocks must be a step that writes, reached only through that approval's granted outcome and the
    other steps it unlocks, and not after a refusal or on a loop (`unlocks.chain_problems`)."""
    routes = {s.id: dict(s.routes) for s in draft.steps}
    out: list[BuilderIssue] = []
    sound: set[str] = set()
    for approval in (s for s in draft.steps if s.type == "approval"):
        also = approval.config.get("also_unlocks")
        if also is None:
            continue
        if not isinstance(also, list):
            out.append(
                _issue(
                    f"also_unlocks of {approval.id} must be a list of steps.",
                    approval.id,
                    f"steps.{approval.id}",
                )
            )
            continue
        usable = []
        for target in also:
            step = by_id.get(target) if isinstance(target, str) else None
            tool = tools.get(_ref(step.config, "tool") or "") if step and step.type == "connector" else None
            if tool is None or tool["action_class"] == READ:
                out.append(
                    _issue(
                        f"{approval.id} also unlocks {target}, which is not a step that changes data.",
                        approval.id,
                        f"steps.{approval.id}",
                    )
                )
            else:
                usable.append(target)
        problems = unlocks.chain_problems(routes, approval.id, usable)
        for target, why in problems.items():
            out.append(_issue(f"{target} {why}.", target, f"steps.{target}"))
        sound |= {t for t in usable if t not in problems}
    return out, sound


def _approval_issues(draft: PackDraft, tools: dict[str, dict]) -> list[BuilderIssue]:
    """A step that changes data in an app runs only straight after an approval was granted: the gateway lets a
    write through only for the step at an approval's granted outcome, and for the writes that approval also
    unlocks when they follow it in one closed chain."""
    by_id = {s.id: s for s in draft.steps}
    out, unlocked = _unlock_issues(draft, tools, by_id)
    incoming: dict[str, list[tuple[StepDraft, str]]] = {}
    for s in draft.steps:
        for o, target in s.routes.items():
            incoming.setdefault(target, []).append((s, o))
    for s in draft.steps:
        tool = tools.get(_ref(s.config, "tool") or "") if s.type == "connector" else None
        if tool is None or tool["action_class"] == READ or s.id in unlocked:
            continue  # anything that is not a read needs the approval
        if any(src.type != "approval" or o != "granted" for src, o in incoming.get(s.id, [])):
            out.append(
                _issue(
                    f"{s.id} changes data in {tool['app']}, so every path into it must come from an "
                    "approval's granted outcome.",
                    s.id,
                    f"steps.{s.id}",
                )
            )
    return out


def pack_issues(
    draft: PackDraft,
    tools: dict[str, dict],
    agents: dict[str, dict],
    spaces: set[str],
    schemas: set[str],
    *,
    names: Iterable[str],
) -> list[BuilderIssue]:
    """What the definition validator cannot check, each naming its step: one start, every outcome connected
    and nowhere backwards, every step reachable, a completing end, references that exist, app settings that
    fit the tool, writes only after an approval. The caller passes `names`, the names of the packs the org
    can see minus the pack's own key: connection grants are keyed by pack name, so the draft must not
    repeat one."""
    by_id = {s.id: s for s in draft.steps}
    issues = _structure_issues(draft, by_id, names)
    for step in draft.steps:
        issues += _route_issues(step, by_id, draft.entry_step)
        issues += _config_issues(step, tools, agents, spaces, schemas)
    issues += _graph_issues(draft, by_id)
    issues += _approval_issues(draft, tools)
    return issues


def input_schema(name: str, fields: list[InputField]) -> dict:
    """The run input schema: one property per field, titled with its label (the start form's label)."""
    props: dict[str, dict] = {}
    for f in fields:
        if f.type == "date":
            props[f.name] = {"title": f.label, "type": "string", "pattern": DATE_PATTERN}
        elif f.type == "number":
            props[f.name] = {"title": f.label, "type": "number"}
        else:
            props[f.name] = {"title": f.label, "type": "string", "minLength": 1, "maxLength": TEXT_MAX}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{name} input",
        "type": "object",
        "additionalProperties": False,
        "required": [f.name for f in fields if f.required],
        "properties": props,
    }


def input_fields(schema: dict) -> list[InputField]:
    required = set(schema.get("required") or [])
    out = []
    for name, prop in (schema.get("properties") or {}).items():
        if prop.get("pattern") == DATE_PATTERN:
            kind = "date"
        elif prop.get("type") in ("number", "integer"):
            kind = "number"
        else:
            kind = "text"
        out.append(
            InputField(name=name, label=str(prop.get("title") or name), type=kind, required=name in required)
        )
    return out


def readable_input_fields(schema: dict, limit: int) -> tuple[list[InputField], list[BuilderIssue]]:
    """The input fields of a schema a draft can hold (at most `limit`); each property that cannot be an
    InputField, and each one past the limit, is left out and reported."""
    required = set(schema.get("required") or [])
    out: list[InputField] = []
    issues: list[BuilderIssue] = []
    for name, prop in (schema.get("properties") or {}).items():
        prop = prop if isinstance(prop, dict) else {}
        try:
            if len(out) >= limit:
                raise ValueError("too many")
            [field] = input_fields({"required": list(required), "properties": {name: prop}})
            out.append(field)
        except ValueError, TypeError, ValidationError:
            issues.append(
                BuilderIssue(
                    path=f"input_fields[{name}]",
                    message=f"The input {name} cannot be edited in the Studio and was left out.",
                )
            )
    return out, issues


def _code(route: str) -> str:
    return _NOT_CODE.sub("_", route.upper()).strip("_") or "RULE"


def _rules_body(rules: DecisionRules) -> dict:
    body = {
        "question": rules.question,
        "rules": [
            {
                "when": r.when.removeprefix("="),
                "verdict": r.verdict,
                "route": r.route,
                "reason_code": _code(r.route),
                "explanation": r.explanation,
            }
            for r in rules.rules
        ],
        "default": {
            "verdict": rules.default.verdict,
            "route": rules.default.route,
            "reason_code": _code(rules.default.route),
            "explanation": rules.default.explanation,
        },
    }
    if rules.evaluator:
        body["evaluator"] = deepcopy(rules.evaluator)
    return body


def rules_of(body: dict) -> DecisionRules:
    """A decision rules definition as the Studio edits it (reason codes are made again on save); its
    evaluator, which the Studio does not edit, is kept as it is."""
    default = body["default"]
    return DecisionRules(
        evaluator=deepcopy(body["evaluator"]) if body.get("evaluator") else None,
        question=body["question"],
        rules=[
            DecisionRule(when=r["when"], route=r["route"], verdict=r["verdict"], explanation=r["explanation"])
            for r in body.get("rules") or []
        ],
        default=DecisionDefault(
            route=default["route"], verdict=default["verdict"], explanation=default["explanation"]
        ),
    )


def _node(pack_key: str, step: StepDraft) -> dict:
    config = {"rules": rules_key(pack_key, step.id)} if step.type == "decision" else deepcopy(step.config)
    node = {"id": step.id, "type": step.type, "version": "1", "config": config}
    if step.type != "end":
        node["routes"] = dict(step.routes)
    return node


def step_of(node: dict, rules: DecisionRules | None = None) -> StepDraft:
    """A workflow node as a step: a connector's "next" becomes "ok", a decision's rules are inlined."""
    routes = dict(node.get("routes") or {})
    if node["type"] == "connector" and "next" in routes and "ok" not in routes:
        routes["ok"] = routes.pop("next")
    config = {} if node["type"] == "decision" else deepcopy(node.get("config") or {})
    return StepDraft(id=node["id"], type=node["type"], config=config, routes=routes, rules=rules)


def _first(draft: PackDraft, test) -> str | None:
    return next((s.id for s in draft.steps if test(s)), None)


def _contract(key: str, draft: PackDraft, capabilities: list[str], release: int) -> dict:
    verify = next((s for s in draft.steps if s.type == "verification"), None)
    success = (verify.routes.get("pass") if verify else None) or _first(draft, _completes) or draft.entry_step
    failure = _first(draft, lambda s: s.type == "end" and s.config.get("status") == "FAILED") or success
    review = _first(draft, lambda s: s.type == "human_workforce")
    output = str(verify.config.get("schema") or "") if verify else ""
    output = output or AGENT_RESULT
    routes = {"success": success, "failure": failure, "timeout": failure}
    if review:
        routes["human_review"] = review
    return {
        "schema_version": "nm.work_contract.v1",
        "contract_id": key,
        "version": release,
        "org_id": "{org}",
        "capability": f"team.{owners.name_of(key).replace('-', '_')}",
        "input_schema_ref": input_key(key),
        "output_schema_ref": output,
        "acceptance": {"verification_ruleset_ref": output, "buyer_acceptance_required": False},
        "authorization": {
            "tool_capabilities": capabilities,
            "region_policy_ref": f"region/{REGION}",
            "policy_ref": POLICY_REF,
        },
        "budget": {
            "currency": CURRENCY,
            "maximum_minor": draft.budget_minor,
            "human_budget_minor": draft.human_budget_minor,
        },
        "limits": {"max_attempts": CONTRACT_ATTEMPTS, "deadline_s": DEADLINE_S},
        "routes": routes,
    }


def pack_definitions(
    key: str, org: OrgRef, draft: PackDraft, tools: dict[str, dict], agents: dict[str, dict], release: int
) -> list[Definition]:
    """The definitions of `draft` at release `release`: pack (1.0.<release>), workflow ("<release>"), contract
    (<release>), input schema and one decision rules definition per decision step. Call only for a draft
    with no `pack_issues`. The pack's `slug` is its key, so it never shadows a platform pack."""
    org_key_check(key, org)
    used_agents = sorted({str(s.config["agent"]) for s in draft.steps if s.type == "agent"})
    refs = {str(s.config["tool"]) for s in draft.steps if s.type == "connector"}
    for a in used_agents:
        refs.update(r for r in (agents[a].get("runtime") or {}).get("tools") or [] if r in tools)
    capabilities = sorted({tools[r]["capability"] for r in refs})
    writes = any(tools[r]["action_class"] != READ for r in refs)
    pack = {
        "slug": key,
        "name": draft.name.strip(),
        "version": f"1.0.{release}",
        "publisher": org.name,
        "function": draft.function,
        "industries": list(draft.industries),
        "outcome": draft.outcome.strip(),
        "description": draft.description.strip(),
        "risk_class": "medium" if writes else "low",
        "price_note": f"Built by your team. Up to {money_text(draft.budget_minor)} of AI work per run.",
        "workflow": key,
        "contract": key,
        "agents": used_agents,
        "connectors": sorted({r.partition(".")[0] for r in refs}),
        "human_review": draft.human_review.strip(),
        "deliverable_view": deepcopy(DELIVERABLE_VIEW),
    }
    workflow = {
        "schema_version": "nm.workflow.v1",
        "workflow_id": key,
        "version": str(release),
        "entry_node_id": draft.entry_step,
        "default_policy_ref": POLICY_REF,
        "work_contract_ref": key,
        "limits": {
            "max_duration_s": DEADLINE_S,
            "max_cost_minor": draft.budget_minor,
            "currency": CURRENCY,
            "max_parallel_nodes": 1,
            "max_total_node_attempts": MAX_ATTEMPTS,
        },
        "nodes": [_node(key, s) for s in draft.steps],
    }

    def made(kind: str, k: str, body: dict) -> Definition:
        return Definition(kind=kind, key=k, body=body, path=path_for(kind, k))

    out = [
        made("pack", key, pack),
        made("workflow", key, workflow),
        made("contract", key, _contract(key, draft, capabilities, release)),
        made("schema", input_key(key), input_schema(draft.name.strip(), draft.input_fields)),
    ]
    out += [
        made("decision_rules", rules_key(key, s.id), _rules_body(s.rules))
        for s in draft.steps
        if s.type == "decision" and s.rules is not None
    ]
    return out


def pack_draft(pack: dict, workflow: dict, contract: dict, schema: dict, rules: dict[str, dict]) -> PackDraft:
    """The draft a pack built by `pack_definitions` was made from. `rules` maps a decision step's id to its
    decision rules body."""
    budget = contract.get("budget") or {}
    steps = [
        step_of(n, rules_of(rules[n["id"]]) if n["type"] == "decision" and n["id"] in rules else None)
        for n in workflow["nodes"]
    ]
    return PackDraft(
        name=pack["name"],
        outcome=pack["outcome"],
        description=pack["description"],
        human_review=pack["human_review"],
        function=pack["function"],
        industries=list(pack["industries"]),
        input_fields=input_fields(schema),
        budget_minor=int(budget.get("maximum_minor") or PackDraft.model_fields["budget_minor"].default),
        human_budget_minor=int(budget.get("human_budget_minor") or 0),
        entry_step=workflow["entry_node_id"],
        steps=steps,
    )


def issue_of(error: DefError, pack_key: str) -> BuilderIssue:
    """A definition validator error as a builder issue, naming the step: a workflow error starts
    "nodes[i] (<id>)", and a decision step's rules are keyed <pack key>--<step id>."""
    step = None
    if error.kind == "workflow" and (found := _NODE_AT.match(error.message)):
        step = found.group(1)
    elif error.kind == "decision_rules" and error.key.startswith(pack_key + SEPARATOR):
        step = error.key[len(pack_key) + len(SEPARATOR) :]
    return BuilderIssue(path=f"{error.kind}/{error.key}", message=error.message, step=step)
