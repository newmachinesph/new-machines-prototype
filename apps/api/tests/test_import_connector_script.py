"""scripts/import_connector.py sorts a Composio toolkit's actions and adds them to a connector file.
No network: the Composio client is never built."""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).parents[1] / "scripts" / "import_connector.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("import_connector", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["import_connector"] = module
    spec.loader.exec_module(module)
    return module


ic = _load_script()

SCHEMA = {
    "type": "object",
    "title": "Request",
    "required": ["spreadsheet_id"],
    "properties": {
        "spreadsheet_id": {
            "type": "string",
            "description": "The  id.",
            "examples": ["abc"],
            "maxLength": 200,
        },
        "rows": {"type": "array", "items": {"type": "string", "title": "Row"}},
    },
}


def _tool(slug, tags=(), name="", **more):
    return {
        "slug": slug,
        "name": name,
        "tags": list(tags),
        "version": "20261001_00",
        "input_parameters": SCHEMA,
        **more,
    }


@pytest.mark.parametrize(
    ("slug", "tags", "expected"),
    [
        ("SHEETS_GET_INFO", ["readOnlyHint"], "read"),
        ("SHEETS_LOOKUP_ROW", [], "read"),
        ("SHEETS_BATCH_GET", [], "read"),
        ("SHEETS_FIND_REPLACE", [], "write"),  # starts like a read, but replaces
        ("SHEETS_FIND_REPLACE", ["updateHint"], "write"),
        ("SHEETS_UPSERT_ROWS", ["createHint", "updateHint"], "write"),
        ("SHEETS_FORMAT_CELL", [], "write"),  # anything not known to be a read asks first
        ("SHEETS_DELETE_SHEET", [], "delete"),
        ("SHEETS_CLEAR_VALUES", ["readOnlyHint"], "delete"),  # destructive words beat a read-only hint
        ("SHEETS_BATCH_UPDATE", ["destructiveHint", "updateHint"], "delete"),
        ("STRIPE_CANCEL_SUBSCRIPTION", [], "delete"),
        ("STRIPE_CREATE_REFUND", ["createHint"], "money"),  # money beats a write
        ("STRIPE_PAYOUT", [], "money"),
        ("STRIPE_LIST_REFUNDS", [], "read"),  # reading money records is a read
        ("SHEETS_EXECUTE_SQL", ["mcpIgnore"], "skip"),
        ("STRIPE_UPDATE_BALANCE", ["readOnlyHint"], "money"),  # a read-only hint never beats a money word
        ("STRIPE_GET_AND_CAPTURE", ["readOnlyHint"], "money"),  # starts like a read, but captures
        ("GMAIL_FETCH_AND_FORWARD", ["readOnlyHint"], "write"),  # starts like a read, but forwards
        ("STRIPE_RETRIEVE_INVOICE", [], "read"),
        ("SHOP_GRAPH_QL_ORDERS", ["readOnlyHint", "GraphQL"], "skip"),  # free-form query
        ("DOCS_SHARE_FILE", ["updateHint"], "skip"),  # changes who can reach data
        ("MAIL_CREATE_SEND_AS", ["createHint"], "skip"),
        ("DRIVE_LIST_PERMISSIONS", ["readOnlyHint"], "read"),  # reading who has access is a read
    ],
)
def test_classify_sorts_by_hints_then_names(slug, tags, expected):
    toolkit = slug.split("_")[0].lower()
    assert ic.classify(_tool(slug, tags), toolkit, None)[0] == expected


def test_classify_lets_a_reviewed_override_win_and_skips_deprecated_tools():
    tool = _tool("SHEETS_BATCH_UPDATE", ["destructiveHint"])
    assert ic.classify(tool, "sheets", {"action_class": "write", "why": "asks first"}) == (
        "write",
        "asks first",
    )
    assert ic.classify(tool, "sheets", {"skip": "not needed"}) == ("skip", "not needed")
    assert ic.classify({**tool, "is_deprecated": True}, "sheets", None)[0] == "skip"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Create Chart in Google Sheets", "create_chart"),
        ("Create a Google Sheet", "create_google_sheet"),
        ("Upsert Rows (Smart Update/Insert)", "upsert_rows"),
        ("", "values_get"),  # no display name: from the slug
    ],
)
def test_tool_id_is_short_and_readable(name, expected):
    assert ic.tool_id(name, "SHEETS_VALUES_GET", "sheets", set(), "Google Sheets") == expected


def test_tool_id_never_reuses_a_taken_id():
    assert ic.tool_id("Format cell", "X", "sheets", {"format_cell", "format_cell_2"}) == "format_cell_3"


