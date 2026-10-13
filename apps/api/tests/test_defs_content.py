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

SLUG = "order-payment-reconciliation"
CEL = celpy.Environment()


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
        "input": {"since": "2026-10-06", "until": "2026-10-12"},
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
    assert {a.key for a in bundle.of("agent")} == {"retail-agent", "finance-agent", "ops-agent"}


def test_taxonomy_and_models(bundle):
    taxonomy = bundle.get("taxonomy", "default").body
    assert [f["id"] for f in taxonomy["functions"]] == [
        "finance-ops",
        "customer-ops",
        "fulfillment",
        "merchandising",
        "operations",
    ]
    assert [i["id"] for i in taxonomy["industries"]] == ["retail-commerce", "manufacturing", "media-content"]
    profiles = bundle.get("models", "default").body["profiles"]
    assert profiles["reasoning"]["envs"]["test"] == {"provider": "fake", "model": "fake-reasoning"}
    assert profiles["reasoning"]["envs"]["prod"] == {"provider": "provider", "model": "gemini-2.5-pro"}
    assert profiles["fast"]["envs"]["prod"] == {"provider": "provider", "model": "gemini-2.5-flash"}


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


def test_connector_args_are_valid_for_the_real_tools(bundle):
    wf = {n["id"]: n for n in bundle.get("workflow", SLUG).body["nodes"]}
    state = sample_state()
    state["nodes"]["report"] = {"output": report_output()}
    for node_id in ("orders", "payments", "write"):
        cfg = wf[node_id]["config"]
        conn, _, tool_id = cfg["tool"].partition(".")
        tool = next(t for t in bundle.get("connector", conn).body["tools"] if t["id"] == tool_id)
        known = set(tool["input_schema"]["properties"])
        assert set(cfg["args"]) <= known, (node_id, set(cfg["args"]) - known)
        assert set(tool["input_schema"].get("required", [])) <= set(cfg["args"]), node_id


def test_schemas_accept_sample_outputs(bundle):
    def check(schema_key: str, value: dict) -> None:
        schema = bundle.get("schema", f"{SLUG}/{schema_key}").body
        Draft202012Validator(schema).validate(value)

    check("input", {"since": "2026-10-06", "until": "2026-10-12"})
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
        assert body["version"] == "1.0.0"
        assert body["runtime"]["adapter"] == "hosted"
        assert body["runtime"]["model_profile"] == "reasoning"
        assert body["runtime"]["max_turns"] == 6
        assert body["data_processing"]["supported_regions"] == ["asia-south1"]
        assert body["data_processing"]["data_classes"] == ["CONFIDENTIAL"]
        assert body["data_processing"]["retention_policy_ref"] == "retention/30d"
        first_line = agent.files[body["runtime"]["instructions"]].strip().splitlines()[0]
        assert first_line.lower().startswith(("you are", "your role")), first_line
    tools = {a.key: a.body["runtime"].get("tools", []) for a in bundle.of("agent")}
    assert tools == {"retail-agent": ["shopify.list_orders"], "finance-agent": [], "ops-agent": []}


def test_no_vendor_names_in_agent_prose(bundle):
    pattern = re.compile(r"model|provider|openai|gemini|composio", re.IGNORECASE)
    for agent in bundle.of("agent"):
        for path, text in agent.files.items():
            assert not pattern.search(text), f"{agent.key}/{path}"


def test_connector_defaults_and_classes(bundle):
    expected = {
        "shopify": ("list_orders", "read", "orders.read"),
        "stripe": ("list_charges", "read", "payments.read"),
        "googlesheets": ("append_rows", "write", "sheets.write"),
    }
    for key, (tool_id, action_class, capability) in expected.items():
        body = bundle.get("connector", key).body
        assert body["defaults"] == {
            "read": "permit",
            "write": "require_approval",
            "delete": "deny",
            "money": "deny",
        }
        (tool,) = body["tools"]
        assert (tool["id"], tool["action_class"], tool["capability"]) == (tool_id, action_class, capability)
        assert tool["slug"].isupper() and tool["slug"].startswith(body["toolkit"].upper())


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
