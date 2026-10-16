"""Hardening of the platform's MongoDB MCP driver: the mapping is read-only in code, placeholders cannot steer
the query, sessions obey one deadline and a size cap, receipts carry no server text, `auto` mode settles once
per run, and the logs carry neither the address nor the token. Real sessions run against an in-process server
on loopback; the driver tests use a stub client."""
# ruff: noqa: F811

import logging
import time
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import anyio
import pytest

from app import mcp_logging, settings
from app.catalog.packs import SandboxForecast
from app.defs import mcp_mapping, owners
from app.defs.loader import load_bundle
from app.defs.model import Bundle
from app.defs.validate import validate_bundle
from app.runtime import drivers, gateway, mcp
from tests.fake_mcp import TOKEN, FakeMcp, _server
from tests.test_defs_engine import FIXTURE, mutated, only_error
from tests.test_live_catalog import ana, live, starts  # noqa: F401
from tests.test_mcp_driver import MCP_CONNECTOR, NOTE_TOOL, ORDERS_TOOL, _result, _StubMcp
from tests.test_real_runs import api, rec  # noqa: F401

CONNECTOR = "shop"


# --- the mapping is read-only in code ---------------------------------------------------------------


def _read(tool="aggregate", **fields) -> dict:
    return {"tool": tool, "collection": "orders", "pipeline": [{"$match": {}}], **fields}


@pytest.mark.parametrize("tool", ["aggregate", "find", "count"])
def test_a_read_may_call_the_read_tools(tool):
    assert mcp_mapping.refusal("read", _read(tool), writes_enabled=False) is None


@pytest.mark.parametrize("tool", ["update-many", "insert-many", "delete-many", "drop-collection", "explain"])
def test_a_read_may_call_nothing_else(tool):
    assert "a read may call only" in mcp_mapping.refusal("read", _read(tool), writes_enabled=True)


@pytest.mark.parametrize("operator", sorted(mcp_mapping.BANNED_OPERATORS))
def test_no_mapping_may_hold_a_write_or_server_side_javascript_operator(operator):
    pipelines = [
        [{operator: "x"}],
        [{"$match": {"$expr": {"a": [{operator: 1}]}}}],
        [{"$facet": {"inner": [{"$project": {"v": {operator: {"body": "x"}}}}]}}],
    ]
    for pipeline in pipelines:
        refused = mcp_mapping.refusal("read", _read(pipeline=pipeline), writes_enabled=False)
        assert operator in refused


def test_a_write_is_refused_unless_writes_are_switched_on_and_then_needs_a_filter():
    write = {"tool": "update-many", "collection": "o", "update": {"$set": {"a": 1}}, "filter": {"_id": "x"}}
    assert "read-only" in mcp_mapping.refusal("write", write, writes_enabled=False)
    assert mcp_mapping.refusal("write", write, writes_enabled=True) is None
    assert "non-empty filter" in mcp_mapping.refusal("write", {**write, "filter": {}}, writes_enabled=True)
    assert "non-empty filter" in mcp_mapping.refusal(
        "write", {k: v for k, v in write.items() if k != "filter"}, writes_enabled=True
    )
    assert "only update-many" in mcp_mapping.refusal(
        "write", {**write, "tool": "aggregate"}, writes_enabled=True
    )
    assert mcp_mapping.refusal("delete", write, writes_enabled=False) is not None  # not a read: a write
    assert mcp_mapping.refusal(None, write, writes_enabled=False) is not None  # unknown class fails closed


def test_the_driver_repeats_the_check_for_a_pinned_snapshot_that_skipped_publishing():
    stub = _StubMcp(_result([{"id": 1}]))
    driver = drivers.PlatformMcpDriver(client=stub)
    forged_tool = {**ORDERS_TOOL, "mcp": {**ORDERS_TOOL["mcp"], "tool": "update-many"}}
    out = driver.execute("shop", forged_tool, {"since": "x"})
    assert out.ok is False and out.error == "ConfigError: the shop call is not allowed" and stub.calls == []
    merge = {"pipeline": [{"$match": {}}, {"$merge": {"into": "stolen"}}]}
    forged_op = {**ORDERS_TOOL, "mcp": {**ORDERS_TOOL["mcp"], **merge}}
    out = driver.execute("shop", forged_op, {"since": "x"})
    assert out.ok is False and "not allowed" in out.error and stub.calls == []
    js = {"pipeline": [{"$match": {"$where": "sleep(10000)"}}]}
    out = driver.execute("shop", {**ORDERS_TOOL, "mcp": {**ORDERS_TOOL["mcp"], **js}}, {"since": "x"})
    assert out.ok is False and stub.calls == []


