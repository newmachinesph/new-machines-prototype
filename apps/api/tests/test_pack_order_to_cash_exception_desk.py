"""Order-to-Cash Exception Desk: definitions, the planted sandbox cases across the business app's sections,
the fake triage, writer and report agents, the decision, the one approval, and a sandbox run.

The pack's sandbox fixtures (sandbox/custom-business-app/<tool>.json) are generated from the anonymised export
(scripts/demo_data), so the checks read ids, dates and amounts from the fixture files; only the planted
cases' amounts (DEMO_CASES.md) and the sellers are fixed."""

from datetime import date

from jsonschema import Draft202012Validator

from app.models.runs import Run
from app.runtime import cel as runtime_cel
from app.runtime import decisions, fakes
from app.runtime.fakes.o2c import KINDS
from tests import sample_packs as sp
from tests.test_workflow import _entries, _run_row, runtime_env  # noqa: F401

PACK = "order-to-cash-exception-desk"
COMPANY = "Kalumpang Demo Supply Co."
AS_OF = "2026-10-16"
INPUT = {"since": "2026-09-16", "until": AS_OF, "company_name": COMPANY, "grace_days": 7, "max_messages": 3}
STOPS = [("approve", sp.APPROVAL)]
SELLERS = {
    "Kristoffer M. Nunez": "kristoffer.m.nunez@example.com",
    "Yvette D. Tolentino": "yvette.d.tolentino@example.com",
}
# The planted cases (scripts/demo_data/DEMO_CASES.md): id -> (kind, amount in centavos).
PLANTED = {
    "DEMO-PNS-1": ("paid_not_shipped", 1860000),
    "DEMO-PNS-2": ("paid_not_shipped", 744000),
    "DEMO-PNS-3": ("paid_not_shipped", 2592000),
    "DEMO-SNP-1": ("shipped_not_paid", 4025280),
    "DEMO-SNP-2": ("shipped_not_paid", 1248000),
    "DEMO-SNP-3": ("shipped_not_paid", 315000),
    "DEMO-PPC-1": ("payment_pending_confirmation", 1560000),
    "DEMO-DSP-1": ("disputed", 2880000),
}
ACTIONS = {
    "shipped_not_paid": "draft_collection_message",
    "payment_pending_confirmation": "confirm_payment",
    "disputed": "escalate_finance",
}
READS = [
    "custom-business-app.list_store_orders",
    "custom-business-app.list_store_payments",
    "custom-business-app.list_sales_orders",
    "custom-business-app.list_customers",
    "custom-business-app.list_served_orders",
    "custom-business-app.list_sales",
]


def _inputs() -> dict:
    return {
        "orders": sp.sandbox(PACK, "custom-business-app", "list_store_orders"),
        "payments": sp.sandbox(PACK, "custom-business-app", "list_store_payments"),
        "sales_orders": sp.sandbox(PACK, "custom-business-app", "list_sales_orders"),
        "customers": sp.sandbox(PACK, "custom-business-app", "list_customers"),
        "served_orders": sp.sandbox(PACK, "custom-business-app", "list_served_orders"),
        "sales": sp.sandbox(PACK, "custom-business-app", "list_sales"),
        "as_of": AS_OF,
        "grace_days": 7,
        "rules": [],
    }


def _triage(inputs: dict | None = None, **changes) -> dict:
    return fakes.agent_script("o2c-triage-agent")({**(inputs or _inputs()), **changes})


def _to_draft(triage: dict) -> list[dict]:
    return [e for e in triage["exceptions"] if e["recommended_action"] == "draft_collection_message"]


def _drafts(triage: dict, max_messages: int = 3) -> dict:
    request = {
        "exceptions": _to_draft(triage),
        "max_messages": max_messages,
        "company_name": COMPANY,
        "rules": [],
    }
    assert sp.schema_errors(f"{PACK}/draft-request", request) == []
    return fakes.agent_script("collections-writer")(request)


def _by_action(triage: dict, *actions: str) -> list[dict]:
    return [e for e in triage["exceptions"] if e["recommended_action"] in actions]


def _state(triage: dict | None = None, drafts: dict | None = None, *, granted: bool = True) -> dict:
    triage = triage or _triage()
    drafts = drafts or _drafts(triage)
    inputs = _inputs()
    decision = {"decision": "granted" if granted else "denied", "by": sp.GRANTED_BY, "note": ""}
    nodes = {
        "orders": {"output": inputs["orders"]},
        "customers": {"output": inputs["customers"]},
        "sales_orders": {"output": inputs["sales_orders"]},
        "triage": {"output": triage},
        "draft": {"output": drafts},
        "approve": {"output": decision},
    }
    if granted:
        nodes["send_drafts"] = {"output": {"results": [{}] * len(drafts["drafts"])}}
        finance = len(_by_action(triage, "confirm_payment", "escalate_finance"))
        nodes["ledger_notes"] = {"output": {"results": [{}] * finance}}
        nodes["warehouse_notes"] = {"output": {"results": [{}] * len(_by_action(triage, "nudge_warehouse"))}}
    return {"input": INPUT, "memory": [], "nodes": nodes}


