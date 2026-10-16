"""Decision rules that first ask the decision model: its answers reach the rules as `jev`; every failure takes
the body's on_error outcome (never an approval); the validator checks the evaluator and its routes."""

import copy
import json
from dataclasses import asdict, replace

import pytest

from app import settings
from app.defs.loader import load_bundle
from app.defs.model import Bundle
from app.defs.validate import validate_bundle
from app.runtime import cel, decisions, jev

EMAILS = [
    {
        "messageId": "m1",
        "sender": "Maya Chen <maya@brightleaf.example.com>",
        "subject": "Quote for 40 guests",
        "messageText": "Could you quote for a dinner on 12 November?",
    },
    {
        "messageId": "m2",
        "sender": "Daily News <news@digest.example.com>",
        "subject": "Your weekly digest",
        "messageText": "Top stories this week.",
    },
]
STATE = {"input": {}, "nodes": {"inbox": {"output": {"messages": EMAILS}}}}
EVALUATOR = {
    "kind": "jev",
    "for_each": "nodes.inbox.output.messages",
    "ref": "item.messageId",
    "state": ["'From: ' + item.sender", "'Subject: ' + item.subject", "'Text: ' + item.messageText"],
    "questions": {
        "is_lead": {
            "type": "noul",
            "instructions": "Is this email from someone who wants to buy, book or get a price?",
            "criteria": {"true": "A real enquiry.", "false": "Anything else."},
        }
    },
    "keep": "answers.is_lead.value >= 0.7",
    "on_error": {
        "verdict": "BLOCKED",
        "route": "failed",
        "reason_code": "DECISION_MODEL_UNAVAILABLE",
        "explanation": "The decision model was not available, so nothing was written.",
    },
}
RULES = {
    "question": "Are there leads to record?",
    "evaluator": EVALUATOR,
    "rules": [
        {
            "when": "size(jev.kept) == 0",
            "verdict": "APPROVED",
            "route": "nothing",
            "reason_code": "NO_LEADS",
            "explanation": "No email looked like a real enquiry.",
        }
    ],
    "default": {
        "verdict": "APPROVED",
        "route": "extract",
        "reason_code": "LEADS_FOUND",
        "explanation": "Some emails look like real enquiries.",
    },
}
MAYA_TEXT = (
    "From: Maya Chen <maya@brightleaf.example.com>\nSubject: Quote for 40 guests\n"
    "Text: Could you quote for a dinner on 12 November?"
)


def _scored() -> jev.FakeJev:
    return jev.FakeJev(answer_for=lambda name: lambda state: {"noul": 0.92 if "Quote" in state else 0.05})


class Failing:
    def __init__(self, error: Exception) -> None:
        self.error, self.calls = error, 0

    def ask(self, state, questions):
        self.calls += 1
        raise self.error


def test_rules_without_an_evaluator_never_ask_and_are_unchanged():
    plain = {k: v for k, v in RULES.items() if k != "evaluator"}
    plain["rules"] = [{**RULES["rules"][0], "when": "size(nodes.inbox.output.messages) == 0"}]
    client = Failing(AssertionError("never asked"))
    outcome = decisions.evaluate_rules(plain, STATE, client=client)
    assert type(outcome) is decisions.DecisionOutcome and client.calls == 0
    assert (outcome.route, outcome.reason_code, outcome.matched_rule) == ("extract", "LEADS_FOUND", None)


def test_answers_reach_the_keep_expression_and_the_rules():
    outcome = decisions.evaluate_rules(RULES, STATE, client=_scored())
    assert isinstance(outcome, decisions.EvaluatedOutcome)
    assert (outcome.verdict, outcome.route, outcome.reason_code) == ("APPROVED", "extract", "LEADS_FOUND")
    assert outcome.items == [
        {"ref": "m1", "answers": {"is_lead": {"value": 0.92}}},
        {"ref": "m2", "answers": {"is_lead": {"value": 0.05}}},
    ]
    assert outcome.kept == ["m1"]
    assert outcome.evaluator == {"kind": "jev", "status": "answered", "note": "Answered for 2 items; 1 kept."}
    assert outcome.usage == {
        "calls": 2,
        "input_tokens": 2 * jev.FAKE_INPUT_TOKENS,
        "output_tokens": 2 * jev.FAKE_OUTPUT_TOKENS,
        "cost_usd": "0.00004",
        "cost_minor": 1,
        "cost_estimated": False,
    }
    json.dumps(asdict(outcome))  # it goes into the receipt as it is


def test_nothing_kept_routes_by_the_rules():
    client = jev.FakeJev(answer_for=lambda name: lambda state: {"noul": 0.1})
    outcome = decisions.evaluate_rules(RULES, STATE, client=client)
    assert (outcome.route, outcome.reason_code, outcome.matched_rule) == ("nothing", "NO_LEADS", 0)
    assert outcome.kept == []