def test_a_write_mapping_does_not_run_without_the_switch_and_does_with_it(monkeypatch):
    stub = _StubMcp(_result(structured={"matchedCount": 1, "modifiedCount": 1, "upsertedCount": 0}))
    args = {"order_id": "SO-1", "note": "x"}
    monkeypatch.delenv("NM_MCP_WRITES", raising=False)
    assert drivers.PlatformMcpDriver(client=stub).execute("shop", NOTE_TOOL, args).ok is False
    assert stub.calls == []
    monkeypatch.setenv("NM_MCP_WRITES", "1")
    assert drivers.PlatformMcpDriver(client=stub).execute("shop", NOTE_TOOL, args).ok is True


def test_a_write_filter_that_comes_out_empty_is_refused(monkeypatch):
    monkeypatch.setenv("NM_MCP_WRITES", "1")
    stub = _StubMcp(_result(structured={"matchedCount": 1}))
    tool = {**NOTE_TOOL, "mcp": {**NOTE_TOOL["mcp"], "filter": {}}}
    assert (
        drivers.PlatformMcpDriver(client=stub).execute("shop", tool, {"order_id": "a", "note": "b"}).ok
        is False
    )
    assert stub.calls == []


def test_a_write_with_no_structured_result_or_no_match_fails():
    spec = {"result": {"ok": True}}
    for structured in (None, {}, {"matchedCount": 0}, {"matchedCount": "1"}, {"matchedCount": True}):
        result = SimpleNamespace(isError=False, content=[], structuredContent=structured)
        with pytest.raises(mcp.ResultError):
            mcp.shape(spec, result, {})
    ok = SimpleNamespace(isError=False, content=[], structuredContent={"matchedCount": 2})
    assert mcp.shape(spec, ok, {}) == {"ok": True}


def test_the_server_check_fails_closed_when_it_lists_a_write_tool(monkeypatch):
    monkeypatch.delenv("NM_MCP_WRITES", raising=False)
    read_only = ("find", "aggregate", "count", "list-collections", "collection-schema")
    assert drivers.PlatformMcpDriver(client=_StubMcp(tools=read_only)).is_available() is True
    for write in (
        "update-many",
        "insert-many",
        "delete-many",
        "drop-collection",
        "create-index",
        "drop-database",
    ):
        assert drivers.PlatformMcpDriver(client=_StubMcp(tools=(*read_only, write))).is_available() is False
    monkeypatch.setenv("NM_MCP_WRITES", "1")
    assert (
        drivers.PlatformMcpDriver(client=_StubMcp(tools=(*read_only, "update-many"))).is_available() is True
    )


# --- placeholders cannot steer the query ------------------------------------------------------------


def test_a_placeholder_in_a_field_name_is_refused_when_rendering():
    with pytest.raises(mcp.PlaceholderError, match="field name"):
        mcp.render({"{{field}}": 1}, {"field": "$where"})
    with pytest.raises(mcp.PlaceholderError):
        mcp.render([{"a": {"x{{n}}": 1}}], {"n": 1})
    spec = {"tool": "find", "collection": "c", "filter": {"{{k}}": "v"}}
    with pytest.raises(mcp.PlaceholderError):
        mcp.arguments(spec, {"k": "a"}, "db")


@pytest.mark.parametrize(
    "bad",
    [{"$where": "1"}, {"a": 1}, "$ne", "$out", "$field.path", ["ok", "$bad"], [{"$gt": ""}]],
)
def test_an_argument_that_is_an_object_or_starts_with_dollar_is_refused(bad):
    with pytest.raises(mcp.PlaceholderError):
        mcp.call_values(ORDERS_TOOL, {"since": bad})
    stub = _StubMcp(_result([]))
    out = drivers.PlatformMcpDriver(client=stub).execute("shop", ORDERS_TOOL, {"since": bad})
    assert out.ok is False and out.error == "ConfigError: the shop call cannot be built from these arguments"
    assert stub.calls == []


