"""The real definitions bundle (demo-app/definitions) is valid and behaves as the product expects."""

import json
import re
from functools import cache
from pathlib import Path

import celpy
import pytest
from jsonschema import Draft202012Validator

from app import settings
from app.defs.loader import load_bundle
from app.defs.model import Bundle
from app.defs.validate import validate_bundle
from app.runtime import cel as runtime_cel

SLUG = "order-payment-reconciliation"
CEL = celpy.Environment()
SANDBOX_SHEET = "sandbox-reconciliation-sheet-00000001"  # the input schema's default spreadsheet_id
SEED_PACKS = {SLUG, "refund-triage", "overdue-invoice-follow-up"}
SEED_AGENTS = {
    "retail-agent",
    "finance-agent",
    "ops-agent",
    "collections-agent",
    "refunds-agent",
    "writer-agent",
}
OLDER_AGENTS = {"retail-agent", "finance-agent", "ops-agent"}  # version 1.1.0; every later agent is 1.0.0
FAST_AGENTS = {"writer-agent", "lead-agent", "meeting-agent"}  # model_profile fast, max_turns 4


@pytest.fixture(scope="module")
def bundle() -> Bundle:
    return load_bundle(settings.defs_dir())


@cache
def sandbox(app: str, tool: str) -> dict:
    path = settings.defs_dir() / "connectors" / "sandbox" / app / f"{tool}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def cel(expr: str, state: dict):
    return CEL.program(CEL.compile(expr)).evaluate(celpy.json_to_cel(state))


def sample_state(match_output: dict | None = None, *, orders: dict | None = None) -> dict:
    return {
        "input": {"since": "2026-10-06", "until": "2026-10-12", "spreadsheet_id": SANDBOX_SHEET},
        "memory": [],
        "nodes": {
            "orders": {"output": orders if orders is not None else sandbox("shopify", "list_orders")},
            "payments": {"output": sandbox("stripe", "list_charges")},
            **({"match": {"output": match_output}} if match_output is not None else {}),
        },
    }


def decide(rules: dict, state: dict) -> dict:
    """Evaluate decision rules in order; first match wins, otherwise the default."""
    for rule in rules["rules"]:
        if cel(rule["when"].removeprefix("="), state):
            return rule
    return rules["default"]


def mismatch(order_id: str, kind: str, diff: int) -> dict:
    return {
        "order_id": order_id,
        "charge_id": None,
        "kind": kind,
        "date": "2026-10-09",
        "amount_minor": 6750,
        "amount_diff_minor": diff,
        "currency": "USD",
        "explanation": "Sample mismatch.",
    }


def match_output(mismatches: list[dict]) -> dict:
    return {
        "matched": [
            {
                "order_id": "#1001",
                "charge_id": "ch_1",
                "date": "2026-10-06",
                "amount_minor": 4500,
                "currency": "USD",
            }
        ],
        "mismatches": mismatches,
        "totals": {
            "orders_count": 12,
            "charges_count": 11,
            "matched_count": 1,
            "mismatch_count": len(mismatches),
            "orders_total_minor": 100,
            "charges_total_minor": 100,
            "currency": "USD",
        },
    }


def test_real_bundle_validates(bundle):
    assert [str(e) for e in validate_bundle(bundle)] == []


def test_pack_lists_connectors_and_agents(bundle):
    pack = bundle.get("pack", SLUG).body
    assert pack["function"] == "finance-ops"
    assert pack["industries"] == ["retail-commerce", "manufacturing"]
    assert pack["connectors"] == ["shopify", "stripe", "googlesheets"]
    assert pack["agents"] == ["finance-agent", "ops-agent"]
    assert {a.key for a in bundle.of("agent")} >= SEED_AGENTS


