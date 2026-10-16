"""The decision model: one call asks a few typed questions about one piece of text.

Its answers are untrusted. `normalise` keeps only the shape each question allows and raises JevInvalid
otherwise. Errors carry a short `status`, the `usage` spent so far, and a message that never contains the
request text, the answer body or the API key. Spend never fails open: a call without a reported cost is
priced from its tokens (estimated when the endpoint does not count them), with a per-call floor.
Product copy calls this the "Decision model"; the kind in definitions is `jev`.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import requests

from app import settings

log = logging.getLogger(__name__)

MAX_ITEMS = 20  # items one decision step may ask about
MAX_STATE_CHARS = 4000  # text sent per item
DEADLINE_S = 20.0  # for all items of one step; run_node's start-to-close is 30 s
TIMEOUT = (3.0, 8.0)  # connect, read
PARALLEL = 4
FAKE_COST_USD = Decimal("0.00002")
FAKE_INPUT_TOKENS = 120
FAKE_OUTPUT_TOKENS = 8
MIN_CALL_USD = Decimal("0.001")  # the least a call without a reported cost is charged
OUTPUT_TOKENS_PER_QUESTION = 200  # estimate when the endpoint does not count output tokens
CHARS_PER_TOKEN = 4  # estimate when the endpoint does not count input tokens
_TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)  # prices are per million tokens
_WIRE_FIELDS = ("type", "instructions", "criteria")
_TYPES = ("noul", "choice", "score")


@dataclass(frozen=True)
class Usage:
    """What calls cost: summed over a step's items, and carried by every error."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    cost_estimated: bool = False

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.calls + other.calls,
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
            self.cost_estimated or other.cost_estimated,
        )


class JevError(Exception):
    status = "error"

    def __init__(self, message: str = "", usage: Usage | None = None) -> None:
        super().__init__(message)
        self.usage = usage if usage is not None else Usage()


class JevOff(JevError):
    status = "off"


class JevUnavailable(JevError):
    status = "unavailable"


class JevInvalid(JevError):
    status = "invalid"


class JevTooMany(JevError):
    status = "too_many"


@dataclass(frozen=True)
class Reply:
    answers: dict[str, dict]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    cost_estimated: bool = False

    @property
    def usage(self) -> Usage:
        return Usage(1, self.input_tokens, self.output_tokens, self.cost_usd, self.cost_estimated)


# --- questions and normalisation ----------------------------------------------------------------------------


def _check_questions(questions: Any) -> None:
    """Fail closed on a malformed question, before anything is sent."""
    if not isinstance(questions, dict) or not questions:
        raise JevInvalid("no questions")
    for name, question in questions.items():
        criteria = question.get("criteria") if isinstance(question, dict) else None
        well_formed = (
            isinstance(name, str)
            and isinstance(question, dict)
            and question.get("type") in _TYPES
            and isinstance(question.get("instructions"), str)
            and isinstance(criteria, dict)
            and len(criteria) >= (2 if question["type"] == "score" else 1)
        )
        if not well_formed:
            raise JevInvalid(f"{name if isinstance(name, str) else 'a question'}: malformed question")


def _wire(questions: dict[str, dict]) -> dict[str, dict]:
    return {n: {k: q[k] for k in _WIRE_FIELDS if k in q} for n, q in questions.items()}


def _finite(value: Any) -> float | None:
    """A JSON number as a finite float, else None. A number too large for a float is invalid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        raise JevInvalid("an answer number is too large") from None
    return number if math.isfinite(number) else None


def _number(value: Any, low: float, high: float) -> float:
    number = _finite(value)
    if number is None:
        raise JevInvalid("an answer is not a finite number")
    if not low <= number <= high:
        raise JevInvalid("an answer is out of range")
    return number


def _confidence(answer: dict) -> float | None:
    return None if answer.get("confidence") is None else _number(answer["confidence"], 0.0, 1.0)


def _probabilities(raw: Any, allowed: set[str]) -> dict[str, float]:
    """Only the question's own options, only numbers in [0, 1]; anything else is dropped."""
    if not isinstance(raw, dict):
        return {}
    kept = {}
    for key, value in raw.items():
        number = _finite(value)
        if str(key) in allowed and number is not None and 0.0 <= number <= 1.0:
            kept[str(key)] = number
    return kept