def test_a_dollar_inside_a_string_is_only_text():
    assert mcp.call_values(ORDERS_TOOL, {"since": "costs $5"})["since"] == "costs $5"


def test_an_argument_the_mapping_cannot_take_is_a_config_error_not_a_crash():
    tool = {**ORDERS_TOOL, "mcp": {**ORDERS_TOOL["mcp"], "pipeline": [{"$match": {"note": "n={{since}}"}}]}}
    stub = _StubMcp(_result([]))
    out = drivers.PlatformMcpDriver(client=stub).execute("shop", tool, {"since": {1, 2}})  # not JSON
    assert out.ok is False and out.error.startswith("ConfigError") and stub.calls == []


def test_the_validator_refuses_placeholders_in_field_names_and_banned_operators():
    bundle = load_bundle(FIXTURE)

    def shop(**mapping):
        def edit(body, files):
            body["driver"] = "mcp"
            body["tools"][0]["mcp"] = {
                "tool": "find",
                "collection": "orders",
                "result_key": "orders",
                "filter": {"_id": "x"},
                **mapping,
            }

        return mutated(bundle, "connector", "shop", edit)

    assert validate_bundle(shop()) == []
    only_error(shop(filter={"{{order_ids}}": 1}), mentions="field name", kind="connector")
    only_error(shop(tool="update-many"), mentions="a read may call only", kind="connector")
    only_error(shop(tool="insert-many"), mentions="a read may call only", kind="connector")
    only_error(shop(pipeline=[{"$out": "stolen"}]), mentions="$out", kind="connector")
    only_error(shop(filter={"$expr": {"$function": {"body": "x"}}}), mentions="$function", kind="connector")


def test_the_validator_refuses_a_write_mapping_unless_writes_are_on(monkeypatch):
    bundle = load_bundle(FIXTURE)

    def edit(body, files):
        body["driver"] = "mcp"
        body["tools"][0]["action_class"] = "write"
        body["tools"][0]["mcp"] = {
            "tool": "update-many",
            "collection": "orders",
            "filter": {"_id": "x"},
            "update": {"$set": {"a": 1}},
        }

    monkeypatch.delenv("NM_MCP_WRITES", raising=False)
    only_error(mutated(bundle, "connector", "shop", edit), mentions="read-only", kind="connector")
    monkeypatch.setenv("NM_MCP_WRITES", "1")
    assert validate_bundle(mutated(bundle, "connector", "shop", edit)) == []

    def empty_filter(body, files):
        edit(body, files)
        body["tools"][0]["mcp"]["filter"] = {}

    only_error(
        mutated(bundle, "connector", "shop", empty_filter), mentions="non-empty filter", kind="connector"
    )


def test_only_a_platform_connector_can_use_the_platform_server():
    bundle = load_bundle(FIXTURE)
    org_key = owners.org_key("org_3f2a9c1b7d4e5f60", "shop")

    def edit(body, files):
        body["driver"] = "mcp"
        body["tools"][0]["mcp"] = {
            "tool": "find",
            "collection": "orders",
            "result_key": "orders",
            "filter": {"_id": "x"},
        }

    mapped = mutated(bundle, "connector", "shop", edit)
    assert validate_bundle(mapped) == []
    items = dict(mapped.items)
    shop = items.pop(("connector", "shop"))
    items[("connector", org_key)] = replace(shop, key=org_key, path=f"connectors/{org_key}.yaml")
    errors = [e for e in validate_bundle(Bundle(items=items)) if e.kind == "connector" and e.key == org_key]
    assert any("only a platform connector" in e.message for e in errors)


def test_an_org_connector_never_gets_the_platform_driver(monkeypatch):
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    key = owners.org_key("org_3f2a9c1b7d4e5f60", "shop")
    for mode in ("live", "auto"):
        assert isinstance(drivers.driver_for(MCP_CONNECTOR, mode, key=key), drivers.UnconnectedDriver)
    assert isinstance(drivers.driver_for(MCP_CONNECTOR, "live", key="shop"), drivers.PlatformMcpDriver)


