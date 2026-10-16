"""Sorting an MCP server's tools: the server's hints and the importer's words decide read (runs freely), write
(asks first) or blocked; input schemas are checked and hardened; the connector body passes the meta-schema."""

import pytest

from app import tool_words
from app.custom_mcp import tools
from app.defs.model import Bundle, Definition, path_for
from app.defs.validate import validate_bundle

OBJECT = {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}
KEY = "org-a1--acme-crm"
SERVER = "mcp_0123456789ab"


def _tool(name: str, schema=None, **hints) -> tools.ListedTool:
    return tools.ListedTool(name=name, description=f"{name} tool", input_schema=schema or OBJECT, **hints)


def _errors(body: dict) -> list[str]:
    d = Definition(kind="connector", key=KEY, body=body, path=path_for("connector", KEY))
    return [e.message for e in validate_bundle(Bundle(items={("connector", KEY): d}))]


def test_names_split_into_upper_case_words():
    assert tool_words.name_words("getCustomer") == ["GET", "CUSTOMER"]
    assert tool_words.name_words("delete-customer_note") == ["DELETE", "CUSTOMER", "NOTE"]
    assert tool_words.plainly_reads(["LIST", "ORDERS"])
    assert not tool_words.plainly_reads(["GET", "AND", "PAY"])


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        (_tool("get_customer", read_only=True), ("read", "marked_read_only")),
        (_tool("list_orders", read_only=True), ("read", "marked_read_only")),
        (_tool("list_orders"), ("write", "changes_data")),
        (_tool("update_customer", read_only=True), ("write", "changes_data")),
        (_tool("send_email"), ("write", "changes_data")),
        (_tool("share_document", read_only=True), ("write", "changes_access")),
        (_tool("get_permissions", read_only=True), ("read", "marked_read_only")),
        (_tool("purge_cache", destructive=True), ("blocked", "marked_destructive")),
        (_tool("delete_customer", destructive=False), ("blocked", "deletes")),
        (_tool("archiveNote"), ("blocked", "deletes")),
        (_tool("refund_payment"), ("blocked", "moves_money")),
        (_tool("COMPOSIO_SEARCH_TOOLS", read_only=True), ("blocked", "reserved_name")),
    ],
)
def test_tools_are_sorted_from_hints_and_words(tool, expected):
    assert tools.classify(tool) == expected


def test_only_an_explicit_destructive_hint_blocks():
    assert tools.classify(_tool("note_customer", destructive=None)) == ("write", "changes_data")


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array", "items": {"type": "string"}},
        "not a schema",
        {"type": "object", "properties": 5},
        {"type": "object", "properties": {"a": {"$ref": "https://evil.test/schema.json"}}},
        {"type": "object", "properties": {"a": {"$dynamicRef": "http://evil.test/x"}}},
    ],
)
def test_a_tool_whose_inputs_cannot_be_checked_is_blocked(schema):
    assert tools.classify(_tool("get_customer", schema, read_only=True)) == ("blocked", "schema_unusable")


def test_an_input_schema_over_64_kb_is_blocked():
    huge = {
        "type": "object",
        "properties": {f"p{i}": {"type": "string", "description": "x" * 100} for i in range(700)},
    }
    assert tools.MAX_SCHEMA_BYTES == 64 * 1024
    assert tools.classify(_tool("get_customer", huge, read_only=True)) == ("blocked", "schema_too_large")


def test_a_local_ref_is_fine():
    schema = {
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/A"}},
        "$defs": {"A": {"type": "string"}},
    }
    assert tools.schema_problem(schema) is None


def test_hardening_refuses_undeclared_arguments_at_the_top_only():
    nested = {"type": "object", "properties": {"x": {"type": "object", "properties": {}}}}
    hard = tools.harden(nested)
    assert hard["additionalProperties"] is False
    assert "additionalProperties" not in hard["properties"]["x"]
    assert "additionalProperties" not in nested  # the input is not changed
    assert tools.harden({**OBJECT, "additionalProperties": True})["additionalProperties"] is True


def test_a_sample_comes_from_the_output_schema():
    out = {
        "type": "object",
        "properties": {"customer": {"$ref": "#/$defs/Customer"}, "count": {"type": "integer"}},
        "$defs": {"Customer": {"type": "object", "properties": {"name": {"type": "string"}}}},
    }
    assert tools.sample_of(out) == {"customer": {"name": "sample"}, "count": 1}
    assert tools.sample_of(None) is None
    assert tools.sample_of({"type": "string"}) is None
    assert tools.sample_of({"type": "object", "properties": [1, 2]}) is None


def test_sorting_gives_unique_ids_keeps_switches_and_caps_at_100():
    listed = [
        _tool("getCustomer", read_only=True),
        _tool("get_customer", read_only=True),
        _tool("refund_payment"),
    ]
    first = tools.sort_tools(listed)
    assert [(t.id, t.tool_class, t.on) for t in first] == [
        ("get_customer", "read", True),
        ("get_customer_2", "read", True),
        ("refund_payment", "blocked", False),
    ]
    assert first[2].input_schema == {}  # a blocked tool keeps no schema
    previous = [{**first[0].stored(), "on": False, "admin_off": True}]
    again = tools.sort_tools(listed, previous)
    assert (again[0].id, again[0].on) == ("get_customer", False)
    many = [_tool(f"get_item_{n}", read_only=True) for n in range(120)]
    assert len(tools.sort_tools(many)) == tools.MAX_TOOLS == 100


