"""Support Inbox Triage: definitions, the decision model over the sandbox inbox, the fake agent, a sandbox run
with a reviewer, and the fallback where a person checks every case."""

from jsonschema import Draft202012Validator

from app.models.runs import Run
from app.runtime import cel as runtime_cel
from app.runtime import decisions, fakes, jev
from tests import sample_packs as sp
from tests.test_workflow import _entries, _run_row, _tasks, runtime_env  # noqa: F401

PACK = "support-inbox-triage"
SHEET = "sandbox-support-cases-sheet-0000001"
INPUT = {"spreadsheet_id": SHEET}
LENA, RAJ, CHLOE, DEALS, OMAR = (f"19c3d1b2e3f4000{n}" for n in (5, 4, 3, 2, 1))
STOPS = [("review", sp.HUMAN), ("approve_drafts", sp.APPROVAL), ("approve_log", sp.APPROVAL)]


def _inbox() -> dict:
    return sp.sandbox(PACK, "gmail", "list_threads")


def _screened():
    state = {"input": INPUT, "nodes": {"inbox": {"output": _inbox()}}}
    return decisions.evaluate_rules(sp.body("decision_rules", "support-screen"), state, client=jev.FakeJev())


def _triage(screened: bool) -> dict:
    outcome = _screened()
    emails = [m for m in _inbox()["messages"] if not screened or m["messageId"] in outcome.kept]
    inputs = {
        "emails": emails,
        "categories": outcome.items if screened else [],
        "screened": screened,
        "rules": [],
    }
    return fakes.agent_script("support-agent")(inputs)


def test_the_definitions_validate():
    assert sp.bundle_errors() == []


def test_the_pack_and_its_input():
    pack = sp.body("pack", PACK)
    assert (pack["function"], pack["risk_class"]) == ("customer-ops", "medium")
    assert pack["agents"] == ["support-agent", "writer-agent"] and pack["connectors"] == [
        "gmail",
        "googlesheets",
    ]
    assert "decision model" in pack["description"]
    assert sp.body("schema", f"{PACK}/input")["properties"]["spreadsheet_id"]["default"] == SHEET


def test_every_write_comes_after_its_own_approval():
    assert sp.writes_without_approval(PACK) == []
    assert sp.node(PACK, "approve_drafts")["routes"]["granted"] == "save"
    assert sp.node(PACK, "approve_log")["routes"]["granted"] == "log"


def test_the_decision_routes_are_the_node_s_routes():
    assert sp.decision_routes("support-screen") == set(sp.node(PACK, "screen")["routes"])
    assert sp.decision_routes("support-cases") == set(sp.node(PACK, "check")["routes"])
    on_error = sp.body("decision_rules", "support-screen")["evaluator"]["on_error"]
    assert (
        on_error["verdict"] == "HUMAN_REVIEW"
        and sp.node(PACK, "screen")["routes"][on_error["route"]] == "triage"
    )


def test_the_agent_follows_the_conventions():
    agent = sp.body("agent", "support-agent")
    assert agent["runtime"]["adapter"] == "google_adk"
    assert (agent["runtime"]["model_profile"], agent["runtime"]["max_turns"]) == ("reasoning", 6)
    assert sp.PERSONAL_DATA_LINE in sp.skill_text("support-agent")


def test_the_decision_model_sorts_the_inbox_and_leaves_spam_out():
    outcome = _screened()
    assert (outcome.route, outcome.reason_code) == ("sorted", "EMAILS_SORTED")
    category = {i["ref"]: i["answers"]["support_category"]["value"] for i in outcome.items}
    assert category == {LENA: "question", RAJ: "complaint", CHLOE: "refund", DEALS: "spam", OMAR: "question"}
    assert outcome.kept == [LENA, RAJ, CHLOE, OMAR]


def test_the_fake_agent_sends_complaints_and_refunds_to_a_person():
    triage = _triage(screened=True)
    assert sp.schema_errors(f"{PACK}/triage", triage) == []
    assert sp.schema_errors("shared/review-items", triage["review_items"]) == []
    assert [(c["category"], c["needs_person"]) for c in triage["cases"]] == [
        ("question", False),
        ("complaint", True),
        ("refund", True),
        ("question", False),
    ]
    assert [(i["ref"], i["flag"], i["amount_minor"]) for i in triage["review_items"]] == [
        (RAJ, "Complaint", 0),
        (CHLOE, "Refund request", 4800),
    ]
    assert len(triage["messages"]) == len(triage["rows"]) == 4


