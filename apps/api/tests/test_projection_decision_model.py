"""A decision step whose rules ask the decision model: its evaluator, chain, subtitle and cost in the run
projection. Uses the refund triage snapshot (node `check`, rules `refund-cases`) with an evaluator added."""

import copy
import json
import re
from functools import cache

from app import settings
from app.defs.digest import digest
from app.defs.loader import load_bundle
from app.models.runs import Run
from app.runtime import projection

PACK = "refund-triage"
EVALUATOR = {
    "kind": "jev",
    "for_each": "nodes.requests.output.messages",
    "ref": "item.messageId",
    "state": ["'Subject: ' + item.subject"],
    "questions": {
        "is_refund": {
            "type": "noul",
            "instructions": "Is this email a refund request?",
            "criteria": {"true": "It asks for money back.", "false": "Anything else."},
        }
    },
    "keep": "answers.is_refund.value >= 0.5",
    "on_error": {
        "verdict": "HUMAN_REVIEW",
        "route": "human_review",
        "reason_code": "DECISION_MODEL_UNAVAILABLE",
        "explanation": "The decision model was not available, so a person decides.",
    },
}
BASE = {
    "verdict": "HUMAN_REVIEW",
    "route": "human_review",
    "reason_code": "CASES_PROPOSED",
    "explanation": "A person confirms each case.",
    "matched_rule": None,
    "question": "Are there refund requests to decide?",
    "rules_ref": "refund-cases@v1",
    "policy": {
        "id": "poldec_run_d_check_1",
        "ref": "refund-cases@v1",
        "verdict": "REQUIRE_APPROVAL",
        "reason_codes": ["CASES_PROPOSED"],
        "actor": "rules",
    },
}
USAGE = {"calls": 3, "input_tokens": 360, "output_tokens": 24, "cost_usd": "0.00006", "cost_minor": 1}
ANSWERED = {
    **BASE,
    "evaluator": {"kind": "jev", "status": "answered", "note": "Answered for 3 items; 2 kept."},
    "items": [
        {"ref": "m1", "answers": {"is_refund": {"value": 0.9}}},
        {"ref": "m2", "answers": {"is_refund": {"value": 0.8}}},
        {"ref": "m3", "answers": {"is_refund": {"value": 0.1}}},
    ],
    "kept": ["m1", "m2"],
    "answers": {},
    "usage": USAGE,
}
FELL_BACK = {
    **BASE,
    "reason_code": "DECISION_MODEL_UNAVAILABLE",
    "explanation": "The decision model was not available, so a person decides.",
    "evaluator": {"kind": "jev", "status": "unavailable", "note": "The decision model could not be reached."},
    "items": [],
    "kept": [],
    "answers": {},
    "usage": {**USAGE, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": "0", "cost_minor": 0},
}


@cache
def _bundle():
    return load_bundle(settings.defs_dir())


def _snapshot(with_evaluator: bool) -> dict:
    defs: dict = {}
    versions = []
    for (kind, key), d in sorted(_bundle().items.items()):
        if kind in ("pack", "workflow", "contract") and key != PACK:
            continue
        defs.setdefault(kind, {})[key] = {"body": copy.deepcopy(d.body), "files": d.files}
        versions.append({"kind": kind, "key": key, "version": 1, "digest": digest(d)})
    if with_evaluator:
        defs["decision_rules"]["refund-cases"]["body"]["evaluator"] = copy.deepcopy(EVALUATOR)
    return {"org_id": "org_demo", "versions": versions, "defs": defs, "overrides": {}, "disabled": []}


def _fold(snapshot: dict, *decisions: dict) -> dict:
    p = projection.initial_projection(
        "run_d", snapshot, {"since": "2026-10-06", "until": "2026-10-12"}, "You", 2500
    )
    for seq, data in enumerate(decisions, start=1):
        event = {
            "seq": seq,
            "at": f"2026-10-13T10:00:{seq:02d}Z",
            "type": "decision",
            "node_id": "check",
            "data": data,
        }
        p = projection.apply_event(p, event)
    Run.model_validate(p)  # still a valid Run: no API contract change
    return p


def _check(p: dict) -> dict:
    return next(n for n in p["nodes"] if n["id"] == "check")


def test_a_rules_only_decision_is_unchanged():
    p = _fold(_snapshot(False), BASE)
    decision = _check(p)["decision"]
    assert decision["evaluator"] == {"kind": "rules", "label": "Rules", "configVersion": "refund-cases@v1"}
    assert decision["chain"] == [
        {"kind": "rules", "verdict": "HUMAN_REVIEW", "note": "A person confirms each case."}
    ]
    assert _check(p)["subtitle"] == "Rules"
    assert "cost" not in _check(p)


def test_an_answered_decision_shows_the_decision_model_then_the_rules():
    p = _fold(_snapshot(True), ANSWERED)
    decision = _check(p)["decision"]
    assert decision["evaluator"] == {
        "kind": "jev",
        "label": "Decision model",
        "configVersion": "refund-cases@v1",
    }
    assert decision["chain"] == [
        {"kind": "jev", "verdict": "PASS", "note": "Answered for 3 items; 2 kept."},
        {"kind": "rules", "verdict": "HUMAN_REVIEW", "note": "A person confirms each case."},
    ]
    assert _check(p)["subtitle"] == "Decision model"


def test_a_skipped_call_still_shows_the_rules():
    skipped = {
        **ANSWERED,
        "evaluator": {"kind": "jev", "status": "skipped", "note": "There was nothing to ask."},
    }
    chain = _check(_fold(_snapshot(True), skipped))["decision"]["chain"]
    assert [c["verdict"] for c in chain] == ["PASS", "HUMAN_REVIEW"]


def test_a_fallback_shows_the_model_error_and_the_safe_outcome():
    decision = _check(_fold(_snapshot(True), FELL_BACK))["decision"]
    assert decision["chain"] == [
        {"kind": "jev", "verdict": "ERROR", "note": "The decision model could not be reached."}
    ]
    assert decision["verdict"] == "HUMAN_REVIEW"
    assert decision["reasonCodes"] == ["DECISION_MODEL_UNAVAILABLE"]


def test_the_decision_model_cost_counts_as_ai_spend_on_its_step():
    p = _fold(_snapshot(True), {**ANSWERED, "usage": {**USAGE, "cost_minor": 3}})
    assert p["spent"]["ai"]["amountMinor"] == 3
    assert _check(p)["cost"]["amountMinor"] == 3
    q = _fold(_snapshot(True), {**ANSWERED, "usage": "not a dict"})
    assert q["spent"].get("ai", {"amountMinor": 0})["amountMinor"] == 0


def test_no_model_id_or_vendor_reaches_the_projection():
    text = json.dumps(_fold(_snapshot(True), ANSWERED))
    assert not re.search(r"jev-\d|typesafe|openrouter", text, re.IGNORECASE)
    assert "modelId" not in _check(json.loads(text))["decision"]["evaluator"]