def _pesos(minor: int) -> str:
    """Pesos the way the pack's CEL writes them: no thousands separators."""
    return f"₱{minor // 100}.{minor % 100:02d}"


def _days(reference: str) -> int:
    return (date.fromisoformat(AS_OF) - date.fromisoformat(reference)).days


def test_the_definitions_validate():
    assert sp.bundle_errors() == []


def test_the_pack_and_its_input():
    pack = sp.body("pack", PACK)
    assert (pack["function"], pack["risk_class"]) == ("finance-ops", "medium")
    assert pack["agents"] == ["o2c-triage-agent", "collections-writer", "o2c-report-agent"]
    assert pack["connectors"] == ["custom-business-app", "gmail"]
    schema = sp.body("schema", f"{PACK}/input")
    defaults = {k: v.get("default") for k, v in schema["properties"].items()}
    assert defaults == {
        "since": "2026-09-16",
        "until": AS_OF,
        "company_name": COMPANY,
        "grace_days": 7,
        "max_messages": 3,
    }
    assert sp.schema_errors(f"{PACK}/input", INPUT) == []
    assert sp.schema_errors(f"{PACK}/input", {**INPUT, "since": "16/09/2026"})


def test_one_approval_unlocks_the_drafts_and_the_notes_after_them():
    """The one grant unlocks the customer drafts it routes to and, through also_unlocks, the finance and
    warehouse notes that follow; a refused approval reaches the report without any write."""
    nodes = {n["id"]: n for n in sp.workflow(PACK)["nodes"]}
    assert [i for i, n in nodes.items() if n["type"] == "approval"] == ["approve"]
    assert [i for i, n in nodes.items() if n["type"] == "human_workforce"] == []
    assert nodes["approve"]["routes"] == {"granted": "send_drafts", "denied": "report", "timeout": "report"}
    assert nodes["approve"]["config"]["also_unlocks"] == ["ledger_notes", "warehouse_notes"]
    assert nodes["send_drafts"]["routes"]["ok"] == "ledger_notes"
    assert nodes["ledger_notes"]["routes"]["ok"] == "warehouse_notes"
    assert nodes["warehouse_notes"]["routes"]["ok"] == "report"
    assert sp.writes_without_approval(PACK) == []
    for key in ("custom-business-app", "gmail"):
        assert sp.body("connector", key)["defaults"]["write"] == "require_approval"


def test_the_decision_routes_are_the_node_s_routes():
    assert sp.decision_routes("o2c-exceptions") == set(sp.node(PACK, "check")["routes"])


def test_the_agents_follow_the_conventions():
    for key in ("o2c-triage-agent", "collections-writer", "o2c-report-agent"):
        agent = sp.body("agent", key)
        assert agent["runtime"]["adapter"] == "google_adk"
        assert (agent["runtime"]["model_profile"], agent["runtime"]["max_turns"]) == ("reasoning", 6)
    for key in ("o2c-triage-agent", "collections-writer"):
        assert sp.PERSONAL_DATA_LINE in sp.skill_text(key)


def test_the_planted_cases_share_one_id_across_the_four_systems():
    inputs = _inputs()
    ids = {o["id"] for o in inputs["orders"]["orders"]}
    assert ids == {s["id"] for s in inputs["sales_orders"]["sales_orders"]}
    assert ids == {s["id"] for s in inputs["sales"]["sales"]}
    not_shipped = {"DEMO-PNS-1", "DEMO-PNS-2", "DEMO-PNS-3"}
    assert {s["id"] for s in inputs["served_orders"]["served_orders"]} == ids - not_shipped
    assert {p["order_id"] for p in inputs["payments"]["payments"]} <= ids
    assert set(PLANTED) <= ids and not any(i.startswith("DEMO-CUP") for i in ids)
    assert {o["currency"] for o in inputs["orders"]["orders"]} == {"PHP"}
    pending = [p for p in inputs["payments"]["payments"] if p["status"] == "pending"]
    assert [(p["order_id"], p["mode_of_payment"]) for p in pending] == [("DEMO-PPC-1", "GCash")]
    customers = inputs["customers"]["customers"]
    disputed = next(c for c in customers if c["name"].startswith("Edgardo P. Sarmiento"))
    assert "credit memo" in disputed["notes"][0]
    emails = [c["email"] for c in customers if c["email"]]
    assert emails and all(e.endswith("@example.com") for e in emails)
    assert sum(c["account_manager"] is None for c in customers) > len(customers) / 2  # rarely recorded
    sellers = {(s["seller_name"], s["seller_email"]) for s in inputs["sales"]["sales"] if s["id"] in PLANTED}
    assert sellers <= set(SELLERS.items())


