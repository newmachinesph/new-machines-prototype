"""Meeting Follow-ups: definitions, sandbox calendar, fake agent, decision and a sandbox run."""

from jsonschema import Draft202012Validator

from app.models.runs import Run
from app.runtime import cel as runtime_cel
from app.runtime import decisions, fakes
from tests import sample_packs as sp
from tests.test_workflow import _entries, _run_row, runtime_env  # noqa: F401

PACK = "meeting-follow-ups"
INPUT = {"day": "2026-10-15", "signature": "Alex Tan"}


def _plan() -> dict:
    events = sp.sandbox(PACK, "googlecalendar", "list_events")
    return fakes.agent_script("meeting-agent")({"events": events, "day": INPUT["day"]})


def test_the_definitions_validate():
    assert sp.bundle_errors() == []


def test_the_pack_and_its_input():
    pack = sp.body("pack", PACK)
    assert (pack["function"], pack["risk_class"]) == ("operations", "low")
    assert pack["agents"] == ["meeting-agent", "writer-agent"]
    assert pack["connectors"] == ["googlecalendar", "gmail"]
    assert sp.schema_errors(f"{PACK}/input", INPUT) == []
    assert sp.schema_errors(f"{PACK}/input", {"day": "yesterday", "signature": "Alex"})


def test_every_write_comes_after_its_own_approval():
    assert sp.writes_without_approval(PACK) == []


def test_the_decision_routes_are_the_node_s_routes():
    assert sp.decision_routes("meeting-follow-ups") == set(sp.node(PACK, "check")["routes"])


def test_the_calendar_is_read_for_the_whole_day_in_utc():
    args = runtime_cel.resolve(sp.node(PACK, "events")["config"]["args"], {"input": INPUT})
    assert (args["timeMin"], args["timeMax"]) == ("2026-10-15T00:00:00Z", "2026-10-15T23:59:59Z")
    tool = next(t for t in sp.body("connector", "googlecalendar")["tools"] if t["id"] == "list_events")
    assert not list(Draft202012Validator(tool["input_schema"]).iter_errors(args))


def test_every_connector_call_has_valid_args_for_the_real_tool():
    """test_defs_content skips packs outside its SEED_PACKS, so this pack checks its own calls."""
    state = {
        "input": INPUT,
        "nodes": {"plan": {"output": _plan()}},
        "item": {"to": "maya.chen@brightleaf.example.com", "subject": "Follow-up", "body": "Hello"},
    }
    calls = [n for n in sp.workflow(PACK)["nodes"] if n["type"] == "connector"]
    assert len(calls) == 2
    for node in calls:
        connector, _, tool_id = node["config"]["tool"].partition(".")
        tool = next(t for t in sp.body("connector", connector)["tools"] if t["id"] == tool_id)
        args = runtime_cel.resolve(node["config"].get("args") or {}, state)
        errors = [e.message for e in Draft202012Validator(tool["input_schema"]).iter_errors(args)]
        assert errors == [], (node["id"], errors)


def test_the_agent_follows_the_conventions():
    agent = sp.body("agent", "meeting-agent")
    assert agent["runtime"]["adapter"] == "google_adk"
    assert (agent["runtime"]["model_profile"], agent["runtime"]["max_turns"]) == ("fast", 4)


def test_the_fake_agent_plans_one_follow_up_per_outside_guest():
    plan = _plan()
    assert sp.schema_errors(f"{PACK}/plan", plan) == []
    assert [(m["title"], m["follow_up"]) for m in plan["meetings"]] == [
        ("Focus time", False),
        ("Daily stand-up", False),
        ("Brightleaf Events: venue options", True),
        ("Okafor Legal: contract review", True),
        ("Supplier call", False),
        ("Intro call: Nordlys Studio", False),
    ]
    assert [m["to"] for m in plan["messages"]] == [
        "maya.chen@brightleaf.example.com",
        "tom@okaforlegal.example.com",
    ]
    assert plan["messages"][0]["about"] == "Follow-up: Brightleaf Events: venue options"
    assert "Agreed: send two venue options and a price by Friday." in plan["messages"][0]["facts"]
    request = {"items": plan["messages"], "review": None, "tone": "x"}
    assert sp.schema_errors("shared/draft-request", request) == []


def test_a_day_without_outside_meetings_plans_nothing():
    plan = fakes.agent_script("meeting-agent")({"events": {"items": []}, "day": "2026-10-16"})
    assert plan["messages"] == [] and sp.schema_errors(f"{PACK}/plan", plan) == []
    rules = sp.body("decision_rules", "meeting-follow-ups")
    assert decisions.evaluate_rules(rules, {"nodes": {"plan": {"output": plan}}}).route == "nothing"


def test_a_sandbox_run_drafts_the_follow_ups_after_approval(runtime_env):  # noqa: F811
    conn = runtime_env
    run_id, _, status = sp.run_pack(conn, PACK, INPUT, [("approve", sp.APPROVAL)])
    assert status == "COMPLETED"
    calls = [e["data"] for e in _entries(conn, run_id) if e["type"] == "tool.call"]
    assert [c["tool_ref"] for c in calls] == [
        "googlecalendar.list_events",
        "gmail.create_draft",
        "gmail.create_draft",
    ]
    run = Run.model_validate(_run_row(conn, run_id)["projection"])
    assert [(r.label, r.value) for r in run.deliverable.rows] == [("Drafts created", "2")]
    assert run.deliverable.items[0].label == (
        "maya.chen@brightleaf.example.com — Follow-up: Brightleaf Events: venue options"
    )
    assert "sandbox data" in run.deliverable.summary
    [completed] = [e["data"] for e in _entries(conn, run_id) if e["type"] == "run.completed"]
    assert all(d["body"].endswith("Kind regards,\nAlex Tan") for d in completed["deliverable"]["drafts"])
