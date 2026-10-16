"""The MCP connector driver: placeholder mapping, the connector schema and validator rules for `driver: mcp`,
driver selection per connector mode, a call shaped through a fake MCP session, and the Exception Desk
connector's mappings producing the contract its sandbox fixtures record. No server is needed;
`test_mcp_driver_live.py` runs the same mappings against one."""

import json
from types import SimpleNamespace

import pytest

from app import settings
from app.defs.loader import load_bundle
from app.defs.validate import validate_bundle
from app.runtime import drivers, gateway, mcp
from tests import sample_packs as sp
from tests.test_defs_engine import FIXTURE, mutated, only_error
from tests.test_runtime_core import _StubComposio

PACK = "order-to-cash-exception-desk"
CONNECTOR = "custom-business-app"
# connector, tool -> the key the tool's response (and its fixture file) carries the rows under
READS = {
    (CONNECTOR, "list_store_orders"): "orders",
    (CONNECTOR, "list_store_payments"): "payments",
    (CONNECTOR, "list_sales_orders"): "sales_orders",
    (CONNECTOR, "list_customers"): "customers",
    (CONNECTOR, "list_customer_payments"): "payments",
    (CONNECTOR, "list_served_orders"): "served_orders",
    (CONNECTOR, "list_sales"): "sales",
}
WRITES = [(CONNECTOR, "add_ledger_note"), (CONNECTOR, "add_warehouse_note")]
ORDERS_TOOL = {
    "id": "list_orders",
    "action_class": "read",
    "input_schema": {
        "type": "object",
        "properties": {"since": {"type": "string"}, "limit": {"type": "integer", "default": 50}},
    },
    "mcp": {
        "tool": "aggregate",
        "collection": "orders",
        "result_key": "orders",
        "pipeline": [{"$match": {"placed": {"$gte": "{{since}}"}}}, {"$limit": "{{limit}}"}],
    },
}
NOTE_TOOL = {
    "id": "add_note",
    "action_class": "write",
    "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}, "note": {}}},
    "mcp": {
        "tool": "update-many",
        "collection": "orders",
        "filter": {"_id": "{{order_id}}"},
        "update": {"$push": {"notesList": {"content": "{{note}}", "createdDate": {"$date": "{{now}}"}}}},
        "result": {"ok": True, "order_id": "{{order_id}}"},
    },
}


def _tool(connector: str, tool_id: str) -> dict:
    return next(t for t in sp.body("connector", connector)["tools"] if t["id"] == tool_id)


# --- placeholders ----------------------------------------------------------------------------------


def test_placeholders_are_collected_from_every_string():
    spec = {"filter": {"_id": "{{order_id}}", "{{key}}": 1}, "pipeline": [{"$limit": "{{ limit }}"}], "n": 3}
    assert mcp.placeholders(spec) == {"order_id", "key", "limit"}
    assert mcp.placeholders("plain text") == set()


def test_a_whole_string_placeholder_keeps_the_argument_s_type():
    values = {"limit": 50, "ids": ["a", "b"], "flag": False, "name": "Ana"}
    rendered = mcp.render({"$limit": "{{limit}}", "in": "{{ids}}", "f": "{{flag}}", "s": "{{name}}"}, values)
    assert rendered == {"$limit": 50, "in": ["a", "b"], "f": False, "s": "Ana"}
    assert type(rendered["$limit"]) is int and type(rendered["f"]) is bool


def test_an_embedded_placeholder_substitutes_text():
    values = {"note": "late by 3 days", "n": 7, "ids": [1, 2]}
    assert mcp.render("Desk: {{note}} ({{n}}) {{ids}}", values) == "Desk: late by 3 days (7) [1, 2]"
    assert mcp.render({"{{note}}": ["{{n}}x"]}, values) == {"late by 3 days": ["7x"]}