def test_the_schema_makes_driver_and_transport_mcp_exclusive():
    import json

    from jsonschema import Draft202012Validator

    schema = json.loads((settings.defs_dir() / "_schemas" / "nm.connector.v1.schema.json").read_text("utf-8"))
    tools = [
        {
            "id": "a",
            "slug": "A",
            "action_class": "read",
            "capability": "x.read",
            "description": "d",
            "input_schema": {},
        }
    ]
    defaults = {"read": "permit", "write": "deny", "delete": "deny", "money": "deny"}
    base = {"app": "App", "tools": tools, "defaults": defaults}
    validator = Draft202012Validator(schema)
    server = {"transport": "mcp", "server": "mcp_0123456789ab"}
    assert not list(validator.iter_errors({**base, **server}))
    assert list(validator.iter_errors({**base, **server, "driver": "mcp"}))
    assert list(validator.iter_errors({**base, **server, "driver": "composio"}))
    assert not list(validator.iter_errors({**base, "toolkit": "t", "driver": "mcp"}))


# --- receipts and logs ------------------------------------------------------------------------------


def test_receipts_carry_no_server_text_host_or_env_name(caplog):
    leak = "ECONNREFUSED mongodb://admin:pw@db.internal:27017/nm_demo find orders {$where: 1}"
    caplog.set_level(logging.DEBUG)
    failed = drivers.PlatformMcpDriver(client=_StubMcp(_result(text=[leak], is_error=True))).execute(
        "shop", ORDERS_TOOL, {"since": "x", "limit": 5}
    )
    assert failed.error == "ToolError: the shop read failed"
    assert "db.internal" not in caplog.text and "admin" not in caplog.text
    unset = drivers.PlatformMcpDriver(client=mcp.McpClient(None)).execute("shop", ORDERS_TOOL, {"since": "x"})
    assert unset.error == "ConfigError: the shop connection is not set up"


def test_a_transport_failure_names_only_its_type():
    boom = _StubMcp(raises=mcp.McpError("TimeoutError"))
    out = drivers.PlatformMcpDriver(client=boom).execute("shop", ORDERS_TOOL, {"since": "x"})
    assert out.error == "McpError: the shop call failed"


def test_the_platform_client_shares_the_logging_rules_with_the_org_client():
    import app.custom_mcp.client as org_client

    assert org_client.mcp_logging is mcp_logging and mcp.mcp_logging is mcp_logging
    for name in mcp_logging.SDK_MODULES:
        filters = [f for f in logging.getLogger(name).filters if isinstance(f, mcp_logging.NoTraceback)]
        assert len(filters) == 1
    for name in mcp_logging.QUIET:
        assert logging.getLogger(name).level >= logging.WARNING


# --- real sessions against a server on loopback -----------------------------------------------------


def _platform_server():
    server = _server("Mongo")

    @server.tool()
    def aggregate(
        database: str, collection: str, pipeline: list[dict], connectionId: str = ""
    ) -> dict[str, Any]:
        return {"documents": [{"n": 1}], "count": 1, "appliedLimits": []}

    @server.tool()
    def count(database: str, collection: str) -> dict[str, Any]:
        return {"count": 3}

    @server.tool()
    async def slow() -> dict[str, Any]:
        await anyio.sleep(30)
        return {}

    @server.tool()
    def big() -> str:
        return "x" * 50_000

    return server


@pytest.fixture
def platform():
    fake = FakeMcp(_platform_server()).start()
    fake.url = f"http://127.0.0.1:{fake.port}/mcp"
    yield fake
    fake.stop()


def _client(fake, **kw) -> mcp.McpClient:
    return mcp.McpClient(fake.url, token=TOKEN, **kw)


def test_a_session_lists_tools_and_calls_one_with_the_bearer_token(platform):
    client = _client(platform)
    assert sorted(client.list_tools()) == ["aggregate", "big", "count", "slow"]
    result = client.call_tool("aggregate", {"database": "d", "collection": "c", "pipeline": []})
    assert mcp.documents_of(result) == [{"n": 1}]
    assert platform.paths and set(platform.paths) == {"/mcp"}


