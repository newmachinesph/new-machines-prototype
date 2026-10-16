"""Inbox Lead Tracker: definitions, the decision model over the sandbox inbox, the fake agent, a sandbox run,
and the explicit fallback when the decision model is off."""

import re

from jsonschema import Draft202012Validator

from app import settings
from app.models.runs import Run
from app.runtime import cel as runtime_cel
from app.runtime import decisions, fakes, jev
from tests import sample_packs as sp
from tests.test_workflow import _entries, _run_row, _tasks, runtime_env  # noqa: F401

PACK = "inbox-lead-tracker"
SHEET = "sandbox-leads-sheet-000000000000001"
INPUT = {"spreadsheet_id": SHEET}
MAYA, TOM, AIKO = (f"19b2c0a1d2e3000{n}" for n in (5, 3, 1))


VENDOR = re.compile(r"jev|typesafe|openrouter", re.IGNORECASE)


def _vendor_hits() -> list[str]:
    """Vendor names in the pack, agent, schemas and decision rules (internal `jev` names are fine)."""
    root = settings.defs_dir()
    files = [root / "packs" / PACK / "pack.yaml", root / "decisions" / "lead-screen.yaml"]
    files += [p for p in (root / "agents" / "lead-agent").rglob("*") if p.is_file()]
    files += list((root / "packs" / PACK / "schemas").glob("*.json"))
    hits = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if VENDOR.search(line) and line.strip() != "kind: jev" and "jev.kept" not in line:
                hits.append(f"{path.name}: {line.strip()}")
    return hits


def _inbox() -> dict:
    return sp.sandbox(PACK, "gmail", "list_threads")


def _screened():
    rules = sp.body("decision_rules", "lead-screen")
    state = {"input": INPUT, "nodes": {"inbox": {"output": _inbox()}}}
    return decisions.evaluate_rules(rules, state, client=jev.FakeJev())


def test_the_definitions_validate():
    assert sp.bundle_errors() == []


def test_the_pack_and_its_input():
    pack = sp.body("pack", PACK)
    assert (pack["function"], pack["risk_class"]) == ("sales-ops", "low")
    assert pack["agents"] == ["lead-agent"] and pack["connectors"] == ["gmail", "googlesheets"]
    assert "manufacturing" not in pack["industries"]
    assert "decision model" in pack["description"]  # says what is sent where
    assert not _vendor_hits()
    schema = sp.body("schema", f"{PACK}/input")
    assert schema["properties"]["spreadsheet_id"]["default"] == SHEET
    assert sp.schema_errors(f"{PACK}/input", INPUT) == []


def test_every_write_comes_after_its_own_approval():
    assert sp.writes_without_approval(PACK) == []


def test_the_decision_routes_include_the_fallback():
    routes = sp.decision_routes("lead-screen")
    assert routes == set(sp.node(PACK, "screen")["routes"]) == {"nothing", "leads", "failed"}
    on_error = sp.body("decision_rules", "lead-screen")["evaluator"]["on_error"]
    assert (on_error["verdict"], on_error["route"]) == ("BLOCKED", "failed")


def test_the_inbox_read_never_exceeds_the_decision_model_limit():
    assert sp.node(PACK, "inbox")["config"]["args"]["max_results"] <= jev.MAX_ITEMS


def test_the_agent_follows_the_conventions():
    agent = sp.body("agent", "lead-agent")
    assert agent["runtime"]["adapter"] == "google_adk"
    assert (agent["runtime"]["model_profile"], agent["runtime"]["max_turns"]) == ("fast", 4)


def test_the_decision_model_keeps_the_real_enquiries():
    outcome = _screened()
    assert (outcome.route, outcome.reason_code) == ("leads", "LEADS_FOUND")
    assert outcome.kept == [MAYA, TOM, AIKO]
    urgency = {i["ref"]: i["answers"]["urgency"]["value"] for i in outcome.items}
    assert (urgency[MAYA], urgency[TOM], urgency[AIKO]) == ("urgent", "soon", "normal")


def test_the_fake_agent_extracts_the_leads():
    outcome = _screened()
    emails = [m for m in _inbox()["messages"] if m["messageId"] in outcome.kept]
    leads = fakes.agent_script("lead-agent")({"emails": emails, "screening": outcome.items})
    assert sp.schema_errors(f"{PACK}/leads", leads) == []
    assert [(lead["name"], lead["company"], lead["urgency"]) for lead in leads["leads"]] == [
        ("Maya Chen", "Brightleaf Events", "urgent"),
        ("Tom Okafor", "Okafor Legal", "soon"),
        ("Aiko Sato", "Not given", "normal"),
    ]
    first = leads["rows"][0][:4]
    assert first == ["2026-10-14", "Maya Chen", "Brightleaf Events", "maya.chen@brightleaf.example.com"]


def test_one_lead_reads_in_the_singular():
    one = [m for m in _inbox()["messages"] if m["messageId"] == MAYA]
    outcome = _screened()
    leads = fakes.agent_script("lead-agent")({"emails": one, "screening": outcome.items})
    assert leads["summary"] == "Found 1 lead, 1 urgent."
    state = {"nodes": {"extract": {"output": leads}}}
    summary = sp.node(PACK, "approve")["config"]["summary"]
    assert runtime_cel.resolve(summary, state) == "Add 1 row to the Leads tab"
    two = {"nodes": {"extract": {"output": {"leads": leads["leads"] * 2, "rows": []}}}}
    assert runtime_cel.resolve(summary, two) == "Add 2 rows to the Leads tab"