def test_an_unknown_placeholder_is_an_error():
    with pytest.raises(mcp.PlaceholderError, match="'missing'"):
        mcp.render({"a": "{{missing}}"}, {"other": 1})
    with pytest.raises(mcp.PlaceholderError):
        mcp.render("x {{missing}} y", {})


def test_call_values_take_the_schema_defaults_and_the_call_time():
    values = mcp.call_values(ORDERS_TOOL, {"since": "2026-10-01T00:00:00Z"})
    assert values["since"] == "2026-10-01T00:00:00Z" and values["limit"] == 50
    assert values[mcp.NOW].endswith("Z") and len(values[mcp.NOW]) == len("2026-10-16T08:00:00.000Z")
    assert mcp.call_values(ORDERS_TOOL, {"since": "x", "limit": 5})["limit"] == 5


def test_arguments_carry_the_preconfigured_connection_the_database_and_the_mapping():
    values = mcp.call_values(ORDERS_TOOL, {"since": "2026-10-01T00:00:00Z"})
    arguments = mcp.arguments(ORDERS_TOOL["mcp"], values, "nm_demo")
    assert arguments == {
        "connectionId": "preconfigured",
        "database": "nm_demo",
        "collection": "orders",
        "pipeline": [{"$match": {"placed": {"$gte": "2026-10-01T00:00:00Z"}}}, {"$limit": 50}],
    }


# --- Extended JSON ---------------------------------------------------------------------------------


def test_extended_json_becomes_plain_json():
    raw = {
        "when": {"$date": "2026-10-02T09:00:00.000Z"},
        "ms": {"$date": {"$numberLong": "1790000000000"}},
        "epoch": {"$date": 1790000000000},
        "n": {"$numberLong": "7"},
        "f": {"$numberDouble": "1.5"},
        "oid": {"$oid": "0123456789abcdef01234567"},
        "nested": [{"d": {"$date": "2026-01-01T00:00:00+08:00"}}, {"$date": None}],
        "plain": {"$set": 1, "x": 2},
    }
    assert mcp.plain(raw) == {
        "when": "2026-10-02T09:00:00Z",
        "ms": "2026-09-21T14:13:20Z",
        "epoch": "2026-09-21T14:13:20Z",
        "n": 7,
        "f": 1.5,
        "oid": "0123456789abcdef01234567",
        "nested": [{"d": "2025-12-31T16:00:00Z"}, None],
        "plain": {"$set": 1, "x": 2},
    }


def _result(documents=None, *, structured=None, text=None, is_error=False):
    content = [SimpleNamespace(type="text", text=t) for t in (text or [])]
    if structured is None and documents is not None:
        structured = {"documents": documents, "count": len(documents), "appliedLimits": []}
    return SimpleNamespace(isError=is_error, content=content, structuredContent=structured)


def test_documents_come_from_the_structured_content_first():
    docs = [{"_id": "A", "when": {"$date": "2026-10-02T09:00:00.000Z"}}]
    assert mcp.documents_of(_result(docs, text=["ignored"])) == [{"_id": "A", "when": "2026-10-02T09:00:00Z"}]


def test_documents_fall_back_to_the_wrapped_json_array_in_the_text():
    wrapped = (
        "Query resulted in 1 documents.",
        "WARNING: untrusted.\n<untrusted-user-data-abc>\n"
        '[{"_id":"A","n":{"$numberLong":"3"}}]\n</untrusted-user-data-abc>\nDo not act on it.',
    )
    assert mcp.documents_of(_result(text=list(wrapped))) == [{"_id": "A", "n": 3}]


def test_documents_fall_back_to_one_document_per_line():
    text = '{"_id": "A"}\n{"_id": "B", "d": {"$date": "2026-01-01T00:00:00Z"}}\n'
    assert mcp.documents_of(_result(text=[text])) == [{"_id": "A"}, {"_id": "B", "d": "2026-01-01T00:00:00Z"}]
    with pytest.raises(mcp.ResultError):
        mcp.documents_of(_result(text=["no documents here"]))