def test_the_driver_runs_a_read_through_a_real_session(platform):
    out = drivers.PlatformMcpDriver(client=_client(platform), database="d").execute(
        "shop", ORDERS_TOOL, {"since": "2026-10-01T00:00:00Z"}
    )
    assert out == drivers.ToolResult(ok=True, data={"orders": [{"n": 1}]}, mocked=False)


def test_a_wrong_token_is_a_failure_that_names_neither_the_token_nor_the_address(platform):
    with pytest.raises(mcp.McpError) as caught:
        mcp.McpClient(platform.url, token="wrong-token-9").list_tools()
    text = str(caught.value)
    assert "wrong-token-9" not in text and "127.0.0.1" not in text and str(platform.port) not in text


def test_a_call_that_takes_too_long_ends_at_the_deadline(platform):
    started = time.monotonic()
    with pytest.raises(mcp.McpError) as caught:
        _client(platform, call_timeout_s=0.6).call_tool("slow", {})
    assert time.monotonic() - started < 3.0
    assert str(caught.value) in {"TimeoutError", "McpError"}


def test_a_response_over_the_cap_ends_the_session(platform, monkeypatch):
    monkeypatch.setattr(mcp, "MAX_RESPONSE_BYTES", 5_000)
    started = time.monotonic()
    with pytest.raises(mcp.McpError):
        _client(platform).call_tool("big", {})
    assert time.monotonic() - started < 5.0


def test_a_redirect_is_not_followed(platform):
    with pytest.raises(mcp.McpError):
        mcp.McpClient(platform.url.replace("/mcp", "/moved"), token=TOKEN).list_tools()
    assert platform.paths.count("/mcp") == 0


def test_the_session_also_works_from_inside_a_running_event_loop(platform):
    async def inside() -> list[str]:
        return _client(platform).list_tools()

    assert len(anyio.run(inside)) == 4


def test_no_log_record_carries_the_query_string_or_the_token(platform, caplog):
    caplog.set_level(logging.DEBUG)
    url = f"{platform.url}?key=SECRETVALUE"
    mcp.McpClient(url, token=TOKEN).list_tools()
    with pytest.raises(mcp.McpError):
        mcp.McpClient(url, token="wrong-token-9").list_tools()
    assert (
        "SECRETVALUE" not in caplog.text and TOKEN not in caplog.text and "wrong-token-9" not in caplog.text
    )


def test_the_call_deadline_ends_inside_the_activity_that_runs_it():
    from app.worker import workflow

    assert mcp.PROBE_TIMEOUT_S < mcp.CALL_TIMEOUT_S
    assert timedelta(seconds=mcp.CALL_TIMEOUT_S) < workflow._TOOL_TIMEOUT
    # A call may follow a probe (auto mode) inside one activity attempt's budget.
    assert timedelta(seconds=mcp.PROBE_TIMEOUT_S + mcp.CALL_TIMEOUT_S) < workflow._TOOL_TIMEOUT


# --- https ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://mcp.example.com/mcp", True),
        ("http://127.0.0.1:8085/mcp", True),
        ("http://localhost:8085/mcp", True),
        ("http://[::1]:8085/mcp", True),
        ("http://mcp.example.com/mcp", False),
        ("http://10.0.0.5:8085/mcp", False),
        ("ftp://127.0.0.1/mcp", False),
        ("mcp.example.com/mcp", False),
        ("", False),
    ],
)
def test_the_bearer_token_never_goes_out_in_clear(monkeypatch, url, expected):
    monkeypatch.setenv("NM_MCP_URL", url)
    assert (settings.mcp_url() == url) is expected
    if not expected:
        assert settings.mcp_url() is None


# --- auto mode --------------------------------------------------------------------------------------


def _counting(monkeypatch, answers=True):
    calls = {"n": 0, "answers": answers}

    def is_available(self):
        calls["n"] += 1
        return calls["answers"]

    monkeypatch.setattr(drivers.PlatformMcpDriver, "is_available", is_available)
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    return calls