def test_the_fake_triage_finds_every_planted_case():
    triage = _triage()
    assert sp.schema_errors(f"{PACK}/triage", triage) == []
    by_id = {e["order_id"]: e for e in triage["exceptions"]}
    assert set(PLANTED) <= set(by_id)
    for order_id, (kind, amount) in PLANTED.items():
        e = by_id[order_id]
        assert (e["kind"], e["amount_minor"], e["currency"]) == (kind, amount, "PHP"), order_id
        assert e["days_outstanding"] == _days(e["reference_date"]) >= 0
        if kind == "paid_not_shipped":
            assert e["recommended_action"] in ("nudge_warehouse", "none") and e["due_date"] is None
        else:
            assert e["recommended_action"] == ACTIONS[kind]
        assert (e["account_manager"], e["account_manager_email"]) in SELLERS.items()
    assert "sign-off" in by_id["DEMO-SNP-1"]["evidence"]  # above ₱20,000
    assert "credit memo" in by_id["DEMO-DSP-1"]["evidence"]
    assert "pending GCash payment" in by_id["DEMO-PPC-1"]["evidence"]
    assert "7-day grace" in by_id["DEMO-SNP-3"]["evidence"]
    assert triage["sign_off_note"].startswith("DEMO-SNP-1 (₱40,252.80) is above ₱20,000")
    # Kinds in the table's order, the longest outstanding first within a kind; the totals add up.
    order = [(KINDS.index(e["kind"]), -e["days_outstanding"]) for e in triage["exceptions"]]
    assert order == sorted(order)
    sales_orders = _inputs()["sales_orders"]["sales_orders"]
    assert triage["clean_count"] + len(triage["exceptions"]) == len(sales_orders)
    for kind in KINDS:
        of = [e for e in triage["exceptions"] if e["kind"] == kind]
        assert triage["totals"][kind] == {
            "count": len(of),
            "amount_minor": sum(e["amount_minor"] for e in of),
        }
    assert triage["summary"].startswith(f"{len(sales_orders)} orders checked")
    assert "payment pending confirmation (₱15,600.00)" in triage["summary"]


def test_the_account_manager_falls_back_to_the_sales_app_seller():
    inputs = _inputs()
    customers = {c["id"]: c for c in inputs["customers"]["customers"]}
    sales = {s["id"]: s for s in inputs["sales"]["sales"]}
    triage = _triage(inputs)
    unrecorded = [e for e in triage["exceptions"] if customers[e["customer_id"]]["account_manager"] is None]
    assert unrecorded  # the ledger rarely records one, so the fallback is exercised by the fixtures
    for e in unrecorded:
        sale = sales[e["order_id"]]
        assert (e["account_manager"], e["account_manager_email"]) == (
            sale["seller_name"],
            sale["seller_email"],
        )
    recorded = [e for e in triage["exceptions"] if customers[e["customer_id"]]["account_manager"]]
    for e in recorded:
        assert e["account_manager"] == customers[e["customer_id"]]["account_manager"]
    orders = {o["id"]: o for o in inputs["orders"]["orders"]}
    no_sales = _triage(inputs, sales={"sales": []})  # no sale either: the store's seller email, no name
    for e in no_sales["exceptions"]:
        if customers[e["customer_id"]]["account_manager"] is None:
            assert (e["account_manager"], e["account_manager_email"]) == (
                None,
                orders[e["order_id"]]["seller_email"],
            )


def test_the_grace_period_keeps_fresh_invoices_clean():
    base = _triage()
    overdue = base["totals"]["shipped_not_paid"]["count"]
    assert overdue >= 3
    lenient = _triage(grace_days=90)  # longer than any fixture order has been outstanding
    assert lenient["totals"]["shipped_not_paid"] == {"count": 0, "amount_minor": 0}
    assert "DEMO-SNP-3" not in [e["order_id"] for e in lenient["exceptions"]]
    assert lenient["clean_count"] == base["clean_count"] + overdue