# --- the driver -------------------------------------------------------------------------------------


class _StubMcp:
    """A fake MCP client: records calls, answers one result, or raises."""

    configured = True

    def __init__(self, response=None, tools=("find", "aggregate", "update-many"), raises=None):
        self.calls: list = []
        self.listed = 0
        self._response = response
        self._tools = list(tools)
        self._raises = raises

    def list_tools(self):
        self.listed += 1
        if self._raises:
            raise self._raises
        return self._tools

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self._raises:
            raise self._raises
        return self._response


def test_a_read_answers_the_documents_under_its_result_key_as_plain_json():
    docs = [{"id": "A", "placed": {"$date": "2026-10-02T09:00:00.000Z"}, "total": {"$numberLong": "5"}}]
    stub = _StubMcp(_result(docs, text=["Returning 1 documents."]))
    driver = drivers.McpDriver(client=stub, database="nm_demo")
    result = driver.execute("shop", ORDERS_TOOL, {"since": "2026-10-01T00:00:00Z"})
    assert result == drivers.ToolResult(
        ok=True, data={"orders": [{"id": "A", "placed": "2026-10-02T09:00:00Z", "total": 5}]}, mocked=False
    )
    name, arguments = stub.calls[0]
    assert name == "aggregate" and arguments["database"] == "nm_demo"
    assert arguments["pipeline"][1] == {"$limit": 50}


def test_a_write_answers_its_result_template_once_the_update_matched():
    stub = _StubMcp(_result(structured={"matchedCount": 1, "modifiedCount": 1, "upsertedCount": 0}))
    driver = drivers.McpDriver(client=stub, database="nm_demo")
    result = driver.execute("ledger", NOTE_TOOL, {"order_id": "SO-1", "note": "Chase it"})
    assert result == drivers.ToolResult(ok=True, data={"ok": True, "order_id": "SO-1"}, mocked=False)
    name, arguments = stub.calls[0]
    assert name == "update-many" and arguments["filter"] == {"_id": "SO-1"}
    note = arguments["update"]["$push"]["notesList"]
    assert note["content"] == "Chase it" and note["createdDate"]["$date"].endswith("Z")


def test_a_write_that_matched_nothing_fails():
    stub = _StubMcp(_result(structured={"matchedCount": 0, "modifiedCount": 0, "upsertedCount": 0}))
    result = drivers.McpDriver(client=stub).execute("ledger", NOTE_TOOL, {"order_id": "NO", "note": "x"})
    assert result.ok is False and result.error == "ToolError: the update matched no document"


def test_a_read_the_server_cut_short_fails_rather_than_answering_part_of_it():
    structured = {"documents": [{"id": "A"}], "count": 730, "appliedLimits": ["config.maxDocumentsPerQuery"]}
    result = drivers.McpDriver(client=_StubMcp(_result(structured=structured))).execute(
        "shop", ORDERS_TOOL, {"since": "x"}
    )
    assert result.ok is False and "config.maxDocumentsPerQuery" in result.error


def test_server_and_transport_errors_are_short_and_carry_no_url():
    noisy = "Error running aggregate at http://127.0.0.1:8085/mcp?token=abc: " + "x" * 300
    failed = drivers.McpDriver(client=_StubMcp(_result(text=[noisy], is_error=True))).execute(
        "shop", ORDERS_TOOL, {"since": "x"}
    )
    assert failed.ok is False and failed.mocked is False
    assert failed.error.startswith("ToolError: Error running aggregate") and "http" not in failed.error
    assert "token=abc" not in failed.error and len(failed.error) <= 140

    class Boom(Exception):
        pass

    broken = drivers.McpDriver(client=_StubMcp(raises=Boom("POST http://x failed"))).execute(
        "shop", ORDERS_TOOL, {"since": "x"}
    )
    assert broken.error == "Boom: the shop call failed"