def test_auto_mode_checks_the_server_once_a_minute(monkeypatch):
    calls = _counting(monkeypatch)
    clock = {"now": 1000.0}
    monkeypatch.setattr(drivers.time, "monotonic", lambda: clock["now"])
    for _ in range(5):
        assert isinstance(drivers.driver_for(MCP_CONNECTOR, "auto"), drivers.PlatformMcpDriver)
    assert calls["n"] == 1
    calls["answers"] = False
    clock["now"] += drivers.PROBE_TTL_S - 1
    assert isinstance(drivers.driver_for(MCP_CONNECTOR, "auto"), drivers.PlatformMcpDriver)
    clock["now"] += 2
    assert isinstance(drivers.driver_for(MCP_CONNECTOR, "auto"), drivers.SandboxDriver)
    assert calls["n"] == 2


def test_the_catalog_forecast_never_opens_a_session(monkeypatch):
    calls = _counting(monkeypatch, answers=False)
    forecast = SandboxForecast("auto")
    assert forecast("custom-business-app", MCP_CONNECTOR) is False  # the URL is set: forecast live
    monkeypatch.delenv("NM_MCP_URL")
    assert SandboxForecast("auto")("custom-business-app", MCP_CONNECTOR) is True
    assert SandboxForecast("live")("custom-business-app", MCP_CONNECTOR) is False
    assert SandboxForecast("sandbox")("custom-business-app", MCP_CONNECTOR) is True
    assert calls["n"] == 0


def _snapshot(**extra) -> dict:
    tool = {"id": "list_orders", "slug": "X_LIST", "action_class": "read", "mcp": ORDERS_TOOL["mcp"]}
    connector = {"body": {**MCP_CONNECTOR, "tools": [tool]}}
    return {"defs": {"connector": {"shop": connector}}, **extra}


def test_a_run_settles_the_server_once_and_every_call_follows(monkeypatch):
    calls = _counting(monkeypatch, answers=True)
    assert gateway.settle_platform_mcp(_snapshot(), "auto", answers=True) == "live"
    assert gateway.settle_platform_mcp(_snapshot(), "auto", answers=False) == "sandbox"

    live = _snapshot(platform_mcp="live")
    sandbox = _snapshot(platform_mcp="sandbox")
    before = calls["n"]
    # Whatever the server does later, a run keeps its answer and asks nothing.
    assert isinstance(
        gateway.driver_of(live, "shop", live["defs"]["connector"]["shop"]["body"], "auto"),
        drivers.PlatformMcpDriver,
    )
    assert isinstance(
        gateway.driver_of(sandbox, "shop", sandbox["defs"]["connector"]["shop"]["body"], "auto"),
        drivers.SandboxDriver,
    )
    assert gateway.runs_simulated(live, "shop.list_orders", "auto") is False
    assert gateway.runs_simulated(sandbox, "shop.list_orders", "auto") is True
    assert calls["n"] == before


def test_a_pinned_live_run_fails_the_call_when_the_server_goes_away(monkeypatch):
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    snapshot = _snapshot(platform_mcp="live")
    driver = gateway.driver_of(snapshot, "shop", snapshot["defs"]["connector"]["shop"]["body"], "auto")
    assert isinstance(driver, drivers.PlatformMcpDriver)
    tool = snapshot["defs"]["connector"]["shop"]["body"]["tools"][0]
    out = drivers.PlatformMcpDriver(client=_StubMcp(raises=mcp.McpError("ConnectError"))).execute(
        "shop", {**tool, "input_schema": {}}, {"since": "x", "limit": 5}
    )
    assert out.ok is False and out.mocked is False and out.error == "McpError: the shop call failed"


def test_nothing_is_pinned_outside_auto_mode_or_without_a_platform_connector(monkeypatch):
    calls = _counting(monkeypatch)
    assert gateway.settle_platform_mcp(_snapshot(), "live", answers=True) is None
    assert gateway.settle_platform_mcp(_snapshot(), "sandbox", answers=True) is None
    sandbox_test = _snapshot(connector_mode="sandbox")
    assert gateway.settle_platform_mcp(sandbox_test, "auto", answers=True) is None
    org_routed = _snapshot(routing="org")
    assert gateway.settle_platform_mcp(org_routed, "auto", answers=True) is None
    assert (
        gateway.settle_platform_mcp(
            {"defs": {"connector": {"s": {"body": {"toolkit": "t"}}}}}, "auto", answers=True
        )
        is None
    )
    assert calls["n"] == 0