def test_the_orders_the_triage_calls_clean_give_no_exception_on_their_own():
    """The clean orders alone give no exception, so the run would go straight to the report."""
    inputs = _inputs()
    broken = {e["order_id"] for e in _triage(inputs)["exceptions"]}
    for name, key in (
        ("orders", "orders"),
        ("payments", "payments"),
        ("sales_orders", "sales_orders"),
        ("served_orders", "served_orders"),
        ("sales", "sales"),
    ):
        inputs[name] = {key: [r for r in inputs[name][key] if (r.get("order_id") or r["id"]) not in broken]}
    triage = _triage(inputs)
    assert triage["exceptions"] == [] and triage["sign_off_note"] == ""
    assert triage["clean_count"] == len(inputs["sales_orders"]["sales_orders"]) > 0
    assert sp.schema_errors(f"{PACK}/triage", triage) == []
    assert "Every order agrees" in triage["summary"]


def test_the_fake_writer_drafts_the_largest_reminders_first_and_stops_at_the_cap():
    triage = _triage()
    drafts = _drafts(triage)
    assert sp.schema_errors(f"{PACK}/drafts", drafts) == []
    largest = sorted(_to_draft(triage), key=lambda e: -e["amount_minor"])[:3]
    assert [d["order_id"] for d in drafts["drafts"]] == [e["order_id"] for e in largest]
    assert [d["order_id"] for d in drafts["drafts"]] == ["DEMO-SNP-1", "DEMO-SNP-2", "DEMO-SNP-3"]
    for draft, e in zip(drafts["drafts"], largest, strict=True):
        assert (draft["to"], draft["account_manager"]) == (e["customer_email"], e["account_manager"])
        assert (
            draft["subject"] == f"Payment reminder: Invoice {e['invoice_number']} for order {e['order_id']}"
        )
    first, snp1 = drafts["drafts"][0], largest[0]
    terms = (date.fromisoformat(snp1["due_date"]) - date.fromisoformat(snp1["reference_date"])).days
    assert first["body"].startswith(f"Dear {snp1['customer_name'].split(' - ')[0]},")
    assert "₱40,252.80" in first["body"]
    assert f"delivered on {snp1['delivered_on']}, with payment terms of {terms} days" in first["body"]
    assert f"{snp1['days_outstanding'] - terms} days past due" in first["body"]
    signature = ["Maraming salamat po,", snp1["account_manager"], f"Account Manager, {COMPANY}"]
    assert first["body"].endswith("\n".join([*signature, snp1["account_manager_email"]]))
    assert "payment due on delivery" in drafts["drafts"][2]["body"]  # DEMO-SNP-3 is cash on delivery
    capped = _drafts(triage, max_messages=2)
    assert [d["order_id"] for d in capped["drafts"]] == ["DEMO-SNP-1", "DEMO-SNP-2"]
    for e in triage["exceptions"]:
        e["account_manager"] = None
    assert _drafts(triage)["drafts"][0]["account_manager"] == f"{COMPANY} Accounts"


def test_the_decision_routes_by_what_the_agent_found():
    rules = sp.body("decision_rules", "o2c-exceptions")
    state = _state()
    assert decisions.evaluate_rules(rules, state).route == "exceptions"
    clean = {**state, "nodes": {**state["nodes"], "triage": {"output": {**_triage(), "exceptions": []}}}}
    assert decisions.evaluate_rules(rules, clean).route == "nothing"
    empty = {**state, "nodes": {**state["nodes"], "orders": {"output": {"orders": []}}}}
    assert decisions.evaluate_rules(rules, empty).route == "blocked"


def test_the_approval_says_what_it_sends_and_posts_in_pesos():
    summary = sp.node(PACK, "approve")["config"]["summary"]
    triage = _triage()
    drafts = _drafts(triage)
    totals = triage["totals"]
    snp, ppc, dsp, pns = (
        totals["shipped_not_paid"],
        totals["payment_pending_confirmation"],
        totals["disputed"],
        totals["paid_not_shipped"],
    )
    nudges = len(_by_action(triage, "nudge_warehouse"))
    finance = _by_action(triage, "confirm_payment", "escalate_finance")
    reminders, notes = len(drafts["drafts"]), len(finance)
    escalated = sum(e["kind"] == "shipped_not_paid" for e in finance)
    expected = (
        f"Save {reminders} collection reminders as Gmail drafts for {snp['count']} shipped-but-not-paid "
        f"invoices ({_pesos(snp['amount_minor'])} outstanding); post {notes} finance notes in the ledger "
        f"({ppc['count']} payment pending confirmation, {_pesos(ppc['amount_minor'])}; {dsp['count']} "
        f"disputed, {_pesos(dsp['amount_minor'])}; {escalated} shipped-but-not-paid, escalated because the "
        f"customer has no email on file) and {nudges} warehouse nudges ({pns['count']} paid orders "
        f"waiting, {_pesos(pns['amount_minor'])}). {triage['sign_off_note']}"
    )
    assert runtime_cel.resolve(summary, _state(triage, drafts)) == expected
    assert "DEMO-SNP-1 (₱40,252.80) is above ₱20,000" in expected
    nothing = {
        **triage,
        "exceptions": [],
        "sign_off_note": "",
        "totals": {**totals, "shipped_not_paid": {"count": 0, "amount_minor": 0}},
    }
    none = _state(nothing, {"drafts": []})
    assert runtime_cel.resolve(summary, none).startswith("No collection reminder to send; post ")


