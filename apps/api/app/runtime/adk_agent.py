"""Google ADK adapter: runs an agent definition as an ADK LlmAgent inside PackRunner.

ADK drives the turn loop. Every model turn and tool call is still one of our activities, supplied by the
workflow through AgentHooks, so contract capabilities, policy decisions, spend and receipts are unchanged.
This module runs workflow-side: no I/O, no clocks, no randomness of its own (GoogleAdkPlugin makes ADK's own
deterministic). Only `warm_up` runs outside a workflow, once per worker process.
"""

import asyncio
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools import BaseTool, ToolContext
from google.genai import types
from pydantic import PrivateAttr

from app.runtime.agent import REPROMPT, cut_off_results, cut_off_uses
from app.runtime.providers import SUBMIT_TOOL

log = logging.getLogger(__name__)

APP_NAME = "new_machines"
MODEL_NAME = "nm/agent"


class TurnsExhausted(Exception):
    pass


class OutputTruncated(Exception):
    """Every turn left was cut off at the output limit."""


@dataclass
class AgentHooks:
    model: Callable[[str, list[dict], list[dict]], Awaitable[tuple[list[dict], str]]]  # content, stop reason
    tool: Callable[[dict], Awaitable[dict]]
    submit: Callable[[Any], Awaitable[tuple[Any, str]]]


def adk_name(agent_id: str) -> str:
    return agent_id.replace("-", "_")


# --- conversion: ADK request <-> our provider-neutral message format ----------------------------------------


def _blocks(content: types.Content) -> list[dict]:
    blocks: list[dict] = []
    for part in content.parts or []:
        if part.function_call is not None:
            fc = part.function_call
            blocks.append({"type": "tool_use", "id": fc.id, "name": fc.name, "input": dict(fc.args or {})})
        elif part.function_response is not None:
            fr = part.function_response
            response = fr.response or {}
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": fr.id,
                    "content": str(response.get("content", json.dumps(response, ensure_ascii=False))),
                    "is_error": bool(response.get("is_error", False)),
                }
            )
        elif part.text:
            blocks.append({"type": "text", "text": part.text})
    return blocks


def _message(role: str, blocks: list[dict]) -> dict:
    if role == "user" and blocks and all(b["type"] == "text" for b in blocks):
        return {"role": role, "content": "\n\n".join(b["text"] for b in blocks)}
    return {"role": role, "content": blocks}


def to_provider_request(llm_request: LlmRequest) -> tuple[str, list[dict], list[dict]]:
    config = llm_request.config
    system = str(config.system_instruction or "") if config else ""
    merged: list[tuple[str, list[dict]]] = []
    for content in llm_request.contents or []:
        role = "assistant" if content.role == "model" else "user"
        blocks = _blocks(content)
        if not blocks:
            continue
        if merged and merged[-1][0] == role:
            merged[-1][1].extend(blocks)
        else:
            merged.append((role, blocks))
    tools = [
        {
            "name": d.name,
            "description": d.description or "",
            "input_schema": d.parameters_json_schema or {"type": "object"},
        }
        for tool in ((config.tools if config else None) or [])
        for d in (getattr(tool, "function_declarations", None) or [])
    ]
    return system, [_message(role, blocks) for role, blocks in merged], tools


def to_llm_response(content: list[dict]) -> LlmResponse:
    parts = []
    for block in content:
        if block.get("type") == "text" and block.get("text"):
            parts.append(types.Part(text=block["text"]))
        elif block.get("type") == "tool_use":
            call = types.FunctionCall(id=block["id"], name=block["name"], args=block.get("input") or {})
            parts.append(types.Part(function_call=call))
    # Token counts and spend are recorded by our model_call activity; an empty usage record only stops ADK
    # from warning on every turn that it has none.
    return LlmResponse(
        content=types.Content(role="model", parts=parts),
        usage_metadata=types.GenerateContentResponseUsageMetadata(),
    )


def _submit_wins(content: list[dict]) -> list[dict]:
    """As in the hosted loop (`agent.next_step`): a turn that calls submit_result runs only its first
    submit_result call, and no other tool alongside it, so finish_node runs once."""
    uses = [b for b in content if b.get("type") == "tool_use"]
    first = next((b for b in uses if b.get("name") == SUBMIT_TOOL), None)
    if first is None:
        return content
    return [b for b in content if b.get("type") != "tool_use" or b is first]


# --- ADK pieces ------------------------------------------------------------------------------------------


class NmAdkModel(BaseLlm):
    """One model turn = the workflow's model hook (our model_call activity). Counts turns across
    invocations. A turn cut off at the output limit never reaches ADK, so its calls (a partial submit_result
    above all) never run: the model is told so and asked again, within max_turns."""

    _hooks: AgentHooks = PrivateAttr()
    _max_turns: int = PrivateAttr()
    _turns: int = PrivateAttr(default=0)

    def __init__(self, hooks: AgentHooks, max_turns: int) -> None:
        super().__init__(model=MODEL_NAME)
        self._hooks, self._max_turns = hooks, max_turns

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        system, messages, tools = to_provider_request(llm_request)
        cut: list[dict] = []
        while True:
            if self._turns >= self._max_turns:
                raise (OutputTruncated if cut else TurnsExhausted)(self._max_turns)
            self._turns += 1
            content, stop_reason = await self._hooks.model(system, messages, tools)
            cut = cut_off_uses(content, stop_reason)
            if not cut:
                yield to_llm_response(_submit_wins(content))
                return
            feedback = {"role": "user", "content": cut_off_results(cut)}
            messages = [*messages, {"role": "assistant", "content": content}, feedback]