def test_taxonomy_and_models(bundle):
    taxonomy = bundle.get("taxonomy", "default").body
    assert [f["id"] for f in taxonomy["functions"]] == [
        "finance-ops",
        "customer-ops",
        "fulfillment",
        "merchandising",
        "operations",
        "sales-ops",
    ]
    assert [i["id"] for i in taxonomy["industries"]] == [
        "retail-commerce",
        "manufacturing",
        "media-content",
        "professional-services",
    ]
    profiles = bundle.get("models", "default").body["profiles"]
    assert profiles["reasoning"]["envs"]["test"] == {"provider": "fake", "model": "fake-reasoning"}
    assert profiles["reasoning"]["envs"]["prod"] == {"provider": "anthropic", "model": "claude-opus-5-5"}
    assert profiles["fast"]["envs"]["prod"] == {"provider": "anthropic", "model": "claude-haiku-5-5"}


def test_sandbox_counts_and_scenario():
    orders = sandbox("shopify", "list_orders")["orders"]
    charges = sandbox("stripe", "list_charges")["data"]
    assert len(orders) == 12
    assert len(charges) == 11
    assert {o["currency"] for o in orders} == {"USD"}
    assert {o["name"] for o in orders} == {f"#{n}" for n in range(1001, 1013)}
    assert {o["created_at"][:10] for o in orders} >= {"2026-10-06", "2026-10-12"}
    assert all("2026-10-06" <= o["created_at"][:10] <= "2026-10-12" for o in orders)
    totals = {o["name"]: round(float(o["total_price"]) * 100) for o in orders}
    by_order = {c["metadata"]["order_id"]: c for c in charges if c["metadata"].get("order_id")}
    assert "#1007" not in by_order
    assert totals["#1004"] - by_order["#1004"]["amount"] == 290
    for name, charge in by_order.items():
        if name != "#1004":
            assert charge["amount"] == totals[name], name
    # one charge carries no order reference, so it can only be matched by amount and date
    assert sum(1 for c in charges if not c["metadata"].get("order_id")) == 1
    assert sandbox("googlesheets", "append_rows")["updates"]["updatedRows"] >= 1


def test_decision_rules_route_by_outcome(bundle):
    rules = bundle.get("decision_rules", "recon-exceptions").body
    two = decide(
        rules,
        sample_state(
            match_output(
                [mismatch("#1004", "amount_mismatch", -290), mismatch("#1007", "missing_payment", -6750)]
            )
        ),
    )
    assert (two["verdict"], two["route"], two["reason_code"]) == (
        "HUMAN_REVIEW",
        "human_review",
        "MISMATCHES_FOUND",
    )
    none = decide(rules, sample_state(match_output([])))
    assert (none["verdict"], none["route"], none["reason_code"]) == ("APPROVED", "approved", "ALL_MATCHED")
    blocked = decide(rules, sample_state(match_output([]), orders={"orders": []}))
    assert (blocked["verdict"], blocked["route"], blocked["reason_code"]) == (
        "BLOCKED",
        "blocked",
        "DATA_MISSING",
    )
    no_charges = sample_state(match_output([]))
    no_charges["nodes"]["payments"]["output"] = {"object": "list", "data": [], "has_more": False}
    assert decide(rules, no_charges)["verdict"] == "BLOCKED"


def test_decision_routes_are_workflow_routes(bundle):
    rules = bundle.get("decision_rules", "recon-exceptions").body
    routes = {r["route"] for r in rules["rules"]} | {rules["default"]["route"]}
    check = next(n for n in bundle.get("workflow", SLUG).body["nodes"] if n["id"] == "check")
    assert routes == set(check["routes"])


def test_workflow_graph(bundle):
    wf = bundle.get("workflow", SLUG).body
    nodes = {n["id"]: n for n in wf["nodes"]}
    assert wf["entry_node_id"] == "start"
    assert nodes["check"]["routes"] == {"approved": "report", "human_review": "review", "blocked": "failed"}
    assert nodes["review"]["routes"] == {"resolved": "report", "rejected": "failed", "timeout": "failed"}
    assert nodes["approve_write"]["routes"] == {"granted": "write", "denied": "failed", "timeout": "failed"}
    assert nodes["write"]["routes"] == {"ok": "verify", "denied": "failed", "error": "failed"}
    assert nodes["verify"]["routes"] == {"pass": "done", "fail": "failed"}
    assert nodes["done"]["config"]["status"] == "COMPLETED"
    assert nodes["failed"]["config"]["status"] == "FAILED"