def test_the_writes_fan_out_over_the_recommended_actions():
    triage = _triage()
    state = _state(triage)
    expect = {
        "send_drafts": [d["order_id"] for d in state["nodes"]["draft"]["output"]["drafts"]],
        "ledger_notes": [e["order_id"] for e in _by_action(triage, "confirm_payment", "escalate_finance")],
        "warehouse_notes": [e["order_id"] for e in _by_action(triage, "nudge_warehouse")],
    }
    assert {"DEMO-PPC-1", "DEMO-DSP-1"} <= set(expect["ledger_notes"])
    assert {"DEMO-PNS-1", "DEMO-PNS-2"} <= set(expect["warehouse_notes"])
    for node_id, ids in expect.items():
        items = runtime_cel.resolve(sp.node(PACK, node_id)["config"]["for_each"], state)
        assert [i["order_id"] for i in items] == ids, node_id


def _expected_outcome(e: dict, drafted: set[str], sent: bool) -> str:
    if e["recommended_action"] == "none":
        return "listed"
    if not sent:
        return "not_sent"
    if e["recommended_action"] == "draft_collection_message":
        return "drafted" if e["order_id"] in drafted else "not_sent"
    return "noted"


def test_the_report_agent_gets_what_ran_and_the_verification_passes():
    inputs = sp.node(PACK, "report")["config"]["inputs"]
    triage = _triage()
    state = _state(triage)
    granted = runtime_cel.resolve(inputs, state)
    drafts = state["nodes"]["draft"]["output"]["drafts"]
    finance = len(_by_action(triage, "confirm_payment", "escalate_finance"))
    nudges = len(_by_action(triage, "nudge_warehouse"))
    assert (granted["drafts_created"], granted["finance_notes"], granted["warehouse_notes"]) == (
        3,
        finance,
        nudges,
    )
    assert granted["approval"]["decision"] == "granted" and len(granted["drafts"]) == 3
    assert sp.schema_errors(f"{PACK}/report-request", granted) == []
    report = fakes.agent_script("o2c-report-agent")(granted)
    assert sp.schema_errors(f"{PACK}/report", report) == []
    assert report["sent"] is True and report["totals"] == triage["totals"]
    drafted = {d["order_id"] for d in drafts}
    assert [(r["order_id"], r["outcome"]) for r in report["rows"]] == [
        (e["order_id"], _expected_outcome(e, drafted, True)) for e in triage["exceptions"]
    ]
    assert {r["outcome"] for r in report["rows"]} >= {"drafted", "noted"}
    assert sum(r["outcome"] == "not_sent" for r in report["rows"]) == len(_to_draft(triage)) - 3  # the cap
    assert report["summary"].endswith(
        f"3 reminders were saved as Gmail drafts, {finance} notes posted for finance and {nudges} notes for "
        "the warehouse."
    )
    state["nodes"]["report"] = {"output": report}
    for check in sp.node(PACK, "verify")["config"]["checks"]:
        assert runtime_cel.evaluate(check, state) is True, check


def test_a_refused_approval_ends_with_the_report_and_nothing_sent():
    triage = _triage()
    denied = runtime_cel.resolve(sp.node(PACK, "report")["config"]["inputs"], _state(triage, granted=False))
    assert (denied["drafts_created"], denied["finance_notes"], denied["warehouse_notes"]) == (0, 0, 0)
    report = fakes.agent_script("o2c-report-agent")(denied)
    assert sp.schema_errors(f"{PACK}/report", report) == []
    assert report["sent"] is False
    assert report["actions"] == {"reminders_drafted": 0, "finance_notes": 0, "warehouse_notes": 0}
    assert [r["outcome"] for r in report["rows"]] == [
        _expected_outcome(e, set(), False) for e in triage["exceptions"]
    ]
    assert report["summary"].endswith("Nothing was sent or posted: the approval was not granted.")
    state = _state(triage, granted=False)
    state["nodes"]["report"] = {"output": report}
    for check in sp.node(PACK, "verify")["config"]["checks"]:
        assert runtime_cel.evaluate(check, state) is True, check
    # A write refused at the gateway leaves the node without output; the report still counts zero.
    refused = _state(triage)
    refused["nodes"]["send_drafts"] = {"output": None}
    del refused["nodes"]["ledger_notes"], refused["nodes"]["warehouse_notes"]
    counts = runtime_cel.resolve(sp.node(PACK, "report")["config"]["inputs"], refused)
    assert (counts["drafts_created"], counts["finance_notes"]) == (0, 0)


