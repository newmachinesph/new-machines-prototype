"""Shared checks for the sample packs: the real bundle, the definition validator, a pack's own sandbox data,
the approval-before-write rule and one sandbox run through PackRunner on the fake model.

A test module that calls `run_pack` must also import the `runtime_env` fixture:
`from tests.test_workflow import runtime_env  # noqa: F401`.
"""

import asyncio
import json
from functools import cache

from jsonschema import Draft202012Validator

from app import settings
from app.defs.loader import load_bundle
from app.defs.validate import validate_bundle
from app.worker.workflow import PackRunner
from tests.test_workflow import _drive, _new_run, _start, _waiting

PERSONAL_DATA_LINE = (
    "Never include email addresses, phone numbers or customer message text in a `note` or `flag`."
)
HUMAN = "human"
APPROVAL = "approval"
REVIEW_NOTE = "Checked."
GRANTED_BY = "buyer@demo"


@cache
def bundle():
    return load_bundle(settings.defs_dir())


def bundle_errors() -> list[str]:
    return [str(e) for e in validate_bundle(bundle())]


def body(kind: str, key: str) -> dict:
    return bundle().get(kind, key).body


def workflow(pack: str) -> dict:
    return body("workflow", pack)


def node(pack: str, node_id: str) -> dict:
    return next(n for n in workflow(pack)["nodes"] if n["id"] == node_id)


def schema_errors(schema_key: str, value) -> list[str]:
    validator = Draft202012Validator(body("schema", schema_key))
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(value)]


def sandbox(pack: str, connector: str, tool: str):
    path = settings.defs_dir() / "packs" / pack / "sandbox" / connector / f"{tool}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _action_class(n: dict) -> str:
    connector, _, tool_id = n["config"]["tool"].partition(".")
    tool = next(t for t in body("connector", connector)["tools"] if t["id"] == tool_id)
    return tool["action_class"]


def writes_without_approval(pack: str) -> list[str]:
    """Every way into a connector step that is not a read, other than an approval's `granted` route (the
    Studio builder's rule; a grant approves exactly the step its granted route names)."""
    nodes = workflow(pack)["nodes"]
    problems = []
    for target in nodes:
        if target["type"] != "connector" or _action_class(target) == "read":
            continue
        incoming = [(s, r) for s in nodes for r, t in (s.get("routes") or {}).items() if t == target["id"]]
        if not incoming:
            problems.append(f"nothing leads to {target['id']}")
        for source, route in incoming:
            if not (source["type"] == "approval" and route == "granted"):
                problems.append(f"{source['id']}.{route} -> {target['id']}")
    return problems


def decision_routes(rules_key: str) -> set[str]:
    """Every route a decision body can take: its rules, its default and its evaluator's on_error."""
    rules = body("decision_rules", rules_key)
    routes = {r["route"] for r in rules.get("rules") or []} | {rules["default"]["route"]}
    if rules.get("evaluator"):
        routes.add(rules["evaluator"]["on_error"]["route"])
    return routes


def skill_text(agent_key: str) -> str:
    agent = bundle().get("agent", agent_key)
    return "\n".join(agent.files[s] for s in agent.body["runtime"]["skills"])


def run_pack(conn, pack: str, input: dict, stops: list[tuple[str, str]]) -> tuple[str, dict, str]:
    """Start `pack` on sandbox data and the fake model, answer each (node id, HUMAN | APPROVAL) stop in order
    (a person resolves; the buyer grants), and return (run id, snapshot, final status)."""
    run_id, snapshot = _new_run(conn, pack=pack, input=input)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot, input)
        for node_id, kind in stops:
            task = await _waiting(handle, node_id)
            if kind == HUMAN:
                await handle.signal(PackRunner.human_result, args=[task["task_id"], "resolved", REVIEW_NOTE])
            else:
                await handle.signal(PackRunner.approval, args=[task["task_id"], "granted", GRANTED_BY])
        return await handle.result()

    return run_id, snapshot, asyncio.run(_drive(None, scenario))