def test_a_missing_mapping_or_argument_is_a_config_error():
    bare = drivers.McpDriver(client=_StubMcp()).execute("shop", {"id": "list_orders"}, {})
    assert bare.ok is False and bare.error == "ConfigError: tool shop.list_orders has no mcp mapping"
    stub = _StubMcp()
    result = drivers.McpDriver(client=stub).execute("shop", ORDERS_TOOL, {})
    assert result.error == "ConfigError: argument 'since' was not given" and stub.calls == []


def test_an_unset_url_fails_the_call_without_a_request(monkeypatch):
    monkeypatch.delenv("NM_MCP_URL", raising=False)
    result = drivers.McpDriver().execute("shop", ORDERS_TOOL, {"since": "x"})
    assert result.ok is False and result.error == "ConfigError: NM_MCP_URL is not set"


def test_is_available_asks_for_the_tool_list_and_never_raises():
    assert drivers.McpDriver(client=_StubMcp()).is_available() is True
    assert drivers.McpDriver(client=_StubMcp(tools=())).is_available() is False
    assert drivers.McpDriver(client=_StubMcp(raises=OSError("down"))).is_available() is False


def test_the_database_defaults_from_the_environment(monkeypatch):
    monkeypatch.delenv("NM_MCP_DATABASE", raising=False)
    assert drivers.McpDriver(client=_StubMcp()).database == "nm_demo"
    monkeypatch.setenv("NM_MCP_DATABASE", "nm_other")
    assert drivers.McpDriver(client=_StubMcp()).database == "nm_other"
    assert settings.mcp_url() is None or isinstance(settings.mcp_url(), str)


# --- driver selection -------------------------------------------------------------------------------

MCP_CONNECTOR = {"toolkit": "custom_business_app", "driver": "mcp", "tools": []}
COMPOSIO_CONNECTOR = {"toolkit": "shopify", "tools": []}


def test_sandbox_mode_never_touches_the_server(monkeypatch):
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr(drivers.McpDriver, "is_available", lambda self: pytest.fail("asked the server"))
    driver = drivers.driver_for(MCP_CONNECTOR, "sandbox", pack="order-to-cash-exception-desk")
    assert isinstance(driver, drivers.SandboxDriver) and driver.pack == "order-to-cash-exception-desk"


def test_live_mode_always_uses_the_mcp_driver(monkeypatch):
    monkeypatch.delenv("NM_MCP_URL", raising=False)
    assert isinstance(drivers.driver_for(MCP_CONNECTOR, "live"), drivers.McpDriver)
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    assert isinstance(drivers.driver_for(MCP_CONNECTOR, "live"), drivers.McpDriver)


def test_auto_mode_uses_the_server_only_when_set_and_answering(monkeypatch, caplog):
    available = {"value": True}
    monkeypatch.setattr(drivers.McpDriver, "is_available", lambda self: available["value"])
    monkeypatch.delenv("NM_MCP_URL", raising=False)
    assert isinstance(drivers.driver_for(MCP_CONNECTOR, "auto"), drivers.SandboxDriver)
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    assert isinstance(drivers.driver_for(MCP_CONNECTOR, "auto", pack="p"), drivers.McpDriver)
    available["value"] = False
    with caplog.at_level("WARNING"):
        driver = drivers.driver_for(MCP_CONNECTOR, "auto", pack="p")
    assert isinstance(driver, drivers.SandboxDriver) and driver.pack == "p"
    assert "custom_business_app" in caplog.text and "127.0.0.1" not in caplog.text