def _one(name: str, question: dict, answer: Any) -> dict:
    if not isinstance(answer, dict):
        raise JevInvalid(f"no answer for {name}")
    kind = question["type"]
    if answer.get("type") not in (None, kind):
        raise JevInvalid(f"{name}: the answer has another type")
    if kind == "noul":
        return {"value": _number(answer.get("noul"), 0.0, 1.0)}
    options = [str(k) for k in question["criteria"]]
    if kind == "choice":
        choice = answer.get("choice")
        if not isinstance(choice, str) or choice not in options:
            raise JevInvalid(f"{name}: the answer is not one of the options")
        value: str | float = choice
    else:
        value = _number(answer.get("score"), 0.0, float(len(options) - 1))
    return {
        "value": value,
        "confidence": _confidence(answer),
        "probabilities": _probabilities(answer.get("probabilities"), set(options)),
    }


def normalise(raw: Any, questions: dict[str, dict]) -> dict[str, dict]:
    """The answers to `questions`, typed and bounded. Raises JevInvalid for anything else."""
    _check_questions(questions)
    if not isinstance(raw, dict):
        raise JevInvalid("the answers are not an object")
    return {name: _one(name, question, raw.get(name)) for name, question in questions.items()}


# --- usage and cost -----------------------------------------------------------------------------------------


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usd(value: Any) -> Decimal | None:
    """A reported cost, when it is a finite number above zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation, ValueError:
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _price(input_tokens: int, output_tokens: int) -> Decimal:
    per_in = Decimal(str(settings.jev_usd_per_mtok_in()))
    per_out = Decimal(str(settings.jev_usd_per_mtok_out()))
    return (input_tokens * per_in + output_tokens * per_out) / _TOKENS_PER_PRICE_UNIT


def _measured(raw: Any, state: str, wire: dict[str, dict]) -> Usage:
    """One call's usage: reported counts and cost where valid, estimates otherwise. Never zero."""
    raw = raw if isinstance(raw, dict) else {}
    input_tokens = _count(raw.get("input_tokens"))
    if input_tokens is None:
        question_chars = len(json.dumps(wire, ensure_ascii=False, default=str))
        input_tokens = len(state) // CHARS_PER_TOKEN + question_chars // CHARS_PER_TOKEN
    output_tokens = _count(raw.get("output_tokens"))
    if output_tokens is None:
        output_tokens = OUTPUT_TOKENS_PER_QUESTION * len(wire)
    reported = _usd(raw.get("cost"))
    if reported is not None:
        return Usage(1, input_tokens, output_tokens, reported, False)
    return Usage(1, input_tokens, output_tokens, max(_price(input_tokens, output_tokens), MIN_CALL_USD), True)


def _estimate(state: str, questions: dict[str, dict]) -> Usage:
    """One call whose usage is unknown (sent but not answered, or still in flight)."""
    return _measured(None, state[:MAX_STATE_CHARS], _wire(questions))


def cost_minor(usd: Decimal) -> int:
    """US dollars as whole cents, rounded up (any non-zero cost is at least 1 cent)."""
    if usd <= 0:
        return 0
    return int((usd * 100).to_integral_value(rounding=ROUND_CEILING))


# --- clients ------------------------------------------------------------------------------------------------