def test_a_sandbox_run_triages_approves_once_and_writes_everything(runtime_env):  # noqa: F811
    conn = runtime_env
    triage = _triage()
    finance = len(_by_action(triage, "confirm_payment", "escalate_finance"))
    nudges = len(_by_action(triage, "nudge_warehouse"))
    run_id, _, status = sp.run_pack(conn, PACK, INPUT, STOPS)
    assert status == "COMPLETED"
    entries = _entries(conn, run_id)
    calls = [e["data"] for e in entries if e["type"] == "tool.call"]
    assert [c["tool_ref"] for c in calls] == READS + ["gmail.create_draft"] * 3 + [
        "custom-business-app.add_ledger_note"
    ] * finance + ["custom-business-app.add_warehouse_note"] * nudges
    assert all(c["policy"]["verdict"] == "PERMIT" for c in calls)
    assert {tuple(c["policy"]["reason_codes"]) for c in calls[len(READS) :]} == {("APPROVAL_GRANTED",)}
    [decided] = [e["data"] for e in entries if e["type"] == "decision"]
    assert decided["reason_code"] == "EXCEPTIONS_FOUND"
    assert not any(e["type"] == "human.task" for e in entries)
    run = Run.model_validate(_run_row(conn, run_id)["projection"])
    assert run.deliverable.kind == "Exception desk report"
    totals = triage["totals"]

    def fact(kind: str) -> str:
        return f"{totals[kind]['count']} · {_pesos(totals[kind]['amount_minor'])}"

    assert [(r.label, r.value) for r in run.deliverable.rows] == [
        ("Exceptions", str(len(triage["exceptions"]))),
        ("Payments pending confirmation", fact("payment_pending_confirmation")),
        ("Shipped, not paid", fact("shipped_not_paid")),
        ("Paid, not shipped", fact("paid_not_shipped")),
        ("Disputed", fact("disputed")),
        ("Reminders drafted", "3"),
        ("Finance notes", str(finance)),
        ("Warehouse notes", str(nudges)),
    ]
    assert "sandbox data" in run.deliverable.summary
    assert [i.label.split(" — ")[0] for i in run.deliverable.items] == [
        e["order_id"] for e in triage["exceptions"]
    ]


def test_connector_args_are_valid_for_the_real_tools():
    """Task 12 owns the shared arg check for seeded packs only, so this pack checks its own."""
    state = _state()
    nodes = [n for n in sp.workflow(PACK)["nodes"] if n["type"] == "connector"]
    assert len(nodes) == 9
    for n in nodes:
        cfg = n["config"]
        connector, _, tool_id = cfg["tool"].partition(".")
        tool = next(t for t in sp.body("connector", connector)["tools"] if t["id"] == tool_id)
        scope = dict(state)
        if "for_each" in cfg:
            scope["item"] = runtime_cel.resolve(cfg["for_each"], state)[0]
        args = runtime_cel.resolve(cfg.get("args") or {}, scope)
        errors = [e.message for e in Draft202012Validator(tool["input_schema"]).iter_errors(args)]
        assert errors == [], (n["id"], errors)
    orders = next(n for n in nodes if n["id"] == "orders")
    assert runtime_cel.resolve(orders["config"]["args"], state)["since"] == "2026-07-18T00:00:00Z"


def test_a_draft_to_an_address_that_is_not_the_customers_is_not_written():
    state = _state()
    drafts = state["nodes"]["draft"]["output"]["drafts"]
    state["nodes"]["draft"]["output"] = {
        "drafts": [{**drafts[0], "to": "someone.else@example.com"}, *drafts[1:]]
    }
    node = sp.node(PACK, "send_drafts")["config"]["for_each"]
    assert [i["order_id"] for i in runtime_cel.resolve(node, state)] == [d["order_id"] for d in drafts[1:]]
    # The report and its verification count what could be written, so one refused item is not a failed run.
    granted = runtime_cel.resolve(sp.node(PACK, "report")["config"]["inputs"], state)
    assert [d["order_id"] for d in granted["drafts"]] == [d["order_id"] for d in drafts[1:]]


def test_a_note_for_an_order_the_business_app_does_not_know_is_not_written():
    triage = _triage()
    state = _state(triage)
    fake = {**_by_action(triage, "confirm_payment")[0], "order_id": "NO-SUCH-ORDER"}
    state["nodes"]["triage"]["output"] = {**triage, "exceptions": [*triage["exceptions"], fake]}
    for node_id in ("ledger_notes", "warehouse_notes"):
        items = runtime_cel.resolve(sp.node(PACK, node_id)["config"]["for_each"], state)
        assert "NO-SUCH-ORDER" not in [i["order_id"] for i in items], node_id