def test_other_connectors_keep_the_composio_behaviour(monkeypatch):
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr(drivers.McpDriver, "is_available", lambda self: pytest.fail("asked the server"))

    class FakeComposio(drivers.ComposioDriver):
        def __init__(self):
            super().__init__(client=_StubComposio())

        def is_connected(self, toolkit: str) -> bool:
            return False

    monkeypatch.setattr(drivers, "ComposioDriver", FakeComposio)
    assert isinstance(drivers.driver_for(COMPOSIO_CONNECTOR, "live"), FakeComposio)
    assert isinstance(drivers.driver_for(COMPOSIO_CONNECTOR, "auto"), drivers.SandboxDriver)
    with pytest.raises(ValueError):
        drivers.driver_for(MCP_CONNECTOR, "other")


def test_runs_simulated_follows_the_driver(monkeypatch):
    monkeypatch.setattr(drivers.McpDriver, "is_available", lambda self: True)
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    tool = {"id": "list_orders", "slug": "ECOMMERCE_LIST_ORDERS", "mcp": {"tool": "find", "collection": "x"}}
    connector = {"body": {**MCP_CONNECTOR, "tools": [tool]}}
    snapshot = {"defs": {"connector": {"ecommerce": connector}}}
    assert gateway.runs_simulated({**snapshot, "connector_mode": "sandbox"}, "ecommerce.list_orders", "auto")
    assert not gateway.runs_simulated(snapshot, "ecommerce.list_orders", "auto")
    assert not gateway.runs_simulated(snapshot, "ecommerce.list_orders", "live")
    assert gateway.runs_simulated(snapshot, "ecommerce.list_orders", "sandbox")


# --- schema and validator ---------------------------------------------------------------------------

READ_MAPPING = {"tool": "find", "collection": "orders", "filter": {"_id": {"$in": "{{order_ids}}"}}}


@pytest.fixture
def fixture_bundle():
    return load_bundle(FIXTURE)


def _connector_errors(bundle) -> list[str]:
    """The connector's own validation messages (a schema-invalid connector also fails what refers to it)."""
    return [e.message for e in validate_bundle(bundle) if e.kind == "connector"]


def _shop(fixture_bundle, driver="mcp", **changes):
    """The fixture's shop connector on `driver`, its one (read) tool mapped as READ_MAPPING with `changes`."""

    def edit(body, files):
        if driver is not None:
            body["driver"] = driver
        mapping = {**READ_MAPPING, "result_key": "orders", **changes}
        body["tools"][0]["mcp"] = {k: v for k, v in mapping.items() if v is not None}

    return mutated(fixture_bundle, "connector", "shop", edit)


def test_a_mapped_mcp_connector_is_valid(fixture_bundle):
    assert validate_bundle(_shop(fixture_bundle)) == []


def test_the_driver_is_one_of_composio_and_mcp(fixture_bundle):
    bad = mutated(fixture_bundle, "connector", "shop", lambda b, f: b.update(driver="rest"))
    [message] = _connector_errors(bad)
    assert message.startswith("driver: 'rest' is not one of")
    composio = mutated(fixture_bundle, "connector", "shop", lambda b, f: b.update(driver="composio"))
    assert validate_bundle(composio) == []


def test_a_mapping_rejects_unknown_fields(fixture_bundle):
    [message] = _connector_errors(_shop(fixture_bundle, sort={"_id": 1}))
    assert message.startswith("tools[0].mcp: Additional properties are not allowed ('sort'")


def test_only_an_mcp_connector_maps_tools(fixture_bundle):
    only_error(
        _shop(fixture_bundle, driver=None), mentions="only a `driver: mcp` connector", kind="connector"
    )


def test_a_read_of_an_mcp_connector_must_be_mapped_but_a_write_need_not(fixture_bundle):
    bad = mutated(fixture_bundle, "connector", "shop", lambda b, f: b.update(driver="mcp"))
    only_error(bad, mentions="read must map to an MCP call", kind="connector")

    def unmapped_write(body, files):
        body["driver"] = "mcp"
        body["tools"][0]["action_class"] = "write"

    assert validate_bundle(mutated(fixture_bundle, "connector", "shop", unmapped_write)) == []