def test_the_text_sent_is_the_state_expressions_joined_by_lines():
    seen: list[str] = []

    class Recorder:
        def ask(self, state, questions):
            seen.append(state)
            return jev.Reply({"is_lead": {"value": 0.1}})

    decisions.evaluate_rules(RULES, STATE, client=Recorder())
    assert MAYA_TEXT in seen and len(seen) == 2  # calls run in parallel, so compare as a set


def test_no_items_means_no_call_and_the_rules_still_run():
    empty = {"input": {}, "nodes": {"inbox": {"output": {"messages": []}}}}
    client = Failing(AssertionError("never asked"))
    outcome = decisions.evaluate_rules(RULES, empty, client=client)
    assert client.calls == 0
    assert outcome.route == "nothing" and outcome.evaluator["status"] == "skipped"
    assert outcome.usage["cost_minor"] == 0


@pytest.mark.parametrize(
    ("error", "status", "note"),
    [
        (jev.JevOff("switched off"), "off", "The decision model is switched off."),
        (jev.JevUnavailable("HTTP 503"), "unavailable", "The decision model could not be reached."),
        (jev.JevInvalid("bad answer"), "invalid", "The decision model's answer could not be used."),
        (RuntimeError("boom"), "unavailable", "The decision model could not be reached."),
    ],
)
def test_every_failure_takes_the_on_error_outcome(error, status, note):
    outcome = decisions.evaluate_rules(RULES, STATE, client=Failing(error))
    assert (outcome.verdict, outcome.route, outcome.reason_code) == (
        "BLOCKED",
        "failed",
        "DECISION_MODEL_UNAVAILABLE",
    )
    assert outcome.explanation == "The decision model was not available, so nothing was written."
    assert outcome.evaluator == {"kind": "jev", "status": status, "note": note}
    assert (outcome.items, outcome.kept, outcome.matched_rule) == ([], [], None)
    assert outcome.usage["cost_minor"] == 0


def test_too_many_items_fall_back_without_a_call():
    many = {"input": {}, "nodes": {"inbox": {"output": {"messages": [EMAILS[0]] * (jev.MAX_ITEMS + 1)}}}}
    client = Failing(AssertionError("never asked"))
    outcome = decisions.evaluate_rules(RULES, many, client=client)
    assert client.calls == 0 and outcome.route == "failed"
    assert outcome.evaluator["status"] == "too_many"
    assert outcome.evaluator["note"] == "There were more than 20 items, so the decision model was not asked."


def test_one_question_about_the_whole_state_without_for_each():
    rules = copy.deepcopy(RULES)
    for name in ("for_each", "ref", "keep"):
        del rules["evaluator"][name]
    rules["evaluator"]["state"] = ["'Emails: ' + string(size(nodes.inbox.output.messages))"]
    rules["rules"] = [{**RULES["rules"][0], "when": "jev.answers.is_lead.value < 0.5"}]
    outcome = decisions.evaluate_rules(
        rules, STATE, client=jev.FakeJev(answer_for=lambda n: lambda s: {"noul": 0.2})
    )
    assert outcome.answers == {"is_lead": {"value": 0.2}} and outcome.items == [] and outcome.kept == []
    assert outcome.route == "nothing" and outcome.evaluator["note"] == "Answered."


def test_the_default_client_follows_the_flag(monkeypatch):
    monkeypatch.setenv("NM_JEV", "off")
    outcome = decisions.evaluate_rules(RULES, STATE)
    assert outcome.route == "failed" and outcome.evaluator["status"] == "off"


def test_a_failure_after_some_calls_still_reports_their_spend():
    class Half:
        def ask(self, state, questions):
            if "Quote" in state:
                return jev.Reply({"is_lead": {"value": 0.9}}, 10, 2, jev.FAKE_COST_USD)
            raise jev.JevInvalid("bad answer")

    outcome = decisions.evaluate_rules(RULES, STATE, client=Half())
    assert outcome.route == "failed" and outcome.evaluator["status"] == "invalid"
    assert outcome.usage["calls"] == 1 and outcome.usage["cost_usd"] == str(jev.FAKE_COST_USD)
    assert outcome.usage["input_tokens"] == 10


def _choice_rules(keep: str) -> dict:
    rules = copy.deepcopy(RULES)
    rules["evaluator"]["questions"] = {
        "kind": {"type": "choice", "instructions": "Which?", "criteria": {"a": "A.", "b": "B."}}
    }
    rules["evaluator"]["keep"] = keep
    return rules


