"""Runtime core: CEL, providers, drivers, gateway, decisions, memory, receipts, projection, agent helpers."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from psycopg.types.json import Jsonb

from app import settings
from app.defs.digest import canonical, digest
from app.defs.loader import load_bundle
from app.models.runs import Run
from app.runtime import agent, cel, decisions, drivers, gateway, memory, projection, providers, receipt
from app.runtime.providers import FakeProvider, ModelTurn, ToolSpec

PACK = "order-payment-reconciliation"
SANDBOX = settings.defs_dir() / "connectors" / "sandbox"
STATE_INPUT = {"since": "2026-10-06", "until": "2026-10-12"}


# --- shared fixtures -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def snapshot() -> dict:
    bundle = load_bundle(settings.defs_dir())
    defs: dict = {}
    versions = []
    for (kind, key), d in sorted(bundle.items.items()):
        if kind in ("pack", "workflow", "contract") and key != PACK:
            continue  # a run snapshot pins exactly one pack: the reconciliation pack
        defs.setdefault(kind, {})[key] = {"body": d.body, "files": d.files}
        versions.append({"kind": kind, "key": key, "version": 1, "digest": digest(d)})
    return {"org_id": "org_demo", "versions": versions, "defs": defs, "overrides": {}, "disabled": []}


def _sandbox(connector: str, tool: str) -> dict:
    return json.loads((SANDBOX / connector / f"{tool}.json").read_text(encoding="utf-8"))


def _schema(snapshot: dict, name: str) -> dict:
    return snapshot["defs"]["schema"][f"{PACK}/{name}"]["body"]


def _assert_valid(schema: dict, value) -> None:
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(value)]
    assert errors == []


def _state(**nodes) -> dict:
    return {"input": STATE_INPUT, "nodes": {k: {"output": v} for k, v in nodes.items()}, "memory": []}


def _fake_turn(snapshot: dict, agent_id: str, inputs: dict, task: str = "Do the work.") -> ModelTurn:
    system = agent.build_system(snapshot["defs"]["agent"][agent_id])
    messages = [{"role": "user", "content": agent.build_user_message(task, inputs)}]
    return FakeProvider().call(
        model="fake-reasoning", system=system, messages=messages, tools=[], max_tokens=4000
    )


def _match_result(snapshot: dict) -> dict:
    inputs = {
        "orders": _sandbox("shopify", "list_orders"),
        "charges": _sandbox("stripe", "list_charges"),
        "rules": [],
    }
    kind, result = agent.next_step(_fake_turn(snapshot, "finance-agent", inputs))
    assert kind == "submit"
    return result


# --- CEL -------------------------------------------------------------------------------------------


def test_cel_resolve_maps_nested_args_and_keeps_literals():
    args = {
        "created": {"gte": '=int(timestamp(input.since + "T00:00:00Z"))', "lte": "=1 + 1"},
        "limit": 100,
        "status": "any",
        "rows": ["=input.until", "plain", {"deep": "=input.since"}],
    }
    out = cel.resolve(args, _state())
    assert out == {
        "created": {"gte": 1791244800, "lte": 2},
        "limit": 100,
        "status": "any",
        "rows": ["2026-10-12", "plain", {"deep": "2026-10-06"}],
    }
    assert type(out["created"]["gte"]) is int
    assert args["created"]["lte"] == "=1 + 1"  # input untouched


def test_cel_evaluate_returns_plain_json_types():
    state = _state(match={"mismatches": [{"order_id": "#1"}], "ratio": 1.5})
    assert cel.evaluate("=size(nodes.match.output.mismatches) == 1", state) is True
    assert cel.evaluate("size(nodes.match.output.mismatches)", state) == 1
    value = cel.evaluate("nodes.match.output", state)
    assert value == {"mismatches": [{"order_id": "#1"}], "ratio": 1.5}
    assert type(value) is dict and type(value["mismatches"]) is list and type(value["ratio"]) is float
    assert cel.evaluate("has(nodes.review) ? nodes.review.output : null", state) is None
    assert cel.evaluate('timestamp("2026-10-06T00:00:00Z")', state) == "2026-10-06T00:00:00Z"


@pytest.mark.parametrize(
    ("minor", "text"),
    [
        (0, "0.00"),
        (5, "0.05"),
        (99999, "999.99"),
        (100000, "1,000.00"),
        (5618280, "56,182.80"),
        (123456789, "1,234,567.89"),
        (-150005, "-1,500.05"),
        (4025280.0, "40,252.80"),
    ],
)
def test_cel_format_minor_groups_thousands_with_two_decimals(minor, text):
    state = _state(match={"amount_minor": minor})
    assert cel.evaluate("formatMinor(nodes.match.output.amount_minor)", state) == text
    assert cel.evaluate("'₱' + nodes.match.output.amount_minor.formatMinor()", state) == "₱" + text


@pytest.mark.parametrize("value", ['"12"', "12.5", "true"])
def test_cel_format_minor_refuses_what_is_not_a_whole_number(value):
    with pytest.raises(cel.CelError):
        cel.evaluate(f"formatMinor({value})", _state())


def test_cel_evaluate_error_raises():
    with pytest.raises(cel.CelError):
        cel.evaluate("nodes.nope.output", _state())


# --- drivers ---------------------------------------------------------------------------------------


def test_sandbox_driver_returns_file_content_marked_mocked(snapshot):
    shopify = snapshot["defs"]["connector"]["shopify"]["body"]["tools"][0]
    stripe = snapshot["defs"]["connector"]["stripe"]["body"]["tools"][0]
    sheets = snapshot["defs"]["connector"]["googlesheets"]["body"]["tools"][0]
    driver = drivers.SandboxDriver()
    orders = driver.execute("shopify", shopify, {})
    assert orders.ok and orders.mocked and orders.error is None
    assert len(orders.data["orders"]) == 12
    assert len(driver.execute("stripe", stripe, {}).data["data"]) == 11
    assert driver.execute("googlesheets", sheets, {"values": [[1]]}).data["updates"]["updatedRows"] == 12


def test_sandbox_driver_missing_file_is_an_error():
    result = drivers.SandboxDriver().execute("shopify", {"id": "no_such_tool"}, {})
    assert result.ok is False and result.mocked is True and "no_such_tool" in result.error


class _StubComposio:
    def __init__(self, response=None, accounts=()):
        self.calls: list = []
        self.listed: list = []
        self._response = response
        self._accounts = list(accounts)
        self.tools = SimpleNamespace(execute=self._execute)
        self.connected_accounts = SimpleNamespace(list=self._list)

    def _execute(self, slug, arguments, **kwargs):
        self.calls.append((slug, arguments, kwargs))
        return self._response

    def _list(self, **kwargs):
        self.listed.append(kwargs)
        return SimpleNamespace(items=self._accounts)


def test_composio_driver_unwraps_envelope_and_uses_demo_user(monkeypatch):
    monkeypatch.setenv("DEMO_USER_UID", "uid_demo")
    stub = _StubComposio({"data": {"updates": {"updatedRows": 3}}, "successful": True, "error": None})
    driver = drivers.ComposioDriver(client=stub)
    tool = {"id": "append_rows", "slug": "GOOGLESHEETS_SPREADSHEETS_VALUES_APPEND"}
    result = driver.execute("googlesheets", tool, {"values": [[1]]})
    assert result == drivers.ToolResult(ok=True, data={"updates": {"updatedRows": 3}}, mocked=False)
    slug, arguments, kwargs = stub.calls[0]
    assert slug == "GOOGLESHEETS_SPREADSHEETS_VALUES_APPEND" and arguments == {"values": [[1]]}
    assert kwargs["user_id"] == "uid_demo"


def test_composio_driver_reports_failure_and_refuses_meta_tools(monkeypatch):
    monkeypatch.setenv("DEMO_USER_UID", "uid_demo")
    stub = _StubComposio({"data": {}, "successful": False, "error": "rate limited"})
    driver = drivers.ComposioDriver(client=stub)
    failed = driver.execute("shopify", {"id": "list_orders", "slug": "SHOPIFY_GET_ORDERS_WITH_FILTERS"}, {})
    assert failed.ok is False and failed.error == "ToolError: rate limited" and failed.mocked is False
    meta = driver.execute("x", {"id": "run", "slug": "COMPOSIO_MULTI_EXECUTE_TOOL"}, {})
    assert meta.ok is False and len(stub.calls) == 1


def test_composio_driver_errors_are_generic(monkeypatch):
    monkeypatch.setenv("DEMO_USER_UID", "uid_demo")
    noisy = "Bad request https://backend.composio.dev/api/v3/tools/execute?key=abc " + "x" * 400
    stub = _StubComposio({"data": {}, "successful": False, "error": noisy})
    tool = {"id": "list_orders", "slug": "SHOPIFY_GET_ORDERS_WITH_FILTERS"}
    error = drivers.ComposioDriver(client=stub).execute("shopify", tool, {}).error
    assert error.startswith("ToolError: Bad request") and "http" not in error and "key=abc" not in error
    assert len(error) <= 140

    class Boom(Exception):
        pass

    def explode(*args, **kwargs):
        raise Boom("POST https://backend.composio.dev/x failed with body {'api_key': 'secret'}")

    stub.tools = SimpleNamespace(execute=explode)
    error = drivers.ComposioDriver(client=stub).execute("shopify", tool, {}).error
    assert error == "Boom: the shopify call failed"


def test_composio_is_connected_checks_active_accounts_for_the_demo_user(monkeypatch):
    monkeypatch.setenv("DEMO_USER_UID", "uid_demo")
    stub = _StubComposio(accounts=[SimpleNamespace(id="ca_1")])
    assert drivers.ComposioDriver(client=stub).is_connected("shopify") is True
    assert stub.listed[0]["user_ids"] == ["uid_demo"]
    assert stub.listed[0]["toolkit_slugs"] == ["shopify"]
    assert stub.listed[0]["statuses"] == ["ACTIVE"]
    assert drivers.ComposioDriver(client=_StubComposio(accounts=[])).is_connected("shopify") is False


def test_driver_for_modes(monkeypatch):
    connector = {"toolkit": "shopify", "tools": []}
    assert isinstance(drivers.driver_for(connector, "sandbox"), drivers.SandboxDriver)

    connected = {"value": False}

    class FakeComposio(drivers.ComposioDriver):
        def __init__(self):
            super().__init__(client=_StubComposio())

        def is_connected(self, toolkit: str) -> bool:
            return connected["value"]

    monkeypatch.setattr(drivers, "ComposioDriver", FakeComposio)
    assert isinstance(drivers.driver_for(connector, "live"), FakeComposio)
    assert isinstance(drivers.driver_for(connector, "auto"), drivers.SandboxDriver)
    connected["value"] = True
    assert isinstance(drivers.driver_for(connector, "auto"), FakeComposio)


# --- gateway ---------------------------------------------------------------------------------------

CONTRACT = {
    "authorization": {"tool_capabilities": ["orders.read", "sheets.write"], "policy_ref": "policy/default"}
}
DEFAULTS = {"read": "permit", "write": "require_approval", "delete": "deny", "money": "deny"}


def _tool(action_class: str, capability: str) -> dict:
    return {"id": "t", "action_class": action_class, "capability": capability, "defaults": DEFAULTS}


@pytest.mark.parametrize(
    ("tool", "disabled", "approved", "verdict", "code"),
    [
        (_tool("read", "orders.read"), {"shop"}, False, "DENY", "CONNECTOR_DISABLED"),
        (_tool("read", "orders.write"), set(), False, "DENY", "CAPABILITY_NOT_IN_CONTRACT"),
        (_tool("delete", "orders.read"), set(), True, "DENY", "ACTION_CLASS_DENIED"),
        (_tool("write", "sheets.write"), set(), False, "REQUIRE_APPROVAL", "APPROVAL_REQUIRED"),
        (_tool("write", "sheets.write"), set(), True, "PERMIT", "APPROVAL_GRANTED"),
        (_tool("read", "orders.read"), set(), False, "PERMIT", "ACTION_CLASS_PERMITTED"),
    ],
)
def test_gateway_policy_matrix(tool, disabled, approved, verdict, code):
    decision = gateway.decide(
        tool=tool, connector_key="shop", contract=CONTRACT, overrides={}, disabled=disabled, approved=approved
    )
    assert decision.verdict == verdict
    assert decision.reason_codes == [code]
    assert decision.ref == "policy/default"


def test_gateway_ops_override_wins_over_connector_default():
    decision = gateway.decide(
        tool=_tool("read", "orders.read"),
        connector_key="shop",
        contract=CONTRACT,
        overrides={"shop": {"read": "deny"}},
        disabled=set(),
        approved=False,
    )
    assert (decision.verdict, decision.reason_codes) == ("DENY", ["ACTION_CLASS_DENIED"])


def test_call_tool_read_runs_through_sandbox(snapshot):
    args = {"created_at_min": "2026-10-06T00:00:00Z", "status": "any", "limit": 250}
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref="shopify.list_orders", args=args, approved=False, mode="sandbox"
    )
    assert decision.verdict == "PERMIT"
    assert result.ok and result.mocked and len(result.data["orders"]) == 12


def test_call_tool_write_needs_approval(snapshot):
    sheet = "sandbox-reconciliation-sheet-00000001"
    args = {"spreadsheetId": sheet, "range": "R!A:F", "valueInputOption": "RAW", "values": [["a"]]}
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref="googlesheets.append_rows", args=args, approved=False, mode="sandbox"
    )
    assert (decision.verdict, decision.reason_codes, result) == (
        "REQUIRE_APPROVAL",
        ["APPROVAL_REQUIRED"],
        None,
    )
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref="googlesheets.append_rows", args=args, approved=True, mode="sandbox"
    )
    assert decision.verdict == "PERMIT" and result.ok and result.mocked
    assert result.data["updates"]["updatedRows"] == 12


def test_call_tool_disabled_connector_and_unknown_tool_are_denied(snapshot):
    snap = {**snapshot, "disabled": ["shopify"]}
    decision, result = gateway.call_tool(
        snapshot=snap, tool_ref="shopify.list_orders", args={}, approved=False, mode="sandbox"
    )
    assert (decision.verdict, decision.reason_codes, result) == ("DENY", ["CONNECTOR_DISABLED"], None)
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref="shopify.delete_everything", args={}, approved=True, mode="sandbox"
    )
    assert (decision.verdict, decision.reason_codes, result) == ("DENY", ["UNKNOWN_TOOL"], None)


def test_call_tool_rejects_arguments_outside_the_tool_schema(snapshot):
    decision, result = gateway.call_tool(
        snapshot=snapshot,
        tool_ref="shopify.list_orders",
        args={"limit": 9999},
        approved=False,
        mode="sandbox",
    )
    assert decision.verdict == "PERMIT"
    assert result.ok is False and "invalid arguments" in result.error


# --- decisions -------------------------------------------------------------------------------------


def test_decisions_three_states(snapshot):
    rules = snapshot["defs"]["decision_rules"]["recon-exceptions"]["body"]
    orders, charges = _sandbox("shopify", "list_orders"), _sandbox("stripe", "list_charges")

    blocked = decisions.evaluate_rules(rules, _state(orders={"orders": []}, payments=charges, match={}))
    assert (blocked.verdict, blocked.route, blocked.reason_code, blocked.matched_rule) == (
        "BLOCKED",
        "blocked",
        "DATA_MISSING",
        0,
    )
    clean = decisions.evaluate_rules(rules, _state(orders=orders, payments=charges, match={"mismatches": []}))
    assert (clean.verdict, clean.route, clean.reason_code, clean.matched_rule) == (
        "APPROVED",
        "approved",
        "ALL_MATCHED",
        1,
    )
    review = decisions.evaluate_rules(
        rules, _state(orders=orders, payments=charges, match={"mismatches": [{}, {}]})
    )
    assert (review.verdict, review.route, review.reason_code, review.matched_rule) == (
        "HUMAN_REVIEW",
        "human_review",
        "MISMATCHES_FOUND",
        None,
    )
    assert review.explanation.startswith("Some orders")


# --- providers -------------------------------------------------------------------------------------


def test_fake_finance_agent_submits_a_valid_match_with_two_mismatches(snapshot):
    result = _match_result(snapshot)
    _assert_valid(_schema(snapshot, "match"), result)
    by_order = {m["order_id"]: m for m in result["mismatches"]}
    assert set(by_order) == {"#1004", "#1007"}
    assert (by_order["#1007"]["kind"], by_order["#1007"]["amount_diff_minor"]) == ("missing_payment", -6750)
    assert by_order["#1007"]["charge_id"] is None
    assert (by_order["#1004"]["kind"], by_order["#1004"]["amount_diff_minor"]) == ("amount_mismatch", -290)
    assert by_order["#1004"]["charge_id"] == "ch_3Sandbox1004"
    assert result["totals"]["orders_count"] == 12 and result["totals"]["charges_count"] == 11
    assert result["totals"]["matched_count"] == 10 and result["totals"]["mismatch_count"] == 2
    assert {m["order_id"] for m in result["matched"]} >= {"#1009"}  # paired by amount and date


def test_fake_ops_agent_writes_report_rows_per_skill(snapshot):
    match = _match_result(snapshot)
    review = {
        "outcome": "resolved",
        "note": "Checked both",
        "resolutions": [{"order_id": "#1004", "resolution": "explained", "note": "Processor fee, agreed."}],
    }
    turn = _fake_turn(snapshot, "ops-agent", {"match": match, "review": review})
    kind, report = agent.next_step(turn)
    assert kind == "submit"
    _assert_valid(_schema(snapshot, "report"), report)
    _assert_valid(_schema(snapshot, "output"), report)
    assert len(report["rows"]) == 12
    assert report["rows"][0] == ["2026-10-06", "#1001", "matched", "45.00", "matched", ""]
    mismatch_rows = {row[1]: row for row in report["rows"][10:]}
    assert mismatch_rows["#1004"] == [
        "2026-10-07",
        "#1004",
        "amount_mismatch",
        "89.66",
        "resolved",
        "Processor fee, agreed.",
    ]
    assert mismatch_rows["#1007"][4] == "unreviewed"
    assert report["totals"]["net_difference_minor"] == -7040
    assert "#1007" in report["summary"]
    assert (turn.input_tokens, turn.output_tokens) == (1200, 300)


def test_fake_provider_follows_script_by_turn():
    text = ModelTurn(
        content=[{"type": "text", "text": "thinking"}],
        stop_reason="end_turn",
        input_tokens=10,
        output_tokens=5,
        model="fake",
    )
    submit = ModelTurn(
        content=[{"type": "tool_use", "id": "t1", "name": "submit_result", "input": {"ok": True}}],
        stop_reason="tool_use",
        input_tokens=10,
        output_tokens=5,
        model="fake",
    )
    fake = FakeProvider({"x-agent": [text, submit]})
    system = "agent:x-agent\n\nDo things."
    messages = [{"role": "user", "content": "go"}]
    first = fake.call(model="m", system=system, messages=messages, tools=[], max_tokens=100)
    assert agent.next_step(first) == ("text", "thinking")
    messages += [{"role": "assistant", "content": first.content}, {"role": "user", "content": agent.REPROMPT}]
    second = fake.call(model="m", system=system, messages=messages, tools=[], max_tokens=100)
    assert agent.next_step(second) == ("submit", {"ok": True})
    with pytest.raises(LookupError):
        fake.call(model="m", system="agent:unknown\n\nx", messages=messages, tools=[], max_tokens=100)


def test_cost_minor_rounds_up(snapshot):
    models = snapshot["defs"]["models"]["default"]["body"]
    assert providers.cost_minor(models, "reasoning", 1200, 300) == 1  # 0.15 + 0.3 cents
    assert providers.cost_minor(models, "fast", 1_000_000, 0) == 30
    assert providers.cost_minor(models, "fast", 1, 0) == 1
    assert providers.cost_minor(models, "fast", 0, 0) == 0


def test_provider_for_picks_by_env(snapshot, monkeypatch):
    models = snapshot["defs"]["models"]["default"]["body"]
    provider, model = providers.provider_for("reasoning", models, "test")
    assert isinstance(provider, FakeProvider) and model == "fake-reasoning"
    provider, model = providers.provider_for("reasoning", models, "prod")
    assert isinstance(provider, providers.VertexProvider) and model == "gemini-2.5-pro"
    with pytest.raises(ValueError):
        providers.provider_for("nope", models, "test")


def _gemini_response(parts, finish="STOP", prompt=321, output=45, thoughts=None):
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=parts), finish_reason=SimpleNamespace(name=finish))
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=output, thoughts_token_count=thoughts
        ),
        model_version="gemini-2.5-flash",
    )


def _gemini_part(text=None, call=None, thought=None):
    return SimpleNamespace(text=text, function_call=call, thought=thought)


def _stub_client(response):
    sent: dict = {}

    def generate_content(**kwargs):
        sent.update(kwargs)
        return response

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)), sent


def test_vertex_provider_request_and_turn_shape_with_stubbed_client():
    call = SimpleNamespace(id="call_1", name="submit_result", args={"a": 1})
    response = _gemini_response(
        [
            _gemini_part(text="planning", thought=True),
            _gemini_part(text="Submitting."),
            _gemini_part(call=call),
        ],
        thoughts=30,
    )
    client, sent = _stub_client(response)
    spec = ToolSpec(name="submit_result", description="Submit.", input_schema={"type": "object"})
    turn = providers.VertexProvider(client=client).call(
        model="gemini-2.5-flash",
        system="agent:x\n\nhi",
        messages=[{"role": "user", "content": "go"}],
        tools=[spec],
        max_tokens=20000,
    )
    config = sent["config"]
    assert sent["model"] == "gemini-2.5-flash"
    assert config.system_instruction == "agent:x\n\nhi" and config.max_output_tokens == 16000
    assert config.automatic_function_calling.disable is True
    declaration = config.tools[0].function_declarations[0]
    assert (declaration.name, declaration.description) == ("submit_result", "Submit.")
    assert declaration.parameters_json_schema == {"type": "object"}
    assert [(c.role, c.parts[0].text) for c in sent["contents"]] == [("user", "go")]
    assert turn == ModelTurn(
        content=[
            {"type": "text", "text": "Submitting."},
            {"type": "tool_use", "id": "call_1", "name": "submit_result", "input": {"a": 1}},
        ],
        stop_reason="tool_use",
        input_tokens=321,
        output_tokens=75,  # thinking tokens are billed as output
        model="gemini-2.5-flash",
    )


def test_vertex_provider_maps_tool_results_and_stop_reasons():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking."},
                {"type": "tool_use", "id": "call_1", "name": "shopify_list_orders", "input": {"limit": 2}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "[]", "is_error": False},
                {
                    "type": "tool_result",
                    "tool_use_id": "call_9",
                    "content": "Not permitted",
                    "is_error": True,
                },
            ],
        },
    ]
    contents = providers.to_contents(messages)
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1].parts[1].function_call.name == "shopify_list_orders"
    ok, denied = (p.function_response for p in contents[2].parts)
    assert (ok.id, ok.name, ok.response) == ("call_1", "shopify_list_orders", {"output": "[]"})
    assert (denied.name, denied.response) == ("tool", {"error": "Not permitted"})

    cut = SimpleNamespace(id=None, name="submit_result", args={"a": 1})
    client, _ = _stub_client(_gemini_response([_gemini_part(call=cut)], finish="MAX_TOKENS"))
    turn = providers.VertexProvider(client=client).call(
        model="m", system="", messages=messages, tools=[], max_tokens=100
    )
    assert turn.stop_reason == "max_tokens" and turn.content[0]["id"].startswith("call_")
    client, sent = _stub_client(_gemini_response([_gemini_part(text="done")]))
    turn = providers.VertexProvider(client=client).call(
        model="m", system="", messages=messages, tools=[], max_tokens=100
    )
    assert (
        turn.stop_reason == "end_turn"
        and sent["config"].tools is None
        and sent["config"].system_instruction is None
    )


# --- agent helpers ---------------------------------------------------------------------------------


def test_build_system_and_user_message(snapshot):
    system = agent.build_system(snapshot["defs"]["agent"]["finance-agent"])
    assert system.startswith("agent:finance-agent\n\nYou are the finance agent")
    assert (
        "\n\n# Skills\n" in system and "name: match-orders" in system and "name: explain-mismatch" in system
    )
    message = agent.build_user_message("Match them.", {"orders": [1]})
    assert message.startswith("Match them.") and '"orders"' in message


def test_agent_tools_intersects_contract_and_adds_submit_result(snapshot):
    snap = copy.deepcopy(snapshot)
    snap["defs"]["contract"][PACK]["body"]["authorization"]["tool_capabilities"] = ["orders.read"]
    body = {"runtime": {"tools": ["shopify.list_orders", "googlesheets.append_rows", "nope.tool"]}}
    output_schema = _schema(snapshot, "match")
    tools = agent.agent_tools(body, snap, output_schema)
    assert [t.name for t in tools] == ["shopify__list_orders", "submit_result"]
    assert tools[0].input_schema["properties"]["limit"]["maximum"] == 250
    assert tools[1].input_schema["required"] == ["matched", "mismatches", "totals"]
    assert "$schema" not in tools[1].input_schema
    assert agent.tool_ref("shopify__list_orders") == "shopify.list_orders"


def test_next_step_variants():
    def turn(*blocks):
        return ModelTurn(
            content=list(blocks), stop_reason="end_turn", input_tokens=1, output_tokens=1, model="m"
        )

    use = {"type": "tool_use", "id": "a", "name": "shopify__list_orders", "input": {}}
    assert agent.next_step(turn(use)) == ("tools", [use])
    assert agent.next_step(turn({"type": "text", "text": "a"}, {"type": "text", "text": "b"})) == (
        "text",
        "a\nb",
    )
    submit = {"type": "tool_use", "id": "b", "name": "submit_result", "input": {"x": 1}}
    assert agent.next_step(turn(use, submit)) == ("submit", {"x": 1})


def test_a_turn_cut_off_at_the_output_limit_runs_none_of_its_tool_calls():
    use = {"type": "tool_use", "id": "a", "name": "shopify__list_orders", "input": {}}
    submit = {"type": "tool_use", "id": "b", "name": "submit_result", "input": {"summary": "Checked 33."}}
    cut = ModelTurn(
        content=[use, submit], stop_reason="max_tokens", input_tokens=1, output_tokens=1, model="m"
    )
    assert agent.next_step(cut) == ("truncated", [use, submit])
    results = agent.cut_off_results([use, submit])
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert all(r["type"] == "tool_result" and r["is_error"] for r in results)
    assert "cut off at the output limit" in results[0]["content"]
    text = ModelTurn(
        content=[{"type": "text", "text": "a"}],
        stop_reason="max_tokens",
        input_tokens=1,
        output_tokens=1,
        model="m",
    )
    assert agent.next_step(text) == ("text", "a")  # no call to hold back: re-prompted as before


# --- receipts (Postgres) ---------------------------------------------------------------------------


def _insert_run(conn, run_id: str) -> None:
    conn.execute(
        "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input) "
        "VALUES (%s, 'org_demo', %s, 'RUNNING', %s, %s, %s)",
        (run_id, PACK, Jsonb({}), Jsonb({}), Jsonb({})),
    )
    conn.commit()


def test_entry_hash_is_sha256_of_prev_and_canonical_entry():
    entry = {
        "seq": 1,
        "at": "2026-10-13T00:00:00.000000Z",
        "type": "run.started",
        "node_id": None,
        "data": {},
    }
    expected = "sha256:" + hashlib.sha256(receipt.GENESIS.encode() + canonical(entry)).hexdigest()
    assert receipt.entry_hash(receipt.GENESIS, entry) == expected


def test_receipt_chain_appends_verifies_and_detects_tampering(db):
    _insert_run(db, "run_1")
    first = receipt.append(db, "run_1", "k1", "run.started", None, {"input": STATE_INPUT})
    second = receipt.append(db, "run_1", "k2", "node.completed", "orders", {"count": 12, "ratio": 0.5})
    third = receipt.append(db, "run_1", "k3", "run.completed", "done", {})
    db.commit()
    assert [first["seq"], second["seq"], third["seq"]] == [1, 2, 3]
    assert first["prev_hash"] == receipt.GENESIS
    assert second["prev_hash"] == first["hash"] and third["prev_hash"] == second["hash"]
    assert receipt.verify(db, "run_1") == (True, 3, third["hash"])

    db.execute(
        "UPDATE receipt_entries SET data = %s WHERE run_id = 'run_1' AND seq = 2", (Jsonb({"count": 13}),)
    )
    db.commit()
    ok, count, _ = receipt.verify(db, "run_1")
    assert (ok, count) == (False, 3)


def test_receipt_duplicate_event_key_is_a_noop(db):
    _insert_run(db, "run_2")
    assert receipt.append(db, "run_2", "k1", "run.started", None, {}) is not None
    assert receipt.append(db, "run_2", "k1", "run.started", None, {"other": 1}) is None
    db.commit()
    assert receipt.verify(db, "run_2")[:2] == (True, 1)


def test_receipt_verify_of_an_empty_run_is_genesis(db):
    _insert_run(db, "run_3")
    assert receipt.verify(db, "run_3") == (True, 0, receipt.GENESIS)


# --- memory (Postgres) -----------------------------------------------------------------------------


def test_memory_recall_ranks_matches_and_falls_back_to_newest(db, snapshot):
    seeds = snapshot["defs"]["memory_space"]["retail-commerce"]["body"]["seed_items"]
    for text in seeds:
        memory.remember(db, "retail-commerce", text, "seed", "ops-agent")
    memory.remember(db, "other-space", "Fees are fun", "seed", "ops-agent")
    db.commit()

    hits = memory.recall(db, "retail-commerce", "fee")
    assert hits and "fees" in hits[0]["text"].lower()
    assert all(h["space"] == "retail-commerce" for h in hits)

    fallback = memory.recall(db, "retail-commerce", "zebra crossing", limit=2)
    assert [h["text"] for h in fallback] == [seeds[-1], seeds[-2]]
    json.dumps(fallback)  # JSON-safe for workflow state


def test_memory_recall_ors_the_query_terms(db, snapshot):
    seeds = snapshot["defs"]["memory_space"]["retail-commerce"]["body"]["seed_items"]
    for text in seeds:
        memory.remember(db, "retail-commerce", text, "seed", "ops-agent")
    db.commit()
    # The reconciliation workflow's own query: no single item holds every word; each hit holds one.
    hits = {h["text"] for h in memory.recall(db, "retail-commerce", "reconciliation fees tolerance refunds")}
    assert {seeds[0], seeds[2]} <= hits
    assert all("fee" in t.lower() or "refund" in t.lower() for t in hits)
    assert not any("refund policy" in t.lower() or "reminder" in t.lower() for t in seeds)  # no policy noise
    # Query syntax characters are words to search for, never tsquery operators.
    assert memory.recall(db, "retail-commerce", "fees & !refunds | (")
    assert len(memory.recall(db, "retail-commerce", "the and of", limit=3)) == 3  # stop words only


def test_the_seed_packs_recall_their_own_policies_from_customer_accounts(db, snapshot):
    seeds = snapshot["defs"]["memory_space"]["customer-accounts"]["body"]["seed_items"]
    for text in seeds:
        memory.remember(db, "customer-accounts", text, "seed", "ops-agent")
    db.commit()
    reminders = {t for t in seeds if "refund" not in t.lower()}
    assert len(reminders) == 2 and len(seeds) == 6
    # Each pack's own recall query (its workflow's recall node) finds its policy items and nothing else.
    collections = memory.recall(db, "customer-accounts", "collections reminders tone overdue")
    assert {h["text"] for h in collections} == reminders
    refunds = memory.recall(db, "customer-accounts", "refund policy approved partial declined")
    assert {h["text"] for h in refunds} == set(seeds) - reminders


def test_memory_list_and_delete(db):
    item = memory.remember(db, "retail-commerce", "Ship within two days.", "console", "ops@nm")
    db.commit()
    assert item["id"].startswith("mem_") and item["created_by"] == "ops@nm" and item["source"] == "console"
    assert [i["id"] for i in memory.list_items(db, "retail-commerce")] == [item["id"]]
    assert memory.delete_item(db, item["id"]) is True
    assert memory.delete_item(db, item["id"]) is False
    db.commit()
    assert memory.list_items(db, "retail-commerce") == []


# --- projection ------------------------------------------------------------------------------------


def _event(type_: str, node_id: str | None, data: dict, seq: int = 1) -> dict:
    return {
        "seq": seq,
        "at": f"2026-10-13T10:00:{seq:02d}.000000Z",
        "type": type_,
        "node_id": node_id,
        "data": data,
    }


def _initial(snapshot) -> dict:
    return projection.initial_projection("run_9", snapshot, STATE_INPUT, "You", 2500)


def test_initial_projection_lays_out_every_node(snapshot):
    p = _initial(snapshot)
    run = Run.model_validate(p)
    workflow = snapshot["defs"]["workflow"][PACK]["body"]
    ids = [n["id"] for n in workflow["nodes"]]
    assert [n.id for n in run.nodes] == ids
    assert all(n.status == "CREATED" for n in run.nodes)
    assert [n.x for n in run.nodes] == [210 * i for i in range(len(ids))]
    by_id = {n.id: n for n in run.nodes}
    assert by_id["failed"].y == 140 and by_id["done"].y == 0
    assert by_id["review"].actor == "human" and by_id["approve_write"].actor == "buyer"
    assert by_id["match"].actor == "machine"
    route_count = sum(len(n.get("routes") or {}) for n in workflow["nodes"])
    assert len(run.edges) == route_count
    assert any(e.from_ == "check" and e.to == "review" and e.label == "human_review" for e in run.edges)
    assert run.status == "RUNNING" and run.budget.amount_minor == 2500 and run.pack_slug == PACK
    assert run.stages.executed == "pending" and run.spent.ai.amount_minor == 0


def test_apply_event_decision_and_tool_call(snapshot):
    p0 = _initial(snapshot)
    events = [
        _event("node.started", "check", {}, 1),
        _event(
            "decision",
            "check",
            {
                "question": "Do the orders and payments match?",
                "verdict": "HUMAN_REVIEW",
                "route": "human_review",
                "reason_code": "MISMATCHES_FOUND",
                "explanation": "Some do not match.",
                "matched_rule": None,
                "rules_ref": "recon-exceptions@1",
                "policy": {
                    "id": "poldec_1",
                    "ref": "recon-exceptions@v1",
                    "verdict": "REQUIRE_APPROVAL",
                    "reason_codes": ["MISMATCHES_FOUND"],
                    "actor": "rules",
                },
            },
            2,
        ),
        _event("node.completed", "check", {"route": "human_review", "summary": "2 mismatches to review"}, 3),
        _event("node.started", "write", {}, 4),
        _event(
            "tool.call",
            "write",
            {
                "tool_ref": "googlesheets.append_rows",
                "app": "Google Sheets",
                "action": "Append rows",
                "capability": "sheets.write",
                "policy": {
                    "verdict": "PERMIT",
                    "reason_codes": ["APPROVAL_GRANTED"],
                    "ref": "policy/default",
                },
                "ok": True,
                "mocked": True,
                "detail": "12 rows appended.",
            },
            5,
        ),
        _event("model.usage", "match", {"input_tokens": 1200, "output_tokens": 300, "cost_minor": 2}, 6),
    ]
    before = copy.deepcopy(p0)
    p = p0
    for e in events:
        p = projection.apply_event(p, e)
    assert p0 == before  # apply_event is pure
    run = Run.model_validate(p)
    nodes = {n.id: n for n in run.nodes}
    assert nodes["check"].status == "COMPLETED"
    assert nodes["check"].decision.verdict == "HUMAN_REVIEW"
    assert nodes["check"].decision.reason_codes == ["MISMATCHES_FOUND"]
    assert nodes["check"].decision.evaluator.kind == "rules"
    stored = p["nodes"][[n["id"] for n in p["nodes"]].index("check")]["decision"]["policy"]
    assert stored["reasonCodes"] == ["MISMATCHES_FOUND"] and "reason_codes" not in stored  # wire form
    assert nodes["check"].decision.policy.verdict == "REQUIRE_APPROVAL"
    assert nodes["check"].output == "2 mismatches to review"
    call = nodes["write"].tool_calls[0]
    assert (call.status, call.policy, call.mocked, call.capability) == (
        "CONFIRMED",
        "PERMIT",
        True,
        "sheets.write",
    )
    assert nodes["write"].status == "RUNNING"
    assert next(e for e in run.edges if e.from_ == "check" and e.to == "review").taken is True
    assert run.spent.ai.amount_minor == 2 and nodes["match"].cost.amount_minor == 2
    assert any(t.node_id == "check" for t in run.timeline)


def test_apply_event_human_task_approval_and_completion(snapshot):
    report = {
        "summary": "Checked 12 orders.",
        "rows": [["2026-10-06", "#1001", "matched", "45.00", "matched", ""]],
        "totals": {
            "orders_count": 12,
            "matched_count": 10,
            "mismatch_count": 2,
            "net_difference_minor": -7040,
            "currency": "USD",
        },
    }
    p = _initial(snapshot)
    p = projection.apply_event(
        p,
        _event(
            "human.task", "review", {"task_id": "ht_1", "status": "open", "title": "Resolve mismatches"}, 1
        ),
    )
    run = Run.model_validate(p)
    assert run.status == "WAITING_FOR_HUMAN" and run.attention.tone == "human"
    assert {n.id: n for n in run.nodes}["review"].human_task_id == "ht_1"
    p = projection.apply_event(
        p,
        _event(
            "human.task",
            "review",
            {
                "task_id": "ht_1",
                "status": "resolved",
                "outcome": "resolved",
                "note": "ok",
                "decided_by": "Reviewer 7",
            },
            2,
        ),
    )
    assert Run.model_validate(p).attention is None
    p = projection.apply_event(
        p, _event("approval", "approve_write", {"approval_id": "apr_1", "status": "pending"}, 3)
    )
    run = Run.model_validate(p)
    assert (
        run.status == "WAITING_FOR_EVENT"
        and {n.id: n for n in run.nodes}["approve_write"].status == "WAITING"
    )
    p = projection.apply_event(
        p, _event("approval", "approve_write", {"approval_id": "apr_1", "status": "granted"}, 4)
    )
    assert Run.model_validate(p).status == "RUNNING"
    p = projection.apply_event(p, _event("node.completed", "verify", {"route": "pass"}, 5))
    p = projection.apply_event(p, _event("run.completed", "done", {"deliverable": report, "mocked": True}, 6))
    run = Run.model_validate(p)
    assert run.status == "COMPLETED" and run.ended_at == "2026-10-13T10:00:06.000000Z"
    assert run.deliverable.summary == "Checked 12 orders." and run.summary == "Checked 12 orders."
    assert run.stages.executed == "done" and run.stages.verified == "done"


def test_apply_event_failure(snapshot):
    p = projection.apply_event(_initial(snapshot), _event("node.failed", "check", {"error": "boom"}, 1))
    p = projection.apply_event(p, _event("run.failed", "failed", {"reason": "No orders for this period."}, 2))
    run = Run.model_validate(p)
    assert run.status == "FAILED" and run.attention.tone == "blocked" and run.ended_at
    assert {n.id: n for n in run.nodes}["check"].status == "FAILED"


def test_projection_save_updates_run_row(db, snapshot):
    _insert_run(db, "run_9")
    p = _initial(snapshot)
    projection.save(db, "run_9", p, "RUNNING")
    db.commit()
    row = db.execute("SELECT status, projection FROM runs WHERE id = 'run_9'").fetchone()
    assert row["status"] == "RUNNING" and row["projection"]["id"] == "run_9"


def test_model_http_timeout_is_shorter_than_the_model_activity_timeout(monkeypatch):
    from google import genai

    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(genai, "Client", fake_client)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "nm-test")
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    providers._shared_client.cache_clear()
    try:
        providers._shared_client()
    finally:
        providers._shared_client.cache_clear()
    assert captured["vertexai"] is True
    assert (captured["project"], captured["location"]) == ("nm-test", "global")
    http = captured["http_options"]
    assert http.timeout == providers.MODEL_CALL_TIMEOUT_S * 1000 < providers.MODEL_ACTIVITY_TIMEOUT_S * 1000
    assert http.retry_options is None  # retries belong to Temporal
