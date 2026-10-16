"""Decision rules: ordered CEL rules, first match wins, else the default.

A rules body may first ask the decision model (`evaluator`, kind jev) a few typed questions about each item.
Its normalised answers reach the rules as `jev` ({items, kept, answers}). When the model is off, unreachable,
answers outside its questions, or there are too many items, the body's `on_error` outcome applies instead:
a safe rejection or a person, never an approval. Nothing here logs the text sent or the answers.
"""

import logging
from dataclasses import asdict, dataclass, field

from app.runtime import cel, jev

log = logging.getLogger(__name__)

NOTES = {
    "off": "The decision model is switched off.",
    "unavailable": "The decision model could not be reached.",
    "invalid": "The decision model's answer could not be used.",
    "too_many": f"There were more than {jev.MAX_ITEMS} items, so the decision model was not asked.",
}
SKIPPED_NOTE = "There was nothing to ask the decision model about."


@dataclass
class DecisionOutcome:
    verdict: str
    route: str
    reason_code: str
    explanation: str
    matched_rule: int | None  # index of the rule that matched; None when the default applied


@dataclass
class EvaluatedOutcome(DecisionOutcome):
    """A decision whose rules asked the decision model. JSON-safe: node output and receipt entry."""

    evaluator: dict = field(default_factory=dict)  # {kind: "jev", status, note}
    items: list = field(default_factory=list)  # [{ref, answers}], one per for_each item
    kept: list = field(default_factory=list)  # the refs `keep` kept
    answers: dict = field(default_factory=dict)  # the answers, when there is no for_each
    usage: dict = field(default_factory=dict)  # {calls, input_tokens, output_tokens, cost_usd, cost_minor}


def _outcome(rule: dict, index: int | None) -> DecisionOutcome:
    return DecisionOutcome(
        verdict=rule["verdict"],
        route=rule["route"],
        reason_code=rule["reason_code"],
        explanation=rule["explanation"],
        matched_rule=index,
    )


def _first_match(rules_def: dict, state: dict) -> DecisionOutcome:
    for index, rule in enumerate(rules_def.get("rules") or []):
        if cel.evaluate(rule["when"], state) is True:
            return _outcome(rule, index)
    return _outcome(rules_def["default"], None)


def evaluate_rules(rules_def: dict, state: dict, client=None) -> DecisionOutcome:
    """`rules_def` is a decision_rules body. A rule or evaluator expression that cannot be evaluated raises
    cel.CelError (a definition error, not a model failure). `client` defaults to jev.client() (NM_JEV)."""
    evaluator = rules_def.get("evaluator")
    if not evaluator:
        return _first_match(rules_def, state)
    return _evaluate(rules_def, evaluator, state, jev.client() if client is None else client)


def _ref(value) -> str | int:
    ok = (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, str) and value != "")
    if not ok:
        raise cel.CelError("evaluator.ref must give a non-empty string or an integer")
    return value


def _subjects(evaluator: dict, state: dict) -> list[tuple[str | int | None, dict]]:
    """(ref, CEL scope) per item to ask about; one subject with no ref when there is no for_each."""
    if "for_each" not in evaluator:
        return [(None, state)]
    items = cel.evaluate(evaluator["for_each"], state)
    if not isinstance(items, list):
        raise cel.CelError("evaluator.for_each is not a list")
    if len(items) > jev.MAX_ITEMS:
        raise jev.JevTooMany(f"{len(items)} items")
    subjects = []
    for item in items:
        scope = {**state, "item": item}
        subjects.append((_ref(cel.evaluate(evaluator["ref"], scope)), scope))
    return subjects


def _text(expressions: list[str], scope: dict) -> str:
    return "\n".join(str(cel.evaluate(e, scope)) for e in expressions)[: jev.MAX_STATE_CHARS]


def _usage(spent: jev.Usage) -> dict:
    return {
        "calls": spent.calls,
        "input_tokens": spent.input_tokens,
        "output_tokens": spent.output_tokens,
        "cost_usd": str(spent.cost_usd),
        "cost_minor": jev.cost_minor(spent.cost_usd),
        "cost_estimated": spent.cost_estimated,
    }


def _fallback(evaluator: dict, error: jev.JevError) -> EvaluatedOutcome:
    log.warning("decision model fallback: %s", error.status)  # the status only: never text or answers
    chosen = evaluator["on_error"]
    return EvaluatedOutcome(
        **asdict(_outcome(chosen, None)),
        evaluator={
            "kind": "jev",
            "status": error.status,
            "note": NOTES.get(error.status, NOTES["unavailable"]),
        },
        usage=_usage(error.usage),  # calls already made still count as spend
    )


def _note(per_item: bool, asked: int, kept: int) -> str:
    if not asked:
        return SKIPPED_NOTE
    if not per_item:
        return "Answered."
    return f"Answered for {asked} item{'' if asked == 1 else 's'}; {kept} kept."


def _judge(rules_def: dict, evaluator: dict, state: dict, subjects: list, replies: list[jev.Reply]):
    """keep and the rules over the answers: (items, kept, answers, chosen). May raise cel.CelError."""
    per_item = "for_each" in evaluator
    items, kept = [], []
    if per_item:
        keep = evaluator.get("keep")
        for (ref, scope), reply in zip(subjects, replies, strict=True):
            items.append({"ref": ref, "answers": reply.answers})
            if keep is not None and cel.evaluate(keep, {**scope, "answers": reply.answers}) is not True:
                continue
            if ref not in kept:
                kept.append(ref)
    answers = replies[0].answers if replies and not per_item else {}
    seen = {"items": items, "kept": kept, "answers": answers}
    return items, kept, answers, _first_match(rules_def, {**state, "jev": seen})


def _evaluate(rules_def: dict, evaluator: dict, state: dict, client) -> EvaluatedOutcome:
    questions = evaluator["questions"]
    per_item = "for_each" in evaluator
    try:
        subjects = _subjects(evaluator, state)
        texts = [_text(evaluator["state"], scope) for _, scope in subjects]
        replies = jev.ask_all(client, texts, questions)
    except jev.JevError as error:  # ask_all turns any other client exception into JevUnavailable
        return _fallback(evaluator, error)
    spent = sum((r.usage for r in replies), jev.Usage())
    try:
        items, kept, answers, chosen = _judge(rules_def, evaluator, state, subjects, replies)
    except cel.CelError:
        # The model's own answer (a null confidence, a dropped key) broke an expression after the calls were
        # paid for: take on_error and keep the spend. Log that it happened, never the expression's values.
        log.warning("decision model answer broke an evaluator or rule expression")
        return _fallback(evaluator, jev.JevInvalid("answer not usable", usage=spent))
    return EvaluatedOutcome(
        **asdict(chosen),
        evaluator={
            "kind": "jev",
            "status": "answered" if replies else "skipped",
            "note": _note(per_item, len(replies), len(kept)),
        },
        items=items,
        kept=kept,
        answers=answers,
        usage=_usage(spent),
    )