# --- the run pins the answer -------------------------------------------------------------------------

DESK = "order-to-cash-exception-desk"


def _start_desk(user) -> dict:
    assert (
        user.post(
            f"/v1/organizations/{user.org_id}/agent-installations",
            json={"packSlug": DESK, "capMinor": 2000, "reviewerPool": "team_then_network"},
        ).status_code
        == 201
    )
    for app in ("custom-business-app", "gmail"):
        assert user.connect(app).status_code == 200
    return user.post("/v1/workflow-runs", json={"packSlug": DESK, "input": {}, "budgetMinor": 2000})


def test_an_org_routed_run_pins_nothing_and_never_asks_the_server(ana, starts, db, monkeypatch):
    from tests.test_live_catalog import _rows

    monkeypatch.setenv("NM_CONNECTOR_MODE", "auto")
    _counting(monkeypatch, answers=True)
    started = _start_desk(ana)
    assert started.status_code == 202, started.text
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", started.json()["id"])
    assert gateway.PLATFORM_MCP_PIN not in row["snapshot"]


def test_a_demo_run_pins_what_the_server_check_said_when_it_started(api, rec, db, monkeypatch):
    from tests.test_live_catalog import _rows

    monkeypatch.setenv("NM_CONNECTOR_MODE", "auto")
    calls = _counting(monkeypatch, answers=True)
    from app import real_runs
    from tests.test_real_runs import START

    build = real_runs.build_snapshot

    def with_platform_connector(*args, **kwargs):  # the demo packs have no `driver: mcp` connector
        snapshot = build(*args, **kwargs)
        connector = {"body": {**MCP_CONNECTOR, "tools": []}}
        defs = {**snapshot["defs"], "connector": {**snapshot["defs"]["connector"], "shop": connector}}
        return {**snapshot, "defs": defs}

    monkeypatch.setattr(real_runs, "build_snapshot", with_platform_connector)
    body = START
    first = api.post("/v1/workflow-runs", json=body)
    assert first.status_code == 202, first.text
    calls["answers"] = False
    drivers.reset_probe_cache()
    second = api.post("/v1/workflow-runs", json=body)
    assert second.status_code == 202, second.text
    pins = [
        _rows(db, "SELECT snapshot FROM runs WHERE id = %s", r.json()["id"])[0]["snapshot"].get(
            gateway.PLATFORM_MCP_PIN
        )
        for r in (first, second)
    ]
    assert pins == ["live", "sandbox"]  # each run keeps the answer it started with


def test_a_run_in_sandbox_mode_pins_nothing(ana, starts, db, monkeypatch):
    from tests.test_live_catalog import _rows

    calls = _counting(monkeypatch)
    started = _start_desk(ana)
    assert started.status_code == 202, started.text
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", started.json()["id"])
    assert gateway.PLATFORM_MCP_PIN not in row["snapshot"] and calls["n"] == 0


# --- fix round: unsettled runs, listing, receipts, operators ----------------------------------------------


def test_an_auto_run_with_no_pin_fails_the_call_instead_of_probing(monkeypatch):
    calls = _counting(monkeypatch, answers=True)
    snapshot = _snapshot()
    body = snapshot["defs"]["connector"]["shop"]["body"]
    driver = gateway.driver_of(snapshot, "shop", body, "auto", tool=body["tools"][0])
    assert isinstance(driver, drivers.UnsettledDriver)
    out = driver.execute("shop", body["tools"][0], {})
    assert out.ok is False and out.mocked is False
    assert out.error == "ConfigError: the shop connection was not settled when the run started"
    assert gateway.runs_simulated(snapshot, "shop.list_orders", "auto") is False
    assert calls["n"] == 0
    # A tool without a mapping still answers from sandbox data, and a pinned or live run is unaffected.
    unmapped = {**body["tools"][0], "mcp": None}
    assert isinstance(gateway.driver_of(snapshot, "shop", body, "auto", tool=unmapped), drivers.SandboxDriver)
    assert isinstance(
        gateway.driver_of(snapshot, "shop", body, "live", tool=body["tools"][0]), drivers.PlatformMcpDriver
    )