class HttpJev:
    """The hosted endpoint: POST {model, state, questions} with a bearer key; reply {answers, usage}."""

    def __init__(self, url: str, api_key: str, model: str, post: Callable[..., Any] = requests.post) -> None:
        if urlparse(url).scheme != "https":
            raise ValueError("the decision model URL must use https")
        self._url, self._api_key, self._model, self._post = url, api_key, model, post

    def __repr__(self) -> str:
        return f"HttpJev({urlparse(self._url).hostname}, {self._model})"

    def ask(self, state: str, questions: dict[str, dict]) -> Reply:
        _check_questions(questions)
        if not self._api_key:
            raise JevUnavailable("no key")
        text, wire = state[:MAX_STATE_CHARS], _wire(questions)
        sent = _measured(None, text, wire)  # what a sent call is charged when its usage is unknown
        try:
            res = self._post(
                self._url,
                json={"model": self._model, "state": text, "questions": wire},
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=TIMEOUT,
                allow_redirects=False,  # a 3xx is a non-200 below: the text never goes to another URL
            )
        except requests.RequestException as exc:
            raise JevUnavailable(type(exc).__name__, usage=sent) from None
        if res.status_code != 200:
            raise JevUnavailable(f"HTTP {res.status_code}", usage=sent)
        try:
            data = res.json()
        except ValueError:
            raise JevInvalid("the reply is not JSON", usage=sent) from None
        if not isinstance(data, dict):
            raise JevInvalid("the reply is not an object", usage=sent)
        usage = _measured(data.get("usage"), text, wire)
        try:
            answers = normalise(data.get("answers"), questions)
        except JevInvalid as exc:
            raise JevInvalid(str(exc), usage=usage) from None
        return Reply(answers, usage.input_tokens, usage.output_tokens, usage.cost_usd, usage.cost_estimated)


class FakeJev:
    """Scripted answers per question name (app.runtime.fakes), through the same normalisation."""

    def __init__(self, answer_for: Callable[[str], Callable[[str], dict] | None] | None = None) -> None:
        self._answer_for = answer_for

    def ask(self, state: str, questions: dict[str, dict]) -> Reply:
        _check_questions(questions)
        answer_for = self._answer_for
        if answer_for is None:
            from app.runtime import fakes  # the pack scripts import nothing from here; lazy keeps it so

            answer_for = fakes.jev_answer
        raw = {}
        for name in questions:
            script = answer_for(name)
            if script is None:
                raise JevUnavailable(f"no fake answer for {name}")
            raw[name] = script(state[:MAX_STATE_CHARS])
        return Reply(normalise(raw, questions), FAKE_INPUT_TOKENS, FAKE_OUTPUT_TOKENS, FAKE_COST_USD)


class OffJev:
    def ask(self, state: str, questions: dict[str, dict]) -> Reply:
        raise JevOff("switched off")


def client() -> HttpJev | FakeJev | OffJev:
    mode = settings.jev_mode()
    if mode == "fake":
        return FakeJev()
    if mode == "live":
        try:
            return HttpJev(settings.jev_url(), settings.jev_api_key(), settings.jev_model())
        except ValueError:  # a URL that is not https: fail closed, and say so (never the URL or the key)
            log.warning("decision model URL is not https; the decision model is off")
            return OffJev()
    return OffJev()


def _ask(client: Any, state: str, questions: dict[str, dict]) -> Reply:
    try:
        return client.ask(state, questions)
    except JevError:
        raise
    except Exception as exc:  # a bug in a client is a failed call, never a pass
        raise JevUnavailable(type(exc).__name__) from None


def _spent(future: Future, state: str, questions: dict[str, dict]) -> Usage:
    if future.cancelled():  # never started
        return Usage()
    if not future.done():  # still in flight: charge it as one estimated call
        return _estimate(state, questions)
    error = future.exception()
    if error is None:
        return future.result().usage
    return error.usage if isinstance(error, JevError) else Usage()


def ask_all(
    client: Any, states: list[str], questions: dict[str, dict], deadline_s: float = DEADLINE_S
) -> list[Reply]:
    """One reply per state, in order. Raises the first failure in item order, JevTooMany over MAX_ITEMS (no
    call is made) and JevUnavailable("timed out") when the replies are not all in by the deadline. Every
    raised error carries the usage of all calls made, with in-flight calls charged as estimates."""
    if len(states) > MAX_ITEMS:
        raise JevTooMany(f"{len(states)} items")
    if not states:
        return []
    pool = ThreadPoolExecutor(max_workers=min(PARALLEL, len(states)))
    try:
        futures = [pool.submit(_ask, client, state, questions) for state in states]
        _, pending = wait(futures, timeout=deadline_s)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    def spent() -> Usage:
        return sum((_spent(f, s, questions) for f, s in zip(futures, states, strict=True)), Usage())

    if pending:
        raise JevUnavailable("timed out", usage=spent())
    first = next((f.exception() for f in futures if f.exception() is not None), None)
    if first is not None:
        raise type(first)(str(first), usage=spent()) from None
    return [future.result() for future in futures]
