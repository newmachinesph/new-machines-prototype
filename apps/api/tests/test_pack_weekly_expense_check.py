"""Weekly Expense Check: definitions, sandbox data, fake agent and decision, and sandbox runs."""

from jsonschema import Draft202012Validator

from app.models.runs import Run
from app.runtime import cel as runtime_cel
from app.runtime import decisions, fakes
from tests import sample_packs as sp
from tests.test_workflow import _entries, _run_row, _tasks, runtime_env  # noqa: F401

PACK = "weekly-expense-check"
SHEET = "sandbox-expenses-sheet-0000000000001"
INPUT = {
    "week_start": "2026-10-05",
    "spreadsheet_id": SHEET,
    "expenses_range": "Expenses!A:E",
    "summary_tab": "Summary",
    "email_to": "finance@yourco.example.com",
}


def _report(week_start: str = "2026-10-05") -> dict:
    sheet = sp.sandbox(PACK, "googlesheets", "read_rows")
    return fakes.agent_script("expense-agent")({"sheet": sheet, "week_start": week_start, "rules": []})


def test_the_definitions_validate():
    assert sp.bundle_errors() == []


def test_the_pack_and_its_input():
    pack = sp.body("pack", PACK)
    assert (pack["function"], pack["risk_class"]) == ("finance-ops", "medium")
    assert pack["agents"] == ["expense-agent", "writer-agent"]
    assert pack["connectors"] == ["googlesheets", "gmail"]
    schema = sp.body("schema", f"{PACK}/input")
    assert schema["properties"]["spreadsheet_id"]["default"] == SHEET  # live runs must name a real sheet
    assert sp.schema_errors(f"{PACK}/input", INPUT) == []
    assert sp.schema_errors(f"{PACK}/input", {**INPUT, "summary_tab": "Bad!Tab"})


def test_every_write_comes_after_its_own_approval():
    assert sp.writes_without_approval(PACK) == []
    assert sp.node(PACK, "approve_sheet")["routes"]["granted"] == "write"
    assert sp.node(PACK, "approve_email")["routes"]["granted"] == "send"


def test_the_decision_routes_are_the_node_s_routes():
    assert sp.decision_routes("expense-flags") == set(sp.node(PACK, "check")["routes"])


def test_the_agent_follows_the_conventions():
    agent = sp.body("agent", "expense-agent")
    assert agent["runtime"]["adapter"] == "google_adk"
    assert (agent["runtime"]["model_profile"], agent["runtime"]["max_turns"]) == ("reasoning", 6)
    assert sp.PERSONAL_DATA_LINE in sp.skill_text("expense-agent")


def test_the_fake_agent_checks_the_sandbox_week():
    report = _report()
    assert sp.schema_errors(f"{PACK}/report", report) == []
    assert sp.schema_errors("shared/review-items", report["review_items"]) == []
    assert (report["week_start"], report["week_end"]) == ("2026-10-05", "2026-10-11")
    assert [e["row"] for e in report["expenses"]] == [2, 3, 4, 5, 6, 7, 8, 9]
    assert report["total_minor"] == 92965
    assert [(c["category"], c["count"], c["amount_minor"]) for c in report["categories"]] == [
        ("Travel", 3, 72350),
        ("Meals", 2, 9600),
        ("Software", 2, 4800),
        ("Office", 1, 6215),
    ]
    assert [(i["ref"], i["flag"]) for i in report["review_items"]] == [
        ("Row 6", "No receipt for $25 or more"),
        ("Row 7", "Over the $500 limit"),
        ("Row 9", "Possible duplicate of row 4"),
    ]
    assert report["summary_rows"][0] == ["2026-10-05", "Travel", "3", "723.50"]
    assert report["summary_rows"][-1] == ["2026-10-05", "Total", "8", "929.65"]
    assert report["email_facts"][0] == "Expenses from 2026-10-05 to 2026-10-11: 8 items, 929.65 USD in total."


def test_an_empty_week_has_nothing_to_check():
    report = _report("2026-11-02")
    assert sp.schema_errors(f"{PACK}/report", report) == []
    assert (report["expenses"], report["summary_rows"], report["email_facts"]) == ([], [], [])


def test_the_skill_writes_singular_and_plural_out():
    skill = sp.skill_text("expense-agent")
    assert "item(s)" not in skill
    for phrase in ("1 item", "<count> items", "1 expense is flagged", "<n> expenses are flagged"):
        assert phrase in skill, phrase


def test_the_sheet_approval_counts_rows_in_the_singular_and_plural():
    summary = sp.node(PACK, "approve_sheet")["config"]["summary"]

    def says(rows: int) -> str:
        state = {"input": INPUT, "nodes": {"analyse": {"output": {"summary_rows": [[]] * rows}}}}
        return runtime_cel.resolve(summary, state)

    assert says(1) == "Add 1 row to the Summary tab"
    assert says(5) == "Add 5 rows to the Summary tab"