def test_a_listing_longer_than_the_pages_read_is_unavailable(monkeypatch):
    class Endless:
        configured = True

        def list_tools(self):
            raise mcp.McpError("TooManyPages")

    assert drivers.PlatformMcpDriver(client=Endless()).is_available() is False


def test_a_real_listing_with_a_cursor_past_the_last_page_raises(monkeypatch):
    server = _server("Endless")
    fake = FakeMcp(server).start()
    try:
        from mcp.types import ListToolsResult, Tool

        async def pages(request):
            tool = Tool(name="aggregate", inputSchema={"type": "object"})
            return ListToolsResult(tools=[tool], nextCursor="more")

        server._mcp_server.list_tools()(lambda: None)  # keep the decorator import path exercised
        from mcp.types import ListToolsRequest

        server._mcp_server.request_handlers[ListToolsRequest] = pages
        with pytest.raises(mcp.McpError, match="TooManyPages"):
            mcp.McpClient(f"http://127.0.0.1:{fake.port}/mcp", token=TOKEN).list_tools()
    finally:
        fake.stop()


@pytest.mark.parametrize(
    "extra",
    ["atlas-local-create-deployment", "atlas-local-delete-deployment", "something-new", "create-index"],
)
def test_the_server_check_refuses_any_tool_not_known_to_be_read_only(monkeypatch, extra):
    monkeypatch.delenv("NM_MCP_WRITES", raising=False)
    tools = ("find", "aggregate", "list-collections", "collection-schema", "db-stats", "explain", extra)
    assert drivers.PlatformMcpDriver(client=_StubMcp(tools=tools)).is_available() is False
    assert drivers.PlatformMcpDriver(client=_StubMcp(tools=tools[:-1])).is_available() is True


def test_a_non_finite_argument_is_refused():
    for bad in (float("nan"), float("inf"), [1, float("-inf")]):
        with pytest.raises(mcp.PlaceholderError):
            mcp.call_values(ORDERS_TOOL, {"since": bad})


def test_the_partial_result_receipt_does_not_name_the_server_limits(caplog):
    structured = {"documents": [], "appliedLimits": ["config.maxDocumentsPerQuery"]}
    out = drivers.PlatformMcpDriver(client=_StubMcp(_result(structured=structured))).execute(
        "shop", ORDERS_TOOL, {"since": "x"}
    )
    assert out.error == "ToolError: the server returned only part of the result"


def test_the_sdk_streamable_http_logger_only_speaks_at_error():
    assert logging.getLogger("mcp.client.streamable_http").level >= logging.ERROR


def test_a_banned_operator_nested_in_lookup_and_union_with_pipelines_is_refused():
    nested = [
        {"$lookup": {"from": "o", "pipeline": [{"$match": {}}, {"$out": "stolen"}], "as": "x"}},
        {"$unionWith": {"coll": "o", "pipeline": [{"$merge": {"into": "stolen"}}]}},
        {
            "$unionWith": {
                "coll": "o",
                "pipeline": [
                    {
                        "$lookup": {
                            "from": "p",
                            "pipeline": [
                                {"$project": {"v": {"$function": {"body": "x", "args": [], "lang": "js"}}}}
                            ],
                            "as": "y",
                        }
                    }
                ],
            }
        },
    ]
    for stage in nested:
        refused = mcp_mapping.refusal("read", _read(pipeline=[stage]), writes_enabled=False)
        assert refused is not None and refused.code == "operator"
    stub = _StubMcp(_result([]))
    forged = {**ORDERS_TOOL, "mcp": {**ORDERS_TOOL["mcp"], "pipeline": [nested[1]]}}
    assert drivers.PlatformMcpDriver(client=stub).execute("shop", forged, {"since": "x"}).ok is False
    assert stub.calls == []