def test_the_summary_is_singular_for_one_email():
    omar = [m for m in _inbox()["messages"] if m["messageId"] == OMAR]
    categories = [{"ref": OMAR, "answers": {"support_category": {"value": "question"}}}]
    one = fakes.agent_script("support-agent")(
        {"emails": omar, "categories": categories, "screened": True, "rules": []}
    )
    assert one["summary"] == "1 customer email became a case; 0 need a person."
    refund = [m for m in _inbox()["messages"] if m["messageId"] == CHLOE]
    categories = [{"ref": CHLOE, "answers": {"support_category": {"value": "refund"}}}]
    one = fakes.agent_script("support-agent")(
        {"emails": refund, "categories": categories, "screened": True, "rules": []}
    )
    assert one["summary"] == "1 customer email became a case; 1 needs a person."


def test_unscreened_every_case_goes_to_a_person():
    triage = _triage(screened=False)
    assert sp.schema_errors(f"{PACK}/triage", triage) == []
    assert [c["thread_id"] for c in triage["cases"]] == [LENA, RAJ, CHLOE, OMAR]  # spam left out by the agent
    assert all(c["needs_person"] for c in triage["cases"]) and len(triage["review_items"]) == 4


def test_a_sandbox_run_sorts_reviews_drafts_and_logs(runtime_env):  # noqa: F811
    conn = runtime_env
    run_id, _, status = sp.run_pack(conn, PACK, INPUT, STOPS)
    assert status == "COMPLETED"
    entries = _entries(conn, run_id)
    calls = [e["data"]["tool_ref"] for e in entries if e["type"] == "tool.call"]
    assert calls == ["gmail.list_threads"] + ["gmail.create_draft"] * 4 + ["googlesheets.append_rows"]
    screen, check = [e["data"] for e in entries if e["type"] == "decision"]
    assert screen["evaluator"]["status"] == "answered" and screen["reason_code"] == "EMAILS_SORTED"
    assert check["reason_code"] == "CASES_NEED_A_PERSON"
    review = next(t for t in _tasks(conn, run_id) if t["kind"] == "human")
    assert [i["ref"] for i in review["payload"]["show"]] == [RAJ, CHLOE]
    run = Run.model_validate(_run_row(conn, run_id)["projection"])
    assert [(r.label, r.value) for r in run.deliverable.rows] == [("Drafts created", "4")]
    [completed] = [e["data"] for e in entries if e["type"] == "run.completed"]
    assert all(d["body"].endswith("Kind regards,\nSupport team") for d in completed["deliverable"]["drafts"])