def _cel_strings(value):
    if isinstance(value, str) and value.startswith("="):
        yield value[1:]
    elif isinstance(value, dict):
        for v in value.values():
            yield from _cel_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _cel_strings(v)


def report_output() -> dict:
    return {
        "summary": "12 orders checked, 10 matched, 2 need attention.",
        "rows": [
            ["2026-10-09", "#1007", "missing_payment", "67.50", "resolved", "Refunded outside the store."]
        ],
        "totals": {
            "orders_count": 12,
            "matched_count": 10,
            "mismatch_count": 2,
            "net_difference_minor": -7040,
            "currency": "USD",
        },
    }


@pytest.mark.parametrize("with_review", [False, True])
def test_every_node_expression_evaluates(bundle, with_review):
    """Config expressions only read paths that exist in the state the runtime will have at that node."""
    state = sample_state(match_output([mismatch("#1007", "missing_payment", -6750)]))
    state["nodes"]["report"] = {"output": report_output()}
    if with_review:
        state["nodes"]["review"] = {"output": {"resolutions": []}}
    for node in bundle.get("workflow", SLUG).body["nodes"]:
        for expr in _cel_strings(node["config"]):
            cel(expr, state)  # raises when a path or function is wrong


def _connector_nodes(bundle) -> list[tuple[str, dict]]:
    return [
        (wf.key, node)
        for wf in bundle.of("workflow")
        for node in wf.body["nodes"]
        if node["type"] == "connector"
    ]


def test_every_pack_calls_connectors(bundle):
    packs = {key for key, _ in _connector_nodes(bundle)}
    assert {SLUG, "refund-triage", "overdue-invoice-follow-up"} <= packs


COMPOSIO_FIXTURES = Path(__file__).parent / "fixtures" / "composio"


def _sandbox_sheet(bundle) -> str:
    """The spreadsheet id a reconciliation run gets when its input names none (the input schema default)."""
    return bundle.get("schema", f"{SLUG}/input").body["properties"]["spreadsheet_id"]["default"]


def test_connector_args_are_valid_for_the_real_tools(bundle):
    """Every pack's connector node resolves to arguments its tool's input_schema accepts, as the gateway
    checks them before any driver runs (so a CEL timestamp must already be an ISO string), and that the
    tool's recorded Composio schema accepts too."""
    state = sample_state()
    state["input"] = {"since": "2026-10-06", "until": "2026-10-12", "spreadsheet_id": _sandbox_sheet(bundle)}
    state["nodes"]["report"] = {"output": report_output()}
    state["item"] = {"to": "ana@example.com", "subject": "Your refund", "body": "We refunded order #1007."}
    for pack, node in _connector_nodes(bundle):
        if pack not in SEED_PACKS:
            continue
        cfg = node["config"]
        conn, _, tool_id = cfg["tool"].partition(".")
        tool = next(t for t in bundle.get("connector", conn).body["tools"] if t["id"] == tool_id)
        args = runtime_cel.resolve(cfg.get("args") or {}, state)
        errors = [e.message for e in Draft202012Validator(tool["input_schema"]).iter_errors(args)]
        assert errors == [], (pack, node["id"], errors)
        recorded = json.loads((COMPOSIO_FIXTURES / f"{tool['slug']}.json").read_text(encoding="utf-8"))
        theirs = recorded["input_parameters"]
        errors = [e.message for e in Draft202012Validator(theirs).iter_errors(args)]
        assert errors == [], (pack, node["id"], "Composio", errors)


def test_the_reconciliation_writes_to_the_sheet_its_run_names(bundle):
    write = next(n for k, n in _connector_nodes(bundle) if k == SLUG and n["id"] == "write")
    assert write["config"]["args"]["spreadsheetId"] == "=input.spreadsheet_id"
    schema = bundle.get("schema", f"{SLUG}/input").body
    sheets = bundle.get("connector", "googlesheets").body["tools"][0]["input_schema"]["properties"]
    ours = schema["properties"]["spreadsheet_id"]
    assert "spreadsheet_id" in schema["required"]
    assert (ours["minLength"], ours["pattern"]) == (30, sheets["spreadsheetId"]["pattern"])
    assert sheets["spreadsheetId"]["minLength"] == 30
    validator = Draft202012Validator(schema)
    base = {"since": "2026-10-06", "until": "2026-10-12"}
    assert not list(validator.iter_errors({**base, "spreadsheet_id": _sandbox_sheet(bundle)}))
    assert list(validator.iter_errors({**base, "spreadsheet_id": "demo-reconciliation-sheet"}))
    assert list(validator.iter_errors({**base, "spreadsheet_id": "has spaces " * 4}))