def _declaration(name: str, description: str, schema: dict) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(name=name, description=description, parameters_json_schema=schema)


class GatewayTool(BaseTool):
    """A connector tool. The call runs the workflow's tool hook (our tool_call activity, through the
    gateway)."""

    def __init__(self, spec: dict, hooks: AgentHooks) -> None:
        super().__init__(name=spec["name"], description=spec.get("description", ""))
        self._schema, self._hooks = spec.get("input_schema") or {"type": "object"}, hooks

    def _get_declaration(self) -> types.FunctionDeclaration:
        return _declaration(self.name, self.description, self._schema)

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        return await _gateway_call(self._hooks, self.name, args, tool_context)


async def _gateway_call(hooks: AgentHooks, name: str, args: dict, tool_context: ToolContext) -> dict:
    block = {"type": "tool_use", "id": tool_context.function_call_id, "name": name, "input": dict(args or {})}
    result = await hooks.tool(block)
    return {"content": result["content"], "is_error": result["is_error"]}


def _unoffered_to_gateway(hooks: AgentHooks, offered: set[str]):
    """ADK answers a call to a tool it does not hold by itself. As in the hosted loop, such a call goes to the
    gateway instead, which denies it (TOOL_NOT_OFFERED) and records the attempt on the receipt."""

    async def before_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
        if tool.name in offered:
            return None
        return await _gateway_call(hooks, tool.name, args, tool_context)

    return before_tool


class SubmitTool(BaseTool):
    """submit_result: validates through the workflow's submit hook (finish_node) and ends the agent's loop."""

    def __init__(self, spec: dict, hooks: AgentHooks, sink: dict) -> None:
        super().__init__(name=SUBMIT_TOOL, description=spec.get("description", ""))
        self._schema, self._hooks, self._sink = spec.get("input_schema") or {"type": "object"}, hooks, sink

    def _get_declaration(self) -> types.FunctionDeclaration:
        return _declaration(self.name, self.description, self._schema)

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        self._sink["result"] = await self._hooks.submit(dict(args))
        tool_context.actions.skip_summarization = True
        return {"ok": True}


async def run_agent(spec: dict, hooks: AgentHooks, session_user: str) -> tuple[Any, str]:
    """Run until submit_result succeeds; a text-only answer is re-prompted. Raises TurnsExhausted, or
    OutputTruncated when the last turn was cut off at the output limit."""
    sink: dict = {}
    tools: list[BaseTool] = [GatewayTool(t, hooks) for t in spec["tools"] if t["name"] != SUBMIT_TOOL]
    submit = next(t for t in spec["tools"] if t["name"] == SUBMIT_TOOL)
    tools.append(SubmitTool(submit, hooks, sink))
    system = spec["system"]
    agent = LlmAgent(
        name=adk_name(spec["agent_id"]),
        model=NmAdkModel(hooks, int(spec["max_turns"])),
        instruction=lambda _ctx: system,  # a callable: ADK does not template {braces} in it
        tools=tools,
        before_tool_callback=_unoffered_to_gateway(hooks, {t.name for t in tools}),
    )
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=session_user)
    text = spec["messages"][0]["content"]
    while "result" not in sink:
        message = types.Content(role="user", parts=[types.Part(text=text)])
        events = runner.run_async(user_id=session_user, session_id=session.id, new_message=message)
        async with aclosing(events) as stream:
            async for _ in stream:
                pass
        text = REPROMPT
    return sink["result"]


# --- warm-up ---------------------------------------------------------------------------------------------


async def _warm_model(system: str, messages: list[dict], tools: list[dict]) -> tuple[list[dict], str]:
    return [{"type": "tool_use", "id": "warm_up", "name": SUBMIT_TOOL, "input": {}}], "tool_use"


async def _warm_tool(block: dict) -> dict:  # never called: the warm-up agent offers only submit_result
    raise AssertionError("the warm-up agent has no connector tools")


async def _warm_submit(value: Any) -> tuple[Any, str]:
    return value, "default"


_WARM_SPEC = {
    "agent_id": "warm-up",
    "system": "agent:warm-up",
    "messages": [{"role": "user", "content": "Call submit_result."}],
    "tools": [{"name": SUBMIT_TOOL, "description": "", "input_schema": {"type": "object"}}],
    "max_turns": 1,
}


WARM_UP_TIMEOUT = 30.0  # seconds; the warm-up normally takes about 4
_warmed = False  # set when the warm-up starts, so a supervisor retry rebuilding the worker never reruns it


def warm_up(timeout: float = WARM_UP_TIMEOUT) -> None:
    """Run one stub agent outside any workflow. ADK's first model turn in a process imports its optional model
    SDKs (about 4 s); inside a workflow activation that trips Temporal's 2 s deadlock detector. Workers call
    this before polling. Its own thread and loop, so it works whether or not the caller has a running loop.

    At most once per process. A warm-up still running after `timeout` is logged and abandoned (its daemon
    thread finishes or dies with the process), so a hang never leaves a worker that silently never polls."""
    global _warmed
    if _warmed:
        return
    _warmed = True
    hooks = AgentHooks(model=_warm_model, tool=_warm_tool, submit=_warm_submit)
    errors: list[BaseException] = []

    def main() -> None:
        try:
            asyncio.run(run_agent(_WARM_SPEC, hooks, session_user="warm_up"))
        except BaseException as exc:  # re-raised on the caller's thread
            errors.append(exc)

    thread = threading.Thread(target=main, name="adk-warm-up", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        log.error("ADK warm-up still running after %.0f s; the worker starts polling without it", timeout)
        return
    if errors:
        raise errors[0]