@pytest.mark.parametrize("name", ["", "x" * 129])
def test_a_tool_name_the_connector_cannot_hold_is_blocked_as_reserved(name):
    sorted_ = tools.sort_tools([_tool(name, read_only=True), _tool("get_customer", read_only=True)])
    assert (sorted_[0].tool_class, sorted_[0].why, sorted_[0].on) == ("blocked", "reserved_name", False)
    assert sorted_[1].tool_class == "read"


def test_a_tool_no_longer_blocked_comes_back_on():
    previous = [
        {"id": "send_note", "name": "send_note", "tool_class": "blocked", "why": "deletes", "on": False}
    ]
    assert tools.sort_tools([_tool("send_note")], previous)[0].on is True


def test_stored_tools_read_back_the_same():
    tool = tools.sort_tools([_tool("get_customer", read_only=True)])[0]
    assert tools.SortedTool.from_stored(tool.stored()) == tool


def test_the_connector_body_offers_only_usable_tools_and_passes_the_meta_schema():
    sorted_tools = tools.sort_tools(
        [_tool("get_customer", read_only=True), _tool("update_note"), _tool("refund_payment")]
    )
    body = tools.connector_body("Acme CRM", SERVER, sorted_tools, "acme-crm")
    assert (body["app"], body["transport"], body["server"]) == ("Acme CRM", "mcp", SERVER)
    assert [(t["id"], t["action_class"], t["capability"]) for t in body["tools"]] == [
        ("get_customer", "read", "acme-crm.read"),
        ("update_note", "write", "acme-crm.write"),
    ]
    assert body["tools"][0]["input_schema"]["additionalProperties"] is False
    assert body["defaults"] == {
        "read": "permit",
        "write": "require_approval",
        "delete": "deny",
        "money": "deny",
    }
    assert _errors(body) == []


def test_the_meta_schema_keeps_composio_and_mcp_apart():
    mcp = tools.connector_body("Acme CRM", SERVER, [], "acme-crm")
    assert _errors(mcp) == []  # every tool switched off is still a valid connector
    assert _errors({**mcp, "toolkit": "acme"}) != []
    assert _errors({k: v for k, v in mcp.items() if k != "server"}) != []
    assert _errors({**mcp, "server": "not-a-server"}) != []
    composio = {"app": "Shop", "toolkit": "shopify", "tools": [], "defaults": mcp["defaults"]}
    assert _errors(composio) != []  # a composio connector needs a tool
    assert _errors({**composio, "toolkit": None}) != []


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("HTTPDelete", "deletes"),
        ("APIDeleteUser", "deletes"),
        ("Delete2Items", "deletes"),
        ("deletecustomer", "deletes"),
        ("drop_table", "deletes"),
        ("wipeAll", "deletes"),
        ("list_and_refund", "moves_money"),
        ("get_and_transfer_funds", "moves_money"),
    ],
)
def test_free_form_names_cannot_hide_a_delete_or_money_move(name, why):
    assert tools.classify(_tool(name, read_only=True)) == ("blocked", why)


def test_a_new_tool_listed_first_does_not_take_a_stored_tools_id():
    previous = [
        {"id": "get_customer", "name": "getCustomer", "tool_class": "read", "why": "marked_read_only"}
    ]
    listed = [_tool("get-customer", read_only=True), _tool("getCustomer", read_only=True)]
    assert [(t.name, t.id) for t in tools.sort_tools(listed, previous)] == [
        ("get-customer", "get_customer_2"),
        ("getCustomer", "get_customer"),
    ]


def test_the_joined_name_check_applies_only_to_unsplit_names():
    assert tools.classify(_tool("dropdown_options", read_only=True)) == ("read", "marked_read_only")
    assert tools.classify(_tool("deletecustomer", read_only=True)) == ("blocked", "deletes")
    assert tools.classify(_tool("dropall", read_only=True)) == ("blocked", "deletes")


@pytest.mark.parametrize(
    "name",
    ["list_refunds", "get_refund", "getCharge", "list_transfers", "get_transfer_status", "list_payouts"],
)
def test_payment_reads_still_run_freely(name):
    assert tools.classify(_tool(name, read_only=True)) == ("read", "marked_read_only")


@pytest.mark.parametrize("name", ["get_reset_status", "get_drop_off_points"])
def test_reset_and_drop_inside_a_read_name_do_not_block(name):
    assert tools.classify(_tool(name, read_only=True)) == ("read", "marked_read_only")


def test_a_reset_asks_first_and_a_leading_drop_is_blocked():
    assert tools.classify(_tool("reset_password")) == ("write", "changes_data")
    assert tools.classify(_tool("drop_table")) == ("blocked", "deletes")


def test_an_admins_off_choice_survives_blocked_and_unblocked():
    off = [
        {"id": "send_note", "name": "send_note", "tool_class": "write", "why": "changes_data", "on": False}
    ]
    blocked = tools.sort_tools([_tool("send_note", destructive=True)], off)
    assert (blocked[0].tool_class, blocked[0].on, blocked[0].admin_off) == ("blocked", False, True)
    back = tools.sort_tools([_tool("send_note")], [blocked[0].stored()])
    assert (back[0].tool_class, back[0].on) == ("write", False)