def test_the_approval_and_the_budget_match_the_copy():
    assert sp.node(PACK, "approve")["config"]["title"] == "Save reminder drafts and post notes"
    assert sp.body("contract", PACK)["budget"]["human_budget_minor"] == 0


def test_a_sales_order_with_no_date_is_skipped_and_listed():
    inputs = _inputs()
    orders = inputs["sales_orders"]["sales_orders"]
    undated = {k: v for k, v in orders[0].items() if k not in ("invoice_date", "created_at")}
    undated["id"] = "UNDATED-1"
    inputs["sales_orders"] = {"sales_orders": [*orders, undated]}
    triage = fakes.agent_script("o2c-triage-agent")(inputs)
    base = _triage()
    assert triage["clean_count"] == base["clean_count"]
    assert "UNDATED-1" in triage["summary"] and "skipped" in triage["summary"]
    assert sp.schema_errors(f"{PACK}/triage", triage) == []


def test_a_refused_note_write_is_reported_as_not_sent():
    triage = _triage()
    state = _state(triage)
    state["nodes"]["ledger_notes"] = {"output": None}  # refused at the gateway
    state["nodes"]["warehouse_notes"] = {"output": {"results": [{}]}}
    report = fakes.agent_script("o2c-report-agent")(
        runtime_cel.resolve(sp.node(PACK, "report")["config"]["inputs"], state)
    )
    outcomes = {r["order_id"]: r["outcome"] for r in report["rows"]}
    for e in _by_action(triage, "confirm_payment", "escalate_finance"):
        assert outcomes[e["order_id"]] == "not_sent"
    for e in _by_action(triage, "nudge_warehouse"):
        assert outcomes[e["order_id"]] == "noted"


def _approval_call(**extra):
    from app.worker.activities import NodeCall

    workflow = sp.workflow(PACK)
    snapshot = {
        "defs": {
            "workflow": {PACK: {"body": workflow}},
            "contract": {PACK: {"body": sp.body("contract", PACK)}},
            "connector": {c: {"body": sp.body("connector", c)} for c in ("custom-business-app", "gmail")},
        },
        **extra,
    }
    return NodeCall("run_1", snapshot, "approve", _state())


def test_the_approval_payload_lists_the_extra_writes_with_their_simulated_flag(monkeypatch):
    from app.runtime import gateway
    from app.worker import activities

    monkeypatch.setattr(gateway, "runs_simulated", lambda snapshot, ref, mode: ref.startswith("custom-"))
    call = _approval_call()
    payload = activities._task_payload(call, activities._node(call.snapshot, "approve"), "approval")
    assert (payload["tool_ref"], payload["mocked"]) == ("gmail.create_draft", False)
    counts = {n: len(_write_list(call.state, n)) for n in ("send_drafts", "ledger_notes", "warehouse_notes")}
    assert payload["count"] == counts["send_drafts"] > 0
    assert payload["unlocked"] == [
        {
            "node": "ledger_notes",
            "tool_ref": "custom-business-app.add_ledger_note",
            "mocked": True,
            "count": counts["ledger_notes"],
        },
        {
            "node": "warehouse_notes",
            "tool_ref": "custom-business-app.add_warehouse_note",
            "mocked": True,
            "count": counts["warehouse_notes"],
        },
    ]


def test_an_approval_is_refused_when_an_extra_write_could_not_run(monkeypatch):
    from app.runtime import gateway
    from app.worker import activities

    refused = {"custom-business-app.add_warehouse_note": gateway.GRANT_REVOKED}
    monkeypatch.setattr(gateway, "approval_refusal", lambda snapshot, ref: refused.get(ref))
    call = _approval_call()
    code, why = activities._refused_approval(call, activities._node(call.snapshot, "approve"))
    assert code == gateway.GRANT_REVOKED and "no longer grants" in why
    refused.clear()
    assert activities._refused_approval(call, activities._node(call.snapshot, "approve")) is None


def _write_list(state: dict, node_id: str) -> list:
    return runtime_cel.resolve(sp.node(PACK, node_id)["config"]["for_each"], state)


def _without_email(state: dict, customer_id: str) -> dict:
    customers = state["nodes"]["customers"]["output"]["customers"]
    state["nodes"]["customers"]["output"] = {
        "customers": [{**c, "email": None} if c["id"] == customer_id else c for c in customers]
    }
    return state


def _counts_line(state: dict) -> str:
    return runtime_cel.resolve(sp.node(PACK, "approve")["config"]["summary"], state)


