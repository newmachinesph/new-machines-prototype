"""The decision-model client: request shape, answer normalisation, failures and limits. No network: every
HTTP call goes through a recorded fake `post`."""

import time
from decimal import Decimal

import pytest
import requests

from app.runtime import jev

KEY = "test-key-not-real-0000"
QUESTIONS = {
    "is_lead": {
        "type": "noul",
        "instructions": "Is this a sales enquiry?",
        "criteria": {"true": "Asks to buy or book.", "false": "Anything else."},
    },
    "urgency": {
        "type": "choice",
        "instructions": "How soon do they want an answer?",
        "criteria": {"urgent": "Today.", "soon": "This week.", "normal": "No date."},
    },
}
GOOD = {
    "id": "dec_1",
    "model": "typesafe/jev-1.14",
    "answers": {
        "is_lead": {"type": "noul", "noul": 0.91},
        "urgency": {
            "type": "choice",
            "choice": "soon",
            "confidence": 0.8,
            "probabilities": {"urgent": 0.1, "soon": 0.8, "normal": 0.1, "other": 0.5},
        },
    },
    "usage": {"input_tokens": 210, "output_tokens": 9, "cost": 0.000123},
}


class Response:
    def __init__(self, status: int = 200, body=GOOD, json_error: bool = False) -> None:
        self.status_code, self._body, self._json_error = status, body, json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._body


class Post:
    """Records each call; returns `response` or raises `error`."""

    def __init__(self, response: Response | None = None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.response, self.error = response or Response(), error

    def __call__(self, url, *, json, headers, timeout, **options):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout, **options})
        if self.error is not None:
            raise self.error
        return self.response


def _http(post: Post, key: str = KEY) -> jev.HttpJev:
    return jev.HttpJev("https://decisions.example.test/v1", key, "typesafe/jev-1.14", post=post)