def test_refund_triage_sends_its_order_window_start_as_an_iso_timestamp(bundle):
    node = next(n for k, n in _connector_nodes(bundle) if k == "refund-triage" and n["id"] == "orders")
    args = runtime_cel.resolve(node["config"]["args"], {"input": {"until": "2026-10-12"}})
    assert args["created_at_min"] == "2026-08-13T00:00:00Z"
    assert args["created_at_max"] == "2026-10-12T23:59:59Z"


def test_schemas_accept_sample_outputs(bundle):
    def check(schema_key: str, value: dict) -> None:
        schema = bundle.get("schema", f"{SLUG}/{schema_key}").body
        Draft202012Validator(schema).validate(value)

    check("input", {"since": "2026-10-06", "until": "2026-10-12", "spreadsheet_id": _sandbox_sheet(bundle)})
    check("match", match_output([mismatch("#1007", "missing_payment", -6750)]))
    check("match", match_output([]))
    check("report", report_output())
    check("output", report_output())
    schema = bundle.get("schema", f"{SLUG}/match").body
    bad = match_output([mismatch("#1007", "not_a_kind", -1)])
    assert list(Draft202012Validator(schema).iter_errors(bad))


def test_agents_follow_conventions(bundle):
    for agent in bundle.of("agent"):
        body = agent.body
        assert body["publisher_id"] == "new-machines-labs"
        assert body["version"] == ("1.1.0" if agent.key in OLDER_AGENTS else "1.0.0")
        assert body["runtime"]["adapter"] == "google_adk"
        fast = agent.key in FAST_AGENTS
        assert body["runtime"]["model_profile"] == ("fast" if fast else "reasoning")
        assert body["runtime"]["max_turns"] == (4 if fast else 6)
        assert body["data_processing"]["supported_regions"] == ["asia-south1"]
        assert body["data_processing"]["data_classes"] == ["CONFIDENTIAL"]
        assert body["data_processing"]["retention_policy_ref"] == "retention/30d"
        first_line = agent.files[body["runtime"]["instructions"]].strip().splitlines()[0]
        assert first_line.lower().startswith(("you are", "your role")), first_line
    tools = {a.key: a.body["runtime"].get("tools", []) for a in bundle.of("agent")}
    assert tools.pop("retail-agent") == ["shopify.list_orders"]
    assert all(t == [] for t in tools.values()), tools


def test_no_vendor_names_in_agent_prose(bundle):
    pattern = re.compile(r"claude|anthropic|openai|gemini|composio", re.IGNORECASE)
    for agent in bundle.of("agent"):
        for path, text in agent.files.items():
            assert not pattern.search(text), f"{agent.key}/{path}"


def test_agents_that_write_review_records_keep_personal_data_out_of_notes(bundle):
    line = "Never include email addresses, phone numbers or customer message text in a `note` or `flag`."
    for key in ("collections-agent", "refunds-agent", "writer-agent", "support-agent", "expense-agent"):
        agent = bundle.get("agent", key)
        skills = [agent.files[s] for s in agent.body["runtime"]["skills"]]
        assert any(line in text for text in skills), key


def test_the_refund_memory_matches_the_find_order_rule(bundle):
    seeds = " ".join(
        item
        for space in ("customer-accounts", "retail-commerce")
        for item in bundle.get("memory_space", space).body["seed_items"]
    )
    assert "refunded set to true" in seeds and "amount_refunded" in seeds
    assert "Refunds appear as negative charges" not in seeds
    assert 'whole word "opened" or "used"' in seeds and '"unused" does not count' in seeds