def test_with_the_decision_model_off_a_person_checks_every_case(runtime_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NM_JEV", "off")
    conn = runtime_env
    run_id, _, status = sp.run_pack(conn, PACK, INPUT, STOPS)
    assert status == "COMPLETED"
    entries = _entries(conn, run_id)
    screen = next(e["data"] for e in entries if e["type"] == "decision")
    assert (screen["verdict"], screen["reason_code"]) == ("HUMAN_REVIEW", "DECISION_MODEL_UNAVAILABLE")
    assert screen["evaluator"]["status"] == "off"
    review = next(t for t in _tasks(conn, run_id) if t["kind"] == "human")
    assert [i["ref"] for i in review["payload"]["show"]] == [LENA, RAJ, CHLOE, OMAR]


def _check(status: str, items: list, triage: dict):
    screen = {"evaluator": {"kind": "jev", "status": status}, "items": items}
    state = {"nodes": {"screen": {"output": screen}, "triage": {"output": triage}}}
    return decisions.evaluate_rules(sp.body("decision_rules", "support-cases"), state)


def _answered(*categories: str) -> list[dict]:
    return [
        {"ref": f"m{n}", "answers": {"support_category": {"value": c, "confidence": 0.9}}}
        for n, c in enumerate(categories)
    ]


def test_without_the_decision_model_a_person_checks_even_when_the_agent_flags_nothing():
    triage = {**_triage(screened=False), "review_items": []}
    outcome = _check("off", [], triage)
    assert (outcome.verdict, outcome.route, outcome.reason_code) == (
        "HUMAN_REVIEW",
        "human_review",
        "UNSCREENED_CASES",
    )
    nothing_kept = {**triage, "cases": [], "messages": [], "rows": []}
    assert _check("unavailable", [], nothing_kept).route == "human_review"  # all dropped as spam


def test_the_decision_model_s_complaints_and_refunds_go_to_a_person():
    triage = {**_triage(screened=True), "review_items": []}
    for category in ("complaint", "refund"):
        outcome = _check("answered", _answered("question", category), triage)
        assert (outcome.route, outcome.reason_code) == ("human_review", "CASES_NEED_A_PERSON")
    assert _check("answered", _answered("question", "spam"), triage).route == "planned"
    empty = {**triage, "cases": []}
    assert _check("answered", _answered("question"), empty).route == "nothing"


def test_the_reviewer_sees_every_case_when_the_decision_model_was_not_available():
    show = sp.node(PACK, "review")["config"]["show"]
    triage = {**_triage(screened=False), "review_items": []}
    unscreened = {
        "nodes": {"screen": {"output": {"evaluator": {"status": "off"}}}, "triage": {"output": triage}}
    }
    shown = runtime_cel.resolve(show, unscreened)
    assert [i["ref"] for i in shown] == [LENA, RAJ, CHLOE, OMAR]
    assert sp.schema_errors("shared/review-items", shown) == []
    assert [i["flag"] for i in shown] == ["Question", "Complaint", "Refund request", "Question"]
    assert not any("@" in i["flag"] + i["note"] for i in shown)
    screened = {
        "nodes": {
            "screen": {"output": {"evaluator": {"status": "answered"}}},
            "triage": {"output": _triage(True)},
        }
    }
    assert [i["ref"] for i in runtime_cel.resolve(show, screened)] == [RAJ, CHLOE]


def _spam(confidence):
    def answer_for(name):
        return lambda state: {
            "type": "choice",
            "choice": "spam",
            "confidence": confidence,
            "probabilities": {"spam": confidence} if confidence is not None else {},
        }

    return answer_for


def test_only_confident_spam_is_left_out():
    state = {"input": INPUT, "nodes": {"inbox": {"output": _inbox()}}}
    rules = sp.body("decision_rules", "support-screen")
    sure = decisions.evaluate_rules(rules, state, client=jev.FakeJev(_spam(0.9)))
    assert (sure.route, sure.kept) == ("nothing", [])
    for unsure in (0.5, None):
        outcome = decisions.evaluate_rules(rules, state, client=jev.FakeJev(_spam(unsure)))
        assert outcome.route == "sorted" and outcome.kept == [LENA, RAJ, CHLOE, DEALS, OMAR]


def test_unscreened_with_no_review_items_still_reaches_a_person(runtime_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NM_JEV", "off")
    real = fakes.agent_script

    def agent_script(agent_id):
        script = real(agent_id)
        if agent_id != "support-agent":
            return script
        return lambda inputs: {**script(inputs), "review_items": []}

    monkeypatch.setattr(fakes, "agent_script", agent_script)
    conn = runtime_env
    run_id, _, status = sp.run_pack(conn, PACK, INPUT, STOPS)
    assert status == "COMPLETED"
    entries = _entries(conn, run_id)
    screen, check = [e["data"] for e in entries if e["type"] == "decision"]
    assert screen["reason_code"] == "DECISION_MODEL_UNAVAILABLE"
    assert (check["verdict"], check["reason_code"]) == ("HUMAN_REVIEW", "UNSCREENED_CASES")
    review = next(t for t in _tasks(conn, run_id) if t["kind"] == "human")
    assert [i["ref"] for i in review["payload"]["show"]] == [LENA, RAJ, CHLOE, OMAR]


def test_connector_args_are_valid_for_the_real_tools():
    """Task 12 owns the shared arg check for seeded packs only, so this pack checks its own."""
    triage = _triage(screened=True)
    draft = {
        "to": "lena.park@example.com",
        "subject": "Re: Hello",
        "body": "Hello.\n\nKind regards,\nSupport team",
    }
    state = {
        "input": INPUT,
        "nodes": {"triage": {"output": triage}, "draft": {"output": {"drafts": [draft]}}},
        "item": draft,
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