@pytest.mark.parametrize(
    "keep",
    [
        "answers.kind.probabilities.a >= 0.1",  # a probability key the model left out
        "answers.kind.confidence >= 0.8",  # a null confidence
    ],
)
def test_an_answer_that_breaks_keep_takes_on_error_and_keeps_the_spend(keep):
    client = jev.FakeJev(answer_for=lambda n: lambda s: {"choice": "b", "probabilities": {"b": 0.9}})
    outcome = decisions.evaluate_rules(_choice_rules(keep), STATE, client=client)
    assert (outcome.verdict, outcome.route) == ("BLOCKED", "failed")
    assert outcome.evaluator["status"] == "invalid" and outcome.kept == []
    assert outcome.usage["calls"] == 2 and outcome.usage["cost_usd"] == "0.00004"


def test_an_answer_that_breaks_a_rule_takes_on_error():
    rules = _choice_rules("true")
    rules["rules"] = [{**RULES["rules"][0], "when": "jev.items[0].answers.kind.confidence >= 0.8"}]
    client = jev.FakeJev(answer_for=lambda n: lambda s: {"choice": "a"})
    outcome = decisions.evaluate_rules(rules, STATE, client=client)
    assert outcome.route == "failed" and outcome.usage["calls"] == 2


def test_too_many_items_are_refused_before_any_item_is_evaluated():
    many = {"input": {}, "nodes": {"inbox": {"output": {"messages": [{}] * (jev.MAX_ITEMS + 1)}}}}
    outcome = decisions.evaluate_rules(RULES, many, client=Failing(AssertionError("never asked")))
    assert outcome.evaluator["status"] == "too_many"  # item.messageId would raise on {} if it were evaluated


@pytest.mark.parametrize("ref", ["''", "null", "true", "1.5", "[1]"])
def test_a_bad_ref_is_a_definition_error(ref):
    rules = copy.deepcopy(RULES)
    rules["evaluator"]["ref"] = ref
    with pytest.raises(cel.CelError):
        decisions.evaluate_rules(rules, STATE, client=_scored())


def test_duplicate_refs_are_kept_once_in_order():
    messages = [EMAILS[0], EMAILS[1], EMAILS[0]]
    state = {"input": {}, "nodes": {"inbox": {"output": {"messages": messages}}}}
    outcome = decisions.evaluate_rules(RULES, state, client=_scored())
    assert outcome.kept == ["m1"] and len(outcome.items) == 3


# --- the definition schema and the validator -------------------------------------------------------------


def _schema() -> dict:
    path = settings.defs_dir() / "_schemas" / "nm.decision_rules.v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["in", "true", "false", "null"])
def test_question_names_cannot_be_cel_keywords(name):
    errors = _errors(_with_evaluator(lambda e: e["questions"].update({name: e["questions"]["is_lead"]})))
    assert errors and any(name in e for e in errors), errors


def test_the_fallback_can_never_approve():
    on_error = _schema()["properties"]["evaluator"]["properties"]["on_error"]
    assert "APPROVED" not in on_error["properties"]["verdict"]["enum"]


def _with_evaluator(edit=None) -> Bundle:
    """The real bundle with refund-cases asking the decision model (its node `check` routes nothing and
    human_review), changed by `edit(evaluator)`."""
    bundle = load_bundle(settings.defs_dir())
    d = bundle.get("decision_rules", "refund-cases")
    body = copy.deepcopy(d.body)
    evaluator = copy.deepcopy(EVALUATOR)
    evaluator.update(for_each="nodes.requests.output.messages")
    evaluator["on_error"] = {**evaluator["on_error"], "verdict": "HUMAN_REVIEW", "route": "human_review"}
    if edit is not None:
        edit(evaluator)
    body["evaluator"] = evaluator
    items = dict(bundle.items)
    items[("decision_rules", "refund-cases")] = replace(d, body=body)
    return Bundle(items=items)


def _errors(bundle: Bundle) -> list[str]:
    return [str(e) for e in validate_bundle(bundle)]


def test_a_valid_evaluator_validates():
    assert _errors(_with_evaluator()) == []


@pytest.mark.parametrize(
    ("edit", "mentions"),
    [
        (lambda e: e.update(keep="answers.is_lead.value >="), "evaluator.keep"),
        (lambda e: e["state"].append("item.subject +"), "evaluator.state[3]"),
        (lambda e: e["on_error"].update(verdict="APPROVED"), "on_error"),
        (lambda e: e.pop("ref"), "ref"),
        (lambda e: e["questions"].update({"Bad-Name": e["questions"]["is_lead"]}), "Bad-Name"),
        (lambda e: e["questions"]["is_lead"].update(type="box"), "is_lead"),
        (lambda e: e["questions"]["is_lead"]["criteria"].pop("false"), "is_lead"),
    ],
)
def test_a_bad_evaluator_is_refused(edit, mentions):
    errors = _errors(_with_evaluator(edit))
    assert errors and any(mentions in e for e in errors), errors


def test_every_route_of_an_evaluator_decision_must_be_on_its_node():
    errors = _errors(_with_evaluator(lambda e: e["on_error"].update(route="failed")))
    assert any("check" in e and "'failed'" in e for e in errors), errors
