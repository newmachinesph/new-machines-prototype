"""Decision rules: ordered CEL rules, first match wins, else the default."""

from dataclasses import dataclass

from app.runtime import cel


@dataclass
class DecisionOutcome:
    verdict: str
    route: str
    reason_code: str
    explanation: str
    matched_rule: int | None  # index of the rule that matched; None when the default applied


def _outcome(rule: dict, index: int | None) -> DecisionOutcome:
    return DecisionOutcome(
        verdict=rule["verdict"],
        route=rule["route"],
        reason_code=rule["reason_code"],
        explanation=rule["explanation"],
        matched_rule=index,
    )


def evaluate_rules(rules_def: dict, state: dict) -> DecisionOutcome:
    """`rules_def` is a decision_rules body. A rule that cannot be evaluated raises cel.CelError."""
    for index, rule in enumerate(rules_def.get("rules") or []):
        if cel.evaluate(rule["when"], state) is True:
            return _outcome(rule, index)
    return _outcome(rules_def["default"], None)