def test_every_count_in_the_approval_summary_is_the_length_of_its_write_list():
    triage = _triage()
    plain = _state(triage)
    # A shipped-but-not-paid customer with no email is escalated to finance, so it is a ledger note too.
    snp = next(e for e in triage["exceptions"] if e["kind"] == "shipped_not_paid")
    no_email = _triage(
        customers={
            "customers": [
                {**c, "email": None} if c["id"] == snp["customer_id"] else c
                for c in _inputs()["customers"]["customers"]
            ]
        }
    )
    assert any(
        e["kind"] == "shipped_not_paid" and e["recommended_action"] == "escalate_finance"
        for e in no_email["exceptions"]
    )
    for state in (plain, _state(no_email)):
        line = _counts_line(state)
        drafts, ledger, warehouse = (
            _write_list(state, n) for n in ("send_drafts", "ledger_notes", "warehouse_notes")
        )
        assert f"post {len(ledger)} finance note" in line
        assert f" and {len(warehouse)} warehouse nudge" in line
        assert line.startswith(f"Save {len(drafts)} collection reminder")
        escalated = sum(e["kind"] == "shipped_not_paid" for e in ledger)
        assert f"{escalated} shipped-but-not-paid, escalated because the customer has no email" in line
        assert "Held back" not in line


def test_what_is_held_back_is_said_in_the_summary_and_the_report_row_is_not_sent():
    triage = _triage()
    state = _state(triage)
    drafts = state["nodes"]["draft"]["output"]["drafts"]
    state["nodes"]["draft"]["output"] = {
        "drafts": [{**drafts[0], "to": "someone.else@example.com"}, *drafts[1:]]
    }
    ghost = {**_by_action(triage, "confirm_payment")[0], "order_id": "NO-SUCH-ORDER"}
    state["nodes"]["triage"]["output"] = {**triage, "exceptions": [*triage["exceptions"], ghost]}
    state["nodes"]["send_drafts"] = {"output": {"results": [{}] * (len(drafts) - 1)}}
    state["nodes"]["ledger_notes"] = {"output": {"results": [{}] * len(_write_list(state, "ledger_notes"))}}
    assert "Held back, not written: 1 reminder(s)" in _counts_line(state)
    assert "1 note(s) whose order is not in the ledger" in _counts_line(state)
    inputs = runtime_cel.resolve(sp.node(PACK, "report")["config"]["inputs"], state)
    assert inputs["drafts_held_back"] == [drafts[0]["order_id"]] and inputs["notes_held_back"] == [
        "NO-SUCH-ORDER"
    ]
    assert "NO-SUCH-ORDER" not in inputs["finance_written"]
    report = fakes.agent_script("o2c-report-agent")(inputs)
    rows = {r["order_id"]: r for r in report["rows"]}
    assert (
        rows["NO-SUCH-ORDER"]["outcome"] == "not_sent"
        and "order is not in the ledger" in rows["NO-SUCH-ORDER"]["note"]
    )
    held = rows[drafts[0]["order_id"]]
    assert held["outcome"] == "not_sent" and "recipient is not on the customer record" in held["note"]
    assert {rows[d["order_id"]]["outcome"] for d in drafts[1:]} == {"drafted"}
    state["nodes"]["report"] = {"output": report}
    for check in sp.node(PACK, "verify")["config"]["checks"]:
        assert runtime_cel.evaluate(check, state) is True, check


def test_a_draft_address_matches_the_customer_record_whatever_its_case():
    state = _state()
    drafts = state["nodes"]["draft"]["output"]["drafts"]
    state["nodes"]["draft"]["output"] = {"drafts": [{**d, "to": d["to"].upper()} for d in drafts]}
    assert len(_write_list(state, "send_drafts")) == len(drafts)


def test_a_customer_with_no_email_gets_no_draft():
    state = _state()
    drafts = state["nodes"]["draft"]["output"]["drafts"]
    customer_id = next(
        o["customer_id"]
        for o in state["nodes"]["sales_orders"]["output"]["sales_orders"]
        if o["id"] == drafts[0]["order_id"]
    )
    assert drafts[0]["order_id"] not in [
        d["order_id"] for d in _write_list(_without_email(state, customer_id), "send_drafts")
    ]


def test_a_sales_order_with_a_malformed_date_is_skipped_and_listed():
    inputs = _inputs()
    orders = inputs["sales_orders"]["sales_orders"]
    bad = {**orders[0], "id": "BAD-DATE-1", "invoice_date": "not-a-date"}
    inputs["sales_orders"] = {"sales_orders": [*orders, bad]}
    triage = fakes.agent_script("o2c-triage-agent")(inputs)
    assert "BAD-DATE-1" in triage["summary"] and triage["clean_count"] == _triage()["clean_count"]