def test_a_read_needs_a_result_key_and_a_query(fixture_bundle):
    only_error(_shop(fixture_bundle, result_key=None), mentions="result_key", kind="connector")
    only_error(_shop(fixture_bundle, filter=None), mentions="pipeline or a filter", kind="connector")
    only_error(
        _shop(fixture_bundle, update={"$set": {"x": 1}}), mentions="read cannot update", kind="connector"
    )


def test_a_write_needs_an_update_and_a_filter(fixture_bundle):
    def write(body, files):
        body["driver"] = "mcp"
        body["tools"][0]["action_class"] = "write"
        body["tools"][0]["mcp"] = {
            "tool": "update-many",
            "collection": "orders",
            "update": {"$set": {"x": 1}},
        }

    only_error(mutated(fixture_bundle, "connector", "shop", write), mentions=".filter", kind="connector")

    def complete(body, files):
        write(body, files)
        body["tools"][0]["mcp"]["filter"] = {"_id": "{{order_ids}}"}
        body["tools"][0]["mcp"]["result"] = {"ok": True, "at": "{{now}}"}

    assert validate_bundle(mutated(fixture_bundle, "connector", "shop", complete)) == []


def test_placeholders_must_name_the_tool_s_arguments(fixture_bundle):
    bad = _shop(fixture_bundle, filter={"_id": "{{order_id}}", "by": "{{now}}"})
    err = only_error(bad, mentions="{{order_id}} is not an argument", kind="connector")
    assert "now" not in err.message


# --- the demo connectors ---------------------------------------------------------------------------


def _fixture_rows(connector: str, tool_id: str) -> list[dict]:
    path = settings.defs_dir() / "packs" / PACK / "sandbox" / connector / f"{tool_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))[READS[(connector, tool_id)]]


def _project(pipeline: list[dict]) -> dict:
    [stage] = [s["$project"] for s in pipeline if "$project" in s]
    return stage


def test_the_demo_connector_runs_on_the_mcp_driver():
    assert sp.body("connector", CONNECTOR)["driver"] == "mcp"
    assert {t["id"] for t in sp.body("connector", CONNECTOR)["tools"]} == {t for _, t in [*READS, *WRITES]}
    assert sp.bundle_errors() == []


@pytest.mark.parametrize(("connector", "tool_id"), sorted(READS))
def test_each_read_projects_exactly_the_fixture_s_keys_in_order(connector, tool_id):
    spec = _tool(connector, tool_id)["mcp"]
    assert spec["tool"] == "aggregate" and spec["result_key"] == READS[(connector, tool_id)]
    rows = _fixture_rows(connector, tool_id)
    projected = [k for k in _project(spec["pipeline"]) if k != "_id"]
    assert projected == list(rows[0])
    assert all(list(r) == projected for r in rows)
    assert _project(spec["pipeline"])["_id"] == 0
    if "currency" in rows[0]:
        assert _project(spec["pipeline"])["currency"] == "PHP"


@pytest.mark.parametrize(("connector", "tool_id"), sorted(READS))
def test_each_read_s_placeholders_are_its_date_window(connector, tool_id):
    tool = _tool(connector, tool_id)
    names = mcp.placeholders(tool["mcp"])
    expected = set(tool["input_schema"].get("properties") or {})
    assert names == expected
    values = mcp.call_values(tool, {n: "2026-10-01T00:00:00Z" for n in expected - {"limit"}})
    arguments = mcp.arguments(tool["mcp"], values, "nm_demo")
    assert mcp.placeholders(arguments) == set() and arguments["collection"] == tool["mcp"]["collection"]