def test_the_rows_written_are_the_leads_shown():
    """The agent's own `rows` are never written: each row is built from a lead the run page shows."""
    outcome = _screened()
    emails = [m for m in _inbox()["messages"] if m["messageId"] in outcome.kept]
    leads = fakes.agent_script("lead-agent")({"emails": emails, "screening": outcome.items})
    tampered = {**leads, "rows": [["2026-10-14", '=HYPERLINK("x")', "", "", "", "", ""]]}
    values = sp.node(PACK, "write")["config"]["args"]["values"]
    written = runtime_cel.resolve(values, {"nodes": {"extract": {"output": tampered}}})
    assert written == leads["rows"]
    assert len(written) == len(leads["leads"]) == 3


def _view_summary(deliverable: dict, mocked: bool) -> str:
    view = sp.body("pack", PACK)["deliverable_view"]
    return runtime_cel.evaluate(view["summary"], {"deliverable": deliverable, "mocked": mocked})


def test_a_sandbox_run_with_no_leads_says_it_is_sandbox_data():
    nothing = runtime_cel.resolve(sp.node(PACK, "nothing")["config"]["deliverable"], {})
    assert _view_summary(nothing, mocked=True) == (
        "No email in the inbox looked like a real enquiry. This is sandbox data."
    )
    assert _view_summary(nothing, mocked=False) == "No email in the inbox looked like a real enquiry."
    one = {"leads": [{"name": "Maya Chen"}]}
    assert _view_summary(one, mocked=True).startswith("1 lead was found in sandbox email.")


def test_connector_args_are_valid_for_the_real_tools():
    """Task 12 owns the shared arg check for seeded packs only, so this pack checks its own."""
    outcome = _screened()
    emails = [m for m in _inbox()["messages"] if m["messageId"] in outcome.kept]
    leads = fakes.agent_script("lead-agent")({"emails": emails, "screening": outcome.items})
    state = {"input": INPUT, "nodes": {"extract": {"output": leads}}}
    checked = []
    for n in sp.workflow(PACK)["nodes"]:
        if n["type"] != "connector":
            continue
        cfg = n["config"]
        connector, _, tool_id = cfg["tool"].partition(".")
        tool = next(t for t in sp.body("connector", connector)["tools"] if t["id"] == tool_id)
        args = runtime_cel.resolve(cfg.get("args") or {}, state)
        errors = [e.message for e in Draft202012Validator(tool["input_schema"]).iter_errors(args)]
        assert errors == [], (n["id"], errors)
        checked.append(n["id"])
    assert checked == ["inbox", "write"]


def test_a_sandbox_run_screens_extracts_and_writes_after_approval(runtime_env):  # noqa: F811
    conn = runtime_env
    run_id, _, status = sp.run_pack(conn, PACK, INPUT, [("approve", sp.APPROVAL)])
    assert status == "COMPLETED"
    entries = _entries(conn, run_id)
    calls = [e["data"] for e in entries if e["type"] == "tool.call"]
    assert [c["tool_ref"] for c in calls] == ["gmail.list_threads", "googlesheets.append_rows"]
    assert calls[1]["policy"]["reason_codes"] == ["APPROVAL_GRANTED"]
    [decided] = [e["data"] for e in entries if e["type"] == "decision"]
    assert decided["evaluator"]["status"] == "answered" and decided["kept"] == [MAYA, TOM, AIKO]
    projection = _run_row(conn, run_id)["projection"]
    screen = next(n for n in projection["nodes"] if n["id"] == "screen")
    assert screen["subtitle"] == "Decision model"
    assert [c["kind"] for c in screen["decision"]["chain"]] == ["jev", "rules"]
    assert screen["cost"]["amountMinor"] >= 1 and projection["spent"]["ai"]["amountMinor"] >= 1
    run = Run.model_validate(projection)
    assert [(r.label, r.value) for r in run.deliverable.rows] == [("Leads found", "3"), ("Urgent", "1")]
    assert "sandbox" in run.deliverable.summary


def test_with_the_decision_model_off_the_run_fails_safely_and_writes_nothing(runtime_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NM_JEV", "off")
    conn = runtime_env
    run_id, _, status = sp.run_pack(conn, PACK, INPUT, [])
    assert status == "FAILED"
    entries = _entries(conn, run_id)
    assert [e["data"]["tool_ref"] for e in entries if e["type"] == "tool.call"] == ["gmail.list_threads"]
    [decided] = [e["data"] for e in entries if e["type"] == "decision"]
    assert (decided["verdict"], decided["reason_code"]) == ("BLOCKED", "DECISION_MODEL_UNAVAILABLE")
    assert decided["evaluator"]["status"] == "off"
    assert not [t for t in _tasks(conn, run_id) if t["kind"] == "approval"]
    screen = next(n for n in _run_row(conn, run_id)["projection"]["nodes"] if n["id"] == "screen")
    assert screen["decision"]["chain"] == [
        {"kind": "jev", "verdict": "ERROR", "note": "The decision model is switched off."}
    ]
