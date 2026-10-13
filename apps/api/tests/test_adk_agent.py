import asyncio
import threading

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from app.runtime import adk_agent


def _request(contents, tools=()):
    decls = [
        types.FunctionDeclaration(name=n, description="d", parameters_json_schema={"type": "object"})
        for n in tools
    ]
    config = types.GenerateContentConfig(
        system_instruction="agent:finance-agent\n\nDo it.",
        tools=[types.Tool(function_declarations=decls)] if decls else None,
    )
    return LlmRequest(model="nm/agent", contents=contents, config=config)


def test_first_user_text_becomes_a_string_message():
    req = _request([types.Content(role="user", parts=[types.Part(text="Match.\n\n# Inputs")])])
    system, messages, tools = adk_agent.to_provider_request(req)
    assert system.startswith("agent:finance-agent\n")
    assert messages == [{"role": "user", "content": "Match.\n\n# Inputs"}]
    assert tools == []


def test_function_call_and_response_become_tool_use_and_tool_result():
    call = types.Part(
        function_call=types.FunctionCall(id="c1", name="shopify__list_orders", args={"limit": 5})
    )
    resp = types.Part(
        function_response=types.FunctionResponse(
            id="c1", name="shopify__list_orders", response={"content": "[]", "is_error": False}
        )
    )
    req = _request(
        [
            types.Content(role="user", parts=[types.Part(text="go")]),
            types.Content(role="model", parts=[call]),
            types.Content(role="user", parts=[resp]),
        ],
        tools=["shopify__list_orders", "submit_result"],
    )
    _, messages, tools = adk_agent.to_provider_request(req)
    assert messages[1] == {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": "c1", "name": "shopify__list_orders", "input": {"limit": 5}}],
    }
    assert messages[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "[]", "is_error": False}],
    }
    assert [t["name"] for t in tools] == ["shopify__list_orders", "submit_result"]
    assert tools[0] == {
        "name": "shopify__list_orders",
        "description": "d",
        "input_schema": {"type": "object"},
    }


def test_consecutive_same_role_messages_are_merged():
    req = _request(
        [
            types.Content(role="user", parts=[types.Part(text="a")]),
            types.Content(role="user", parts=[types.Part(text="b")]),
        ]
    )
    _, messages, _ = adk_agent.to_provider_request(req)
    assert messages == [{"role": "user", "content": "a\n\nb"}]


def test_model_content_blocks_become_an_llm_response():
    resp = adk_agent.to_llm_response(
        [
            {"type": "text", "text": "thinking aloud"},
            {"type": "tool_use", "id": "t1", "name": "submit_result", "input": {"x": 1}},
        ]
    )
    parts = resp.content.parts
    assert resp.content.role == "model"
    assert parts[0].text == "thinking aloud"
    assert (parts[1].function_call.id, parts[1].function_call.name, parts[1].function_call.args) == (
        "t1",
        "submit_result",
        {"x": 1},
    )


def test_adk_name_is_a_python_identifier():
    assert adk_agent.adk_name("finance-agent") == "finance_agent"


def _use(id_: str, name: str) -> dict:
    return {"type": "tool_use", "id": id_, "name": name, "input": {"n": id_}}


def test_submit_wins_keeps_only_the_first_submit_and_no_other_tool():
    text = {"type": "text", "text": "done"}
    content = [
        text,
        _use("t1", "shopify__list_orders"),
        _use("s1", "submit_result"),
        _use("s2", "submit_result"),
        _use("t2", "stripe__list_charges"),
    ]
    assert adk_agent._submit_wins(content) == [text, _use("s1", "submit_result")]


def test_submit_wins_leaves_a_turn_without_submit_alone():
    content = [{"type": "text", "text": "a"}, _use("t1", "shopify__list_orders"), _use("t2", "x__y")]
    assert adk_agent._submit_wins(content) == content


def test_an_llm_response_carries_a_usage_record():
    assert adk_agent.to_llm_response([{"type": "text", "text": "hi"}]).usage_metadata is not None


# --- warm_up: bounded and once per process -----------------------------------------------------------------


def test_warm_up_that_hangs_is_abandoned_after_the_timeout_with_a_logged_error(monkeypatch, caplog):
    release = threading.Event()

    async def hang(spec, hooks, session_user):
        await asyncio.to_thread(release.wait, 10)

    monkeypatch.setattr(adk_agent, "_warmed", False)
    monkeypatch.setattr(adk_agent, "run_agent", hang)
    try:
        with caplog.at_level("ERROR", logger="app.runtime.adk_agent"):
            adk_agent.warm_up(timeout=0.2)  # returns instead of blocking the worker forever
        assert any("warm-up" in r.getMessage() and r.levelname == "ERROR" for r in caplog.records)
    finally:
        release.set()


def test_warm_up_runs_at_most_once_per_process(monkeypatch):
    calls: list[str] = []

    async def count(spec, hooks, session_user):
        calls.append(session_user)

    monkeypatch.setattr(adk_agent, "_warmed", False)
    monkeypatch.setattr(adk_agent, "run_agent", count)
    adk_agent.warm_up()
    adk_agent.warm_up()  # a supervisor retry rebuilding the worker does not rerun it
    assert calls == ["warm_up"]