def test_the_date_strings_the_pipelines_produce_are_the_fixture_s_iso_format():
    for (connector, tool_id), rows in ((k, _fixture_rows(*k)) for k in READS):
        text = json.dumps(_project(_tool(connector, tool_id)["mcp"]["pipeline"]))
        dated = [k for k, v in rows[0].items() if isinstance(v, str) and v.endswith("Z") and "T" in v]
        for key in dated:
            assert f'"{key}": {{"$dateToString"' in text, (connector, tool_id, key)
        assert tool_id == "list_customers" or (dated and "%Y-%m-%dT%H:%M:%SZ" in text), (connector, tool_id)


@pytest.mark.parametrize(("connector", "tool_id"), WRITES)
def test_each_write_has_no_mapping_and_answers_from_its_sandbox_file(connector, tool_id, monkeypatch):
    """The server is read-only: a note is recorded, not written, in every connector mode."""
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr(drivers.McpDriver, "is_available", lambda self: True)
    body, tool = sp.body("connector", connector), _tool(connector, tool_id)
    assert "mcp" not in tool
    sandbox = json.loads(
        (settings.defs_dir() / "connectors" / "sandbox" / connector / f"{tool_id}.json").read_text("utf-8")
    )
    for mode in ("sandbox", "live", "auto"):
        driver = drivers.driver_for(body, mode, pack=PACK, tool=tool)
        assert isinstance(driver, drivers.SandboxDriver) and driver.pack == PACK, mode
        result = driver.execute(connector, tool, {"order_id": "ORD-260917", "note": "Please confirm."})
        assert result == drivers.ToolResult(ok=True, data=sandbox, mocked=True), mode


def test_in_live_mode_the_reads_go_to_the_server_and_the_writes_to_sandbox(monkeypatch):
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr(drivers.McpDriver, "is_available", lambda self: True)
    body = sp.body("connector", CONNECTOR)
    snapshot = {
        "defs": {"connector": {CONNECTOR: {"body": body}}, "pack": {PACK: {"body": {"slug": PACK}}}},
    }
    for mode in ("live", "auto"):
        for _, tool_id in READS:
            tool = _tool(CONNECTOR, tool_id)
            assert isinstance(drivers.driver_for(body, mode, tool=tool), drivers.McpDriver), (mode, tool_id)
            assert not gateway.runs_simulated(snapshot, f"{CONNECTOR}.{tool_id}", mode), (mode, tool_id)
        for _, tool_id in WRITES:
            tool = _tool(CONNECTOR, tool_id)
            chosen = drivers.driver_for(body, mode, pack=PACK, tool=tool)
            assert isinstance(chosen, drivers.SandboxDriver) and chosen.pack == PACK, (mode, tool_id)
            assert gateway.runs_simulated(snapshot, f"{CONNECTOR}.{tool_id}", mode), (mode, tool_id)
    # Without the tool, the connector as a whole still counts as live (the catalog's per-connector view).
    assert isinstance(drivers.driver_for(body, "live"), drivers.McpDriver)


def test_a_write_call_through_the_gateway_is_recorded_as_mocked(monkeypatch):
    monkeypatch.setenv("NM_MCP_URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr(drivers.McpDriver, "is_available", lambda self: True)
    snapshot = {
        "defs": {
            "connector": {CONNECTOR: {"body": sp.body("connector", CONNECTOR)}},
            "contract": {PACK: {"body": {"authorization": {"tool_capabilities": ["business.write"]}}}},
            "pack": {PACK: {"body": {"slug": PACK}}},
        }
    }
    decision, result = gateway.call_tool(
        snapshot=snapshot,
        tool_ref=f"{CONNECTOR}.add_ledger_note",
        args={"order_id": "ORD-260917", "note": "Please confirm."},
        approved=True,
        mode="live",
    )
    assert decision.verdict == gateway.PERMIT
    assert result is not None and result.ok and result.mocked is True
    assert result.data == {"ok": True, "order_id": "ORD-260917"}


def test_the_fixture_bundle_connector_stays_on_composio():
    body = load_bundle(FIXTURE).get("connector", "shop").body
    assert "driver" not in body and "mcp" not in body["tools"][0]