def test_input_schema_keeps_descriptions_and_refuses_undeclared_arguments():
    schema = ic.input_schema(_tool("SHEETS_GET_INFO"))
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["spreadsheet_id"]
    assert schema["properties"]["spreadsheet_id"] == {
        "type": "string",
        "description": "The id.",
        "maxLength": 200,
    }
    assert schema["properties"]["rows"]["items"] == {"type": "string"}


def test_a_schema_the_contract_test_cannot_check_is_skipped():
    tool = _tool("SHEETS_GET_INFO", ["readOnlyHint"])
    tool["input_parameters"] = {"type": "object", "properties": {"x": {"const": True}}}
    [p] = ic.plan("sheets", [tool], [], {}, "sheets")
    assert p.action_class == "skip" and "const" in p.why and p.entry is None


def test_plan_keeps_existing_tools_and_imports_neither_blocked_nor_meta_tools():
    existing = [{"id": "read_rows", "slug": "SHEETS_BATCH_GET"}]
    tools = [
        _tool("SHEETS_BATCH_GET", ["readOnlyHint"]),
        _tool("SHEETS_DELETE_SHEET", name="Delete sheet"),
        _tool("COMPOSIO_MULTI_EXECUTE_TOOL"),
        _tool("SHEETS_VALUES_UPDATE", ["updateHint"], name="Update values", description="Sets   values."),
    ]
    plans = {p.slug: p for p in ic.plan("sheets", tools, existing, {}, "sheets")}
    assert set(plans) == {"SHEETS_BATCH_GET", "SHEETS_DELETE_SHEET", "SHEETS_VALUES_UPDATE"}
    assert plans["SHEETS_BATCH_GET"].action_class == "kept" and plans["SHEETS_BATCH_GET"].entry is None
    assert plans["SHEETS_DELETE_SHEET"].entry is None
    entry = plans["SHEETS_VALUES_UPDATE"].entry
    assert entry["id"] == "update_values" and entry["capability"] == "sheets.write"
    assert entry["version"] == "20261001_00" and entry["description"] == "Sets values."


def test_plan_follows_the_reviewed_config():
    tools = [
        _tool("PAY_LIST_CUSTOMERS", ["important", "readOnlyHint"]),
        _tool("PAY_CREATE_CUSTOMER", ["important", "createHint"]),
        _tool("PAY_CREATE_SUBSCRIPTION", ["important", "createHint"]),
        _tool("PAY_LIST_PAYOUTS", ["readOnlyHint"]),  # not important, but included
        _tool("PAY_LIST_FILES", ["readOnlyHint"]),  # neither: not considered
        _tool("PAY_SEND_NOTE", ["important"], name="Send note"),
    ]
    config = {
        "only_tagged": "important",
        "include": ["PAY_LIST_PAYOUTS"],
        "writes_are_money": True,
        "ids_from": "slug",
        "tools": {
            "PAY_CREATE_CUSTOMER": {"action_class": "write", "why": "charges nothing"},
            "PAY_SEND_NOTE": {"action_class": "write", "capability": "payments.send"},
        },
    }
    plans = {p.slug: p for p in ic.plan("pay", tools, [], config, "payments")}
    assert "PAY_LIST_FILES" not in plans
    assert plans["PAY_LIST_PAYOUTS"].action_class == "read"
    assert plans["PAY_CREATE_CUSTOMER"].entry["action_class"] == "write"  # reviewed
    assert (
        plans["PAY_CREATE_SUBSCRIPTION"].action_class == "money"
        and not plans["PAY_CREATE_SUBSCRIPTION"].entry
    )
    assert plans["PAY_SEND_NOTE"].entry["capability"] == "payments.send"
    assert plans["PAY_SEND_NOTE"].tool_id == "send_note"  # from the slug, not the display name


def test_plan_refuses_an_override_id_already_in_use():
    existing = [{"id": "read_rows", "slug": "SHEETS_BATCH_GET"}]
    config = {"tools": {"SHEETS_VALUES_GET": {"id": "read_rows"}}}
    with pytest.raises(ValueError, match="already used"):
        ic.plan("sheets", [_tool("SHEETS_VALUES_GET")], existing, config, "s")


def test_with_tools_adds_after_the_last_tool_and_leaves_the_rest_alone():
    text = (
        "kind: connector\nkey: sheets\napp: Sheets\ntoolkit: sheets\n\ntools:\n"
        "  - id: read_rows  # hand-written\n    slug: SHEETS_BATCH_GET\n\n"
        "defaults: {read: permit, write: require_approval, delete: deny, money: deny}\n"
    )
    entry = {"id": "update_values", "slug": "SHEETS_VALUES_UPDATE", "version": "20261001_00"}
    out = ic.with_tools(text, [entry], "sheets")
    assert out.startswith(text[: text.find("\n\ndefaults:")])
    assert "# hand-written" in out
    assert out.endswith("defaults: {read: permit, write: require_approval, delete: deny, money: deny}\n")
    body = yaml.safe_load(out)
    assert [t["id"] for t in body["tools"]] == ["read_rows", "update_values"]
    assert body["tools"][1]["version"] == "20261001_00"  # stays text, not the number 2026100100