def test_connector_defaults_and_classes(bundle):
    expected = {
        "shopify": [("list_orders", "read", "orders.read", "SHOPIFY_GET_ORDERS_WITH_FILTERS")],
        "stripe": [
            ("list_charges", "read", "payments.read", "STRIPE_LIST_CHARGES"),
            ("list_invoices", "read", "invoices.read", "STRIPE_LIST_INVOICES"),
        ],
        "googlesheets": [
            ("append_rows", "write", "sheets.write", "GOOGLESHEETS_SPREADSHEETS_VALUES_APPEND"),
            ("read_rows", "read", "sheets.read", "GOOGLESHEETS_BATCH_GET"),
        ],
        "gmail": [
            ("list_threads", "read", "mail.read", "GMAIL_FETCH_EMAILS"),
            ("create_draft", "write", "mail.write", "GMAIL_CREATE_EMAIL_DRAFT"),
            ("send_email", "write", "mail.send", "GMAIL_SEND_EMAIL"),
        ],
        "googlecalendar": [("list_events", "read", "calendar.read", "GOOGLECALENDAR_EVENTS_LIST")],
        "custom-business-app": [
            ("list_store_orders", "read", "business.read", "CUSTOM_BUSINESS_APP_LIST_STORE_ORDERS"),
            ("list_store_payments", "read", "business.read", "CUSTOM_BUSINESS_APP_LIST_STORE_PAYMENTS"),
            ("list_sales_orders", "read", "business.read", "CUSTOM_BUSINESS_APP_LIST_SALES_ORDERS"),
            ("list_customers", "read", "business.read", "CUSTOM_BUSINESS_APP_LIST_CUSTOMERS"),
            ("list_customer_payments", "read", "business.read", "CUSTOM_BUSINESS_APP_LIST_CUSTOMER_PAYMENTS"),
            ("list_served_orders", "read", "business.read", "CUSTOM_BUSINESS_APP_LIST_SERVED_ORDERS"),
            ("list_sales", "read", "business.read", "CUSTOM_BUSINESS_APP_LIST_SALES"),
            ("add_ledger_note", "write", "business.write", "CUSTOM_BUSINESS_APP_ADD_LEDGER_NOTE"),
            ("add_warehouse_note", "write", "business.write", "CUSTOM_BUSINESS_APP_ADD_WAREHOUSE_NOTE"),
        ],
    }
    assert {c.key for c in bundle.of("connector")} == set(expected)
    for key, tools in expected.items():
        body = bundle.get("connector", key).body
        assert body["defaults"] == {
            "read": "permit",
            "write": "require_approval",
            "delete": "deny",
            "money": "deny",
        }
        got = [(t["id"], t["action_class"], t["capability"], t["slug"]) for t in body["tools"]]
        assert got == tools
        assert all(t["slug"].startswith(body["toolkit"].upper()) for t in body["tools"])


def test_every_connector_tool_has_a_shared_sandbox_response(bundle):
    root = settings.defs_dir() / "connectors" / "sandbox"
    for connector in bundle.of("connector"):
        for tool in connector.body["tools"]:
            path = root / connector.key / f"{tool['id']}.json"
            assert path.is_file(), (connector.key, tool["id"])
            json.loads(path.read_text(encoding="utf-8"))


def test_contract(bundle):
    c = bundle.get("contract", SLUG).body
    assert c["org_id"] == "{org}"
    assert c["capability"] == "reconciliation.order_payment"
    assert c["budget"] == {"currency": "USD", "maximum_minor": 2500, "human_budget_minor": 2000}
    assert c["limits"]["max_attempts"] == 3
    assert c["limits"]["deadline_s"] == 172800
    assert c["authorization"]["tool_capabilities"] == ["orders.read", "payments.read", "sheets.write"]
    assert c["routes"] == {
        "success": "done",
        "failure": "failed",
        "timeout": "failed",
        "human_review": "review",
    }
    assert c["acceptance"] == {
        "verification_ruleset_ref": f"{SLUG}/output",
        "buyer_acceptance_required": False,
    }


def test_files_are_lf_only():
    root = Path(settings.defs_dir())
    bad = [str(p) for p in root.rglob("*") if p.is_file() and b"\r" in p.read_bytes()]
    assert bad == []