def test_sends_the_model_text_and_questions_with_a_bearer_key():
    post = Post()
    _http(post).ask("x" * 5000, QUESTIONS)
    [call] = post.calls
    assert call["url"] == "https://decisions.example.test/v1"
    assert call["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert call["timeout"] == jev.TIMEOUT
    assert call["json"]["model"] == "typesafe/jev-1.14"
    assert call["json"]["state"] == "x" * jev.MAX_STATE_CHARS
    assert call["json"]["questions"] == QUESTIONS
    assert call["allow_redirects"] is False  # a redirect would re-send the text elsewhere


def test_a_redirect_is_unavailable_and_never_followed():
    post = Post(Response(status=307))
    with pytest.raises(jev.JevUnavailable, match="HTTP 307"):
        _http(post).ask("text", QUESTIONS)
    assert len(post.calls) == 1


def test_normalises_answers_and_reports_usage():
    reply = _http(Post()).ask("Hello", QUESTIONS)
    assert reply.answers == {
        "is_lead": {"value": 0.91},
        "urgency": {
            "value": "soon",
            "confidence": 0.8,
            "probabilities": {"urgent": 0.1, "soon": 0.8, "normal": 0.1},  # "other" is dropped
        },
    }
    assert (reply.input_tokens, reply.output_tokens) == (210, 9)
    assert reply.cost_usd == Decimal("0.000123") and reply.cost_estimated is False


@pytest.mark.parametrize(
    "answers",
    [
        {"is_lead": {"noul": 1.5}, "urgency": GOOD["answers"]["urgency"]},  # out of range
        {"is_lead": {"noul": True}, "urgency": GOOD["answers"]["urgency"]},  # a bool is not a number
        {"is_lead": {"noul": "0.9"}, "urgency": GOOD["answers"]["urgency"]},  # a string is not a number
        {"is_lead": {"noul": 0.9}, "urgency": {"choice": "tomorrow"}},  # not an option
        {"is_lead": {"noul": 0.9}},  # an answer is missing
        {"is_lead": {"type": "choice", "noul": 0.9}, "urgency": GOOD["answers"]["urgency"]},  # wrong type
        ["not", "an", "object"],
        {"is_lead": {"noul": float("nan")}, "urgency": GOOD["answers"]["urgency"]},  # NaN
        {"is_lead": {"noul": float("inf")}, "urgency": GOOD["answers"]["urgency"]},  # infinity
        {"is_lead": {"noul": 10**400}, "urgency": GOOD["answers"]["urgency"]},  # too large for a float
        {"is_lead": {"noul": 0.9}, "urgency": {**GOOD["answers"]["urgency"], "confidence": 1.5}},
        {
            "is_lead": {"noul": 0.9},
            "urgency": {**GOOD["answers"]["urgency"], "probabilities": {"soon": 10**400}},
        },
    ],
)
def test_an_answer_outside_its_question_is_invalid(answers):
    body = {**GOOD, "answers": answers}
    with pytest.raises(jev.JevInvalid) as caught:
        _http(Post(Response(body=body))).ask("Hello", QUESTIONS)
    assert caught.value.status == "invalid"
    assert "tomorrow" not in str(caught.value)  # never echoes the model's text
    assert caught.value.usage.calls == 1 and caught.value.usage.cost_usd == Decimal(
        "0.000123"
    )  # it was billed


@pytest.mark.parametrize(
    "questions",
    [
        {},
        {"q": "not an object"},
        {"q": {"instructions": "Missing type?", "criteria": {"true": "Y", "false": "N"}}},
        {"q": {"type": "essay", "instructions": "Unknown type?", "criteria": {"a": "A"}}},
        {"q": {"type": "choice", "instructions": "No criteria?"}},
        {"q": {"type": "choice", "instructions": "List criteria?", "criteria": ["a", "b"]}},
        {"q": {"type": "choice", "instructions": "Empty criteria?", "criteria": {}}},
        {"q": {"type": "score", "instructions": "One level?", "criteria": {"0": "Only"}}},
        {"q": {"type": "noul", "criteria": {"true": "Y", "false": "N"}}},  # no instructions
    ],
)
def test_a_malformed_question_is_invalid_and_nothing_is_sent(questions):
    post = Post()
    with pytest.raises(jev.JevInvalid):
        _http(post).ask("Hello", questions)
    assert post.calls == []


def test_a_score_answer_is_bounded_by_its_levels():
    questions = {
        "fit": {
            "type": "score",
            "instructions": "How good a fit?",
            "criteria": {"0": "No", "1": "Some", "2": "Strong"},
        }
    }
    ok = {
        **GOOD,
        "answers": {"fit": {"type": "score", "score": 2, "confidence": 0.7, "probabilities": {"2": 0.7}}},
    }
    assert _http(Post(Response(body=ok))).ask("t", questions).answers["fit"]["value"] == 2.0
    bad = {**GOOD, "answers": {"fit": {"score": 3}}}
    with pytest.raises(jev.JevInvalid):
        _http(Post(Response(body=bad))).ask("t", questions)


def test_an_http_error_is_unavailable_and_says_only_the_status():
    post = Post(Response(status=429, body={"error": {"message": "secret detail"}}))
    with pytest.raises(jev.JevUnavailable) as caught:
        _http(post).ask("Hello", QUESTIONS)
    assert str(caught.value) == "HTTP 429" and caught.value.status == "unavailable"
    usage = caught.value.usage  # a sent call is charged as one estimated call
    assert usage.calls == 1 and usage.cost_estimated and usage.cost_usd >= jev.MIN_CALL_USD


def test_a_network_error_is_unavailable_without_its_message():
    post = Post(error=requests.ConnectionError(f"https://x.test/?key={KEY}"))
    with pytest.raises(jev.JevUnavailable) as caught:
        _http(post).ask("Hello", QUESTIONS)
    assert str(caught.value) == "ConnectionError"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True
    assert KEY not in repr(caught.value)


def test_a_body_that_is_not_json_is_invalid():
    with pytest.raises(jev.JevInvalid):
        _http(Post(Response(json_error=True))).ask("Hello", QUESTIONS)


def test_without_a_key_nothing_is_sent():
    post = Post()
    with pytest.raises(jev.JevUnavailable):
        _http(post, key="").ask("Hello", QUESTIONS)
    assert post.calls == []


def test_the_client_never_shows_its_key():
    assert KEY not in repr(_http(Post()))


@pytest.mark.parametrize("url", ["http://decisions.example.test/v1", "decisions.example.test", ""])
def test_the_client_needs_an_https_url(url):
    with pytest.raises(ValueError):
        jev.HttpJev(url, KEY, "jev-latest", post=Post())


def _prices(monkeypatch, usd_in: str | None = None, usd_out: str | None = None) -> None:
    for name, value in (("NM_JEV_USD_PER_MTOK_IN", usd_in), ("NM_JEV_USD_PER_MTOK_OUT", usd_out)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def test_without_a_reported_cost_the_tokens_are_priced(monkeypatch):
    _prices(monkeypatch, usd_in="10")
    body = {**GOOD, "usage": {"input_tokens": 210, "output_tokens": 9}}  # what the hosted endpoint sends
    reply = _http(Post(Response(body=body))).ask("Hello", QUESTIONS)
    assert (reply.input_tokens, reply.output_tokens) == (210, 9)
    assert (
        reply.cost_usd == Decimal("0.002235") and reply.cost_estimated is True
    )  # 210 x 10 + 9 x 15 per Mtok


def test_a_priced_call_costs_at_least_the_floor(monkeypatch):
    _prices(monkeypatch)
    body = {**GOOD, "usage": {"input_tokens": 210, "output_tokens": 9, "cost": 0}}
    reply = _http(Post(Response(body=body))).ask("Hello", QUESTIONS)
    assert reply.cost_usd == jev.MIN_CALL_USD and reply.cost_estimated is True


def test_bad_usage_is_estimated(monkeypatch):
    _prices(monkeypatch)
    body = {**GOOD, "usage": {"input_tokens": -3, "output_tokens": "9", "cost": "free"}}
    reply = _http(Post(Response(body=body))).ask("x" * 400, QUESTIONS)
    assert reply.input_tokens > 100  # a quarter of the text plus the questions
    assert reply.output_tokens == 2 * jev.OUTPUT_TOKENS_PER_QUESTION
    assert reply.cost_estimated is True and reply.cost_usd >= jev.MIN_CALL_USD


def test_prices_have_conservative_defaults(monkeypatch):
    from app import settings

    _prices(monkeypatch, usd_in="nonsense", usd_out="-1")
    assert (settings.jev_usd_per_mtok_in(), settings.jev_usd_per_mtok_out()) == (3.0, 15.0)
    _prices(monkeypatch, usd_in="inf", usd_out="0")
    assert (settings.jev_usd_per_mtok_in(), settings.jev_usd_per_mtok_out()) == (3.0, 15.0)


def test_cost_is_rounded_up_to_whole_cents():
    assert jev.cost_minor(Decimal("0.000123")) == 1
    assert jev.cost_minor(Decimal("0.0201")) == 3
    assert jev.cost_minor(Decimal("0.02")) == 2
    assert jev.cost_minor(Decimal(0)) == 0


def _fake(answers: dict) -> jev.FakeJev:
    return jev.FakeJev(answer_for=lambda name: (lambda state: answers[name]) if name in answers else None)


def test_the_fake_client_answers_through_the_same_normalisation():
    reply = _fake({"is_lead": {"noul": 0.2}, "urgency": {"choice": "normal"}}).ask("Hi", QUESTIONS)
    assert reply.answers["is_lead"] == {"value": 0.2}
    assert reply.answers["urgency"]["value"] == "normal" and reply.cost_usd == jev.FAKE_COST_USD
    with pytest.raises(jev.JevUnavailable):
        _fake({"is_lead": {"noul": 0.2}}).ask("Hi", QUESTIONS)  # no fake answer for urgency


def test_the_off_client_refuses():
    with pytest.raises(jev.JevOff) as caught:
        jev.OffJev().ask("Hi", QUESTIONS)
    assert caught.value.status == "off"


def test_ask_all_keeps_item_order():
    client = jev.FakeJev(answer_for=lambda name: lambda state: {"noul": 0.9 if "buy" in state else 0.1})
    questions = {"is_lead": QUESTIONS["is_lead"]}
    replies = jev.ask_all(client, ["hello", "I want to buy", "spam"], questions)
    assert [r.answers["is_lead"]["value"] for r in replies] == [0.1, 0.9, 0.1]
    assert jev.ask_all(client, [], questions) == []


def test_ask_all_refuses_more_than_the_item_limit_without_calling():
    post = Post()
    with pytest.raises(jev.JevTooMany):
        jev.ask_all(_http(post), ["x"] * (jev.MAX_ITEMS + 1), QUESTIONS)
    assert post.calls == []


def test_ask_all_gives_up_at_its_deadline():
    class Slow:
        def ask(self, state, questions):
            time.sleep(1.0)
            raise AssertionError("never used")

    started = time.monotonic()
    with pytest.raises(jev.JevUnavailable, match="timed out"):
        jev.ask_all(Slow(), ["a", "b"], QUESTIONS, deadline_s=0.2)
    assert time.monotonic() - started < 0.9


def test_a_timeout_carries_the_usage_so_far():
    class Partly:
        def ask(self, state, questions):
            if state == "slow":
                time.sleep(1.0)
            return jev.Reply({}, 100, 10, Decimal("0.01"))

    with pytest.raises(jev.JevUnavailable, match="timed out") as caught:
        jev.ask_all(Partly(), ["fast", "slow", "fast"], QUESTIONS, deadline_s=0.3)
    usage = caught.value.usage
    assert usage.calls == 3  # two finished, one still in flight and charged as an estimate
    assert usage.input_tokens > 200 and usage.output_tokens == 20 + 2 * jev.OUTPUT_TOKENS_PER_QUESTION
    assert usage.cost_usd >= Decimal("0.02") + jev.MIN_CALL_USD and usage.cost_estimated is True


def test_ask_all_turns_an_unexpected_error_into_unavailable():
    class Broken:
        def ask(self, state, questions):
            raise KeyError("answers")

    with pytest.raises(jev.JevUnavailable, match="KeyError"):
        jev.ask_all(Broken(), ["a"], QUESTIONS)


def test_the_first_failure_in_item_order_wins():
    class Mixed:
        def ask(self, state, questions):
            if state == "bad":
                raise jev.JevInvalid(
                    "answer outside its question", usage=jev.Usage(1, 50, 5, Decimal("0.002"))
                )
            return jev.Reply({"is_lead": {"value": 0.5}}, 100, 10, Decimal("0.01"))

    with pytest.raises(jev.JevInvalid, match="answer outside") as caught:
        jev.ask_all(Mixed(), ["ok", "bad", "ok"], QUESTIONS)
    assert caught.value.usage == jev.Usage(3, 250, 25, Decimal("0.022"))  # every finished call is summed


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"NM_JEV": "off", "NM_MODEL_ENV": "test"}, jev.OffJev),
        ({"NM_JEV": "fake", "NM_MODEL_ENV": "prod"}, jev.FakeJev),
        ({"NM_JEV": "live", "NM_MODEL_ENV": "test"}, jev.HttpJev),
        ({"NM_MODEL_ENV": "test"}, jev.FakeJev),
        ({"NM_MODEL_ENV": "prod", "JEV_API_KEY": KEY}, jev.HttpJev),
        ({"NM_MODEL_ENV": "prod"}, jev.OffJev),
        ({"NM_JEV": "yes", "NM_MODEL_ENV": "test"}, jev.OffJev),  # set but not recognised
        ({"NM_JEV": "live", "NM_JEV_URL": "http://decisions.example.test", "JEV_API_KEY": KEY}, jev.OffJev),
    ],
)
def test_the_client_follows_the_flag(monkeypatch, env, expected):
    for name in ("NM_JEV", "NM_MODEL_ENV", "JEV_API_KEY", "NM_JEV_URL", "NM_JEV_MODEL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert isinstance(jev.client(), expected)


def test_a_live_flag_with_a_url_that_is_not_https_warns(monkeypatch, caplog):
    url = "http://decisions.example.test/v1"
    monkeypatch.setenv("NM_JEV", "live")
    monkeypatch.setenv("NM_JEV_URL", url)
    monkeypatch.setenv("JEV_API_KEY", KEY)
    with caplog.at_level("WARNING", logger=jev.__name__):
        assert isinstance(jev.client(), jev.OffJev)
    [record] = [r for r in caplog.records if r.name == jev.__name__]
    assert record.levelname == "WARNING" and "not https" in record.getMessage()
    assert url not in caplog.text and "decisions.example.test" not in caplog.text and KEY not in caplog.text


def test_the_default_endpoint_and_model(monkeypatch):
    from app import settings

    monkeypatch.delenv("NM_JEV_URL", raising=False)
    monkeypatch.delenv("NM_JEV_MODEL", raising=False)
    assert settings.jev_url() == "https://api.typesafe.ai/v1/systemone"
    assert settings.jev_model() == "jev-latest"