def test_the_email_approval_shows_the_subject_it_sends():
    summary = sp.node(PACK, "approve_email")["config"]["summary"]
    draft = {"to": INPUT["email_to"], "subject": "Weekly expenses: week of 2026-10-05", "body": "Hi."}
    one = {"input": INPUT, "nodes": {"draft": {"output": {"drafts": [draft]}}}}
    assert runtime_cel.resolve(summary, one) == (
        'Send the summary email "Weekly expenses: week of 2026-10-05" to finance@yourco.example.com'
    )
    two = {"input": INPUT, "nodes": {"draft": {"output": {"drafts": [draft, draft]}}}}
    assert runtime_cel.resolve(summary, two) == "Send the summary email to finance@yourco.example.com"


def test_the_decision_routes_by_what_the_agent_found():
    rules = sp.body("decision_rules", "expense-flags")

    def route(expenses, review_items):
        state = {"nodes": {"analyse": {"output": {"expenses": expenses, "review_items": review_items}}}}
        return decisions.evaluate_rules(rules, state).route

    assert route([], []) == "nothing"
    assert route([{}], [{}]) == "human_review"
    assert route([{}], []) == "ordinary"


def test_the_writer_gets_no_review_when_nobody_reviewed():
    """`has(nodes.review)` is false on the ordinary path, where the review step never ran."""
    state = {"input": INPUT, "nodes": {"analyse": {"output": _report()}}}
    inputs = runtime_cel.resolve(sp.node(PACK, "draft")["config"]["inputs"], state)
    assert inputs["review"] is None and inputs["sign_off"] == "Weekly expense check"
    assert inputs["items"][0]["to"] == "finance@yourco.example.com"
    assert sp.schema_errors("shared/draft-request", inputs) == []


def test_a_sandbox_run_checks_reviews_writes_and_sends(runtime_env):  # noqa: F811
    conn = runtime_env
    stops = [("review", sp.HUMAN), ("approve_sheet", sp.APPROVAL), ("approve_email", sp.APPROVAL)]
    run_id, _, status = sp.run_pack(conn, PACK, INPUT, stops)
    assert status == "COMPLETED"
    entries = _entries(conn, run_id)
    calls = [e["data"] for e in entries if e["type"] == "tool.call"]
    assert [c["tool_ref"] for c in calls] == [
        "googlesheets.read_rows",
        "googlesheets.append_rows",
        "gmail.send_email",
    ]
    assert all(c["policy"]["verdict"] == "PERMIT" for c in calls)
    assert [c["policy"]["reason_codes"] for c in calls[1:]] == [["APPROVAL_GRANTED"], ["APPROVAL_GRANTED"]]
    [decided] = [e["data"] for e in entries if e["type"] == "decision"]
    assert decided["reason_code"] == "ODD_ITEMS_FOUND" and "evaluator" not in decided
    review = next(t for t in _tasks(conn, run_id) if t["kind"] == "human")
    assert [i["ref"] for i in review["payload"]["show"]] == ["Row 6", "Row 7", "Row 9"]
    run = Run.model_validate(_run_row(conn, run_id)["projection"])
    assert run.deliverable.kind == "Expense summary"
    assert [(r.label, r.value) for r in run.deliverable.rows] == [
        ("Expenses checked", "8"),
        ("Flagged for a check", "3"),
        ("Total", "929.65 USD"),
    ]
    assert "sandbox data" in run.deliverable.summary
    assert [i.label for i in run.deliverable.items] == ["Travel", "Meals", "Software", "Office"]


def test_a_sandbox_week_without_expenses_ends_without_writing(runtime_env):  # noqa: F811
    conn = runtime_env
    run_id, _, status = sp.run_pack(conn, PACK, {**INPUT, "week_start": "2026-11-02"}, [])
    assert status == "COMPLETED"
    calls = [e["data"]["tool_ref"] for e in _entries(conn, run_id) if e["type"] == "tool.call"]
    assert calls == ["googlesheets.read_rows"]


def test_connector_args_are_valid_for_the_real_tools():
    """Task 12 owns the shared arg check for seeded packs only, so this pack checks its own."""
    state = {
        "input": INPUT,
        "nodes": {"analyse": {"output": _report()}},
        "item": {"to": "finance@yourco.example.com", "subject": "Weekly expenses", "body": "Eight items."},
    }
    nodes = [n for n in sp.workflow(PACK)["nodes"] if n["type"] == "connector"]
    assert len(nodes) == 3
    for n in nodes:
        cfg = n["config"]
        connector, _, tool_id = cfg["tool"].partition(".")
        tool = next(t for t in sp.body("connector", connector)["tools"] if t["id"] == tool_id)
        args = runtime_cel.resolve(cfg.get("args") or {}, state)
        errors = [e.message for e in Draft202012Validator(tool["input_schema"]).iter_errors(args)]
        assert errors == [], (n["id"], errors)
