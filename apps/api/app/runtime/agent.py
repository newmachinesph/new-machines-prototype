"""Agent loop helpers: prompts, the tools an agent may use, and what to do after each model turn."""

import json
from typing import Any

from app.runtime.gateway import contract_of, find_tool
from app.runtime.providers import AGENT_MARKER, INPUTS_HEADING, SUBMIT_TOOL, ModelTurn, ToolSpec

REPROMPT = "Call submit_result."
CUT_OFF_STOP = "max_tokens"  # the provider's stop reason when a turn reaches the output limit
CUT_OFF = (
    "Your answer was cut off at the output limit, so it was not used. "
    "Submit again, shorter: keep every text field to one short line."
)
SUBMIT_DESCRIPTION = "Submit the final result in the required shape. Call it once, when the work is done."
RESUBMIT_HINT = "Fix these fields and call submit_result again with the whole result."
_NAME_SEPARATOR = (
    "__"  # tool names allow [A-Za-z0-9_-] only, so "shopify.list_orders" -> "shopify__list_orders"
)


def build_system(agent_def: dict) -> str:
    """`agent_def` is {"body", "files"}: "agent:<id>", then the instructions, then every skill."""
    body, files = agent_def["body"], agent_def.get("files") or {}
    runtime = body.get("runtime") or {}
    parts = [f"{AGENT_MARKER}{body['agent_id']}", files[runtime["instructions"]].strip()]
    skills = [files[name].strip() for name in runtime.get("skills") or []]
    if skills:
        parts.append("# Skills\n" + "\n\n".join(skills))
    return "\n\n".join(parts)


def build_user_message(task: str, inputs: dict) -> str:
    payload = json.dumps(inputs, indent=2, ensure_ascii=False)
    return f"{task.strip()}\n\n{INPUTS_HEADING}\n\n```json\n{payload}\n```"


def tool_name(tool_ref: str) -> str:
    return tool_ref.replace(".", _NAME_SEPARATOR, 1)


def tool_ref(name: str) -> str:
    return name.replace(_NAME_SEPARATOR, ".", 1)


def agent_tools(agent_body: dict, snapshot: dict, output_schema: dict) -> list[ToolSpec]:
    """The agent's connector tools whose capability the contract grants, plus submit_result."""
    granted = set((contract_of(snapshot).get("authorization") or {}).get("tool_capabilities") or [])
    specs = []
    for ref in (agent_body.get("runtime") or {}).get("tools") or []:
        found = find_tool(snapshot, ref)
        if found is None or found[2].get("capability") not in granted:
            continue
        tool = found[2]
        specs.append(
            ToolSpec(
                name=tool_name(ref),
                description=tool.get("description", ""),
                input_schema=tool.get("input_schema") or {"type": "object"},
            )
        )
    schema = {k: v for k, v in output_schema.items() if k != "$schema"}
    specs.append(ToolSpec(name=SUBMIT_TOOL, description=SUBMIT_DESCRIPTION, input_schema=schema))
    return specs


def cut_off_uses(content: list[dict], stop_reason: str) -> list[dict]:
    """The tool calls of a turn cut off at the output limit. Their input may be incomplete, so none runs."""
    if stop_reason != CUT_OFF_STOP:
        return []
    return [b for b in content if b.get("type") == "tool_use"]


def cut_off_results(uses: list[dict]) -> list[dict]:
    """One error tool_result per held-back call, asking the model to submit again, shorter."""
    return [
        {"type": "tool_result", "tool_use_id": b.get("id"), "content": CUT_OFF, "is_error": True}
        for b in uses
    ]


def rejection(errors: list[str]) -> dict:
    """What submit_result answers when finish_node rejected the result: the schema errors, and what to do."""
    return {"ok": False, "errors": list(errors), "hint": RESUBMIT_HINT}


def rejected_results(content: list[dict], errors: list[str]) -> list[dict]:
    """The error tool_result for the turn's submit_result call, carrying the schema errors."""
    submit = next(b for b in content if b.get("type") == "tool_use" and b.get("name") == SUBMIT_TOOL)
    payload = json.dumps(rejection(errors), ensure_ascii=False)
    return [{"type": "tool_result", "tool_use_id": submit.get("id"), "content": payload, "is_error": True}]


def next_step(turn: ModelTurn) -> tuple[str, Any]:
    """("submit", result) | ("tools", [tool_use blocks]) | ("text", text): re-prompt once with REPROMPT |
    ("truncated", [tool_use blocks]): answer them with `cut_off_results`."""
    cut = cut_off_uses(turn.content, turn.stop_reason)
    if cut:
        return "truncated", cut
    uses = [b for b in turn.content if b.get("type") == "tool_use"]
    submit = next((b for b in uses if b.get("name") == SUBMIT_TOOL), None)
    if submit is not None:
        return "submit", submit.get("input")
    if uses:
        return "tools", uses
    return "text", "\n".join(b.get("text", "") for b in turn.content if b.get("type") == "text")