def test_sandbox_response_is_an_example_of_the_output_data():
    tool = {
        "output_parameters": {
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "spreadsheetId": {"type": "string", "examples": ["1abc"]},
                        "updatedRows": {"type": "integer"},
                        "values": {
                            "type": "array",
                            "items": {"anyOf": [{"type": "null"}, {"type": "string"}]},
                        },
                        "mode": {"type": "string", "enum": ["ROWS", "COLUMNS"]},
                    },
                }
            }
        }
    }
    assert ic.sandbox_response(tool) == {
        "spreadsheetId": "1abc",
        "updatedRows": 1,
        "values": ["sample"],
        "mode": "ROWS",
    }
    assert ic.sandbox_response({}) == {"result": None}


def test_sandbox_response_follows_shared_definitions():
    tool = {
        "output_parameters": {
            "$defs": {"Values": {"type": "object", "properties": {"range": {"type": "string"}}}},
            "properties": {"data": {"$ref": "#/$defs/Values"}},
        }
    }
    assert ic.sandbox_response(tool) == {"range": "sample"}


def test_input_schema_refuses_undeclared_arguments_at_every_depth():
    tool = _tool("SHEETS_ADD")
    tool["input_parameters"] = {
        "type": "object",
        "properties": {"row": {"type": "object", "properties": {"a": {"type": "string"}}}},
    }
    assert ic.input_schema(tool)["properties"]["row"]["additionalProperties"] is False


def test_a_constraint_the_contract_test_does_not_know_is_skipped():
    tool = _tool("SHEETS_GET_INFO", ["readOnlyHint"])
    tool["input_parameters"] = {
        "type": "object",
        "properties": {"x": {"type": "string", "contentEncoding": "x"}},
    }
    [p] = ic.plan("sheets", [tool], [], {}, "sheets")
    assert p.action_class == "skip" and "contentEncoding" in p.why


def test_a_reviewed_override_drops_and_narrows_arguments():
    tool = _tool("SHEETS_GET_INFO", ["readOnlyHint"])
    override = {"drop": ["rows"], "restrict": {"spreadsheet_id": {"enum": ["a"]}}}
    [p] = ic.plan("sheets", [tool], [], {"tools": {"SHEETS_GET_INFO": override}}, "sheets")
    props = p.entry["input_schema"]["properties"]
    assert set(props) == {"spreadsheet_id"} and props["spreadsheet_id"]["enum"] == ["a"]
    items = ic.narrowed(SCHEMA, {"restrict": {"rows.items": {"pattern": "^x$"}}}, "S")
    assert items["properties"]["rows"]["items"]["pattern"] == "^x$"
    assert "pattern" not in SCHEMA["properties"]["rows"]["items"]  # the original is left alone


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"drop": ["spreadsheet_id"]}, "requires"),
        ({"drop": ["nope"]}, "no argument"),
        ({"restrict": {"nope.items": {"enum": ["a"]}}}, "no argument"),
    ],
)
def test_narrowing_refuses_what_it_cannot_do(override, message):
    with pytest.raises(ValueError, match=message):
        ic.narrowed(SCHEMA, override, "S")


def test_a_generated_id_never_takes_one_a_later_action_was_given():
    tools = [_tool("SHEETS_ADD_SHEET", name="Add sheet"), _tool("SHEETS_NEW_TAB", name="New tab")]
    config = {"tools": {"SHEETS_NEW_TAB": {"id": "add_sheet"}}}
    plans = {p.slug: p.tool_id for p in ic.plan("sheets", tools, [], config, "sheets")}
    assert plans == {"SHEETS_ADD_SHEET": "add_sheet_2", "SHEETS_NEW_TAB": "add_sheet"}


def test_a_dropped_argument_the_description_still_offers_needs_a_reviewed_description():
    tool = _tool("SHEETS_GET_INFO", description="Reads info; pass rows to limit it.")
    config = {"tools": {"SHEETS_GET_INFO": {"drop": ["rows"]}}}
    with pytest.raises(ValueError, match="still offers"):
        ic.plan("sheets", [tool], [], config, "sheets")
    config["tools"]["SHEETS_GET_INFO"]["description"] = "Reads info."
    [p] = ic.plan("sheets", [tool], [], config, "sheets")
    assert p.entry["description"] == "Reads info."
