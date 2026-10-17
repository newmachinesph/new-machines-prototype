"""Model-call traces: off without the Langfuse keys, one generation per model call grouped per run with them,
and never in the way of the model call's result or error."""

import hashlib
import logging
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

from app import settings
from app.defs.loader import load_bundle
from app.runtime import tracing
from app.runtime.providers import FakeProvider, ModelTurn
from app.worker import activities
from app.worker.activities import ModelCall, PackActivities

AGENT = "x-agent"
SYSTEM = f"agent:{AGENT}\nYou reconcile orders."
MESSAGES = [{"role": "user", "content": [{"type": "text", "text": "Reconcile the week."}]}]
# 400k input tokens at 125 cents/Mtok + 100k output at 1000 cents/Mtok (the `reasoning` profile) = 150 cents.
TURN = ModelTurn(
    content=[{"type": "text", "text": "Two mismatches."}],
    stop_reason="end_turn",
    input_tokens=400_000,
    output_tokens=100_000,
    model="fake-reasoning",
)
COST_MINOR = 150
KEYS = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")


# --- fixtures --------------------------------------------------------------------------------------


class FakeObservation:
    def __init__(self, **started) -> None:
        self.started = started
        self.updates: list[dict] = []
        self.ended = False

    def update(self, **fields):
        self.updates.append(fields)
        return self

    def end(self):
        self.ended = True
        return self


class FakeLangfuse:
    """What the tracing layer uses of the SDK client; nothing leaves the process."""

    def __init__(self) -> None:
        self.observations: list[FakeObservation] = []
        self.shutdowns = 0
        self.flushes = 0

    def create_trace_id(self, *, seed: str | None = None) -> str:
        return hashlib.sha256((seed or "").encode()).hexdigest()[:32]

    def start_observation(self, **fields) -> FakeObservation:
        observation = FakeObservation(**fields)
        self.observations.append(observation)
        return observation

    def shutdown(self) -> None:
        self.shutdowns += 1

    def flush(self) -> None:
        self.flushes += 1


class _FailingProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def call(self, **kwargs) -> ModelTurn:
        raise self.error


@pytest.fixture
def snapshot() -> dict:
    """A run snapshot with just what a model call reads: the model profiles and the pack it runs."""
    bundle = load_bundle(settings.defs_dir())
    models = bundle.items[("models", "default")].body
    return {
        "org_id": "org_demo",
        "defs": {"models": {"default": {"body": models}}, "pack": {"order-payment-reconciliation": {}}},
    }


@pytest.fixture
def no_commit(monkeypatch):
    """The activity's receipt write, kept out of these tests (they are about the trace, not the receipt)."""
    events: list = []
    monkeypatch.setattr(activities, "_commit", lambda call, evs, write=None: events.append(evs))
    return events


@pytest.fixture
def fake_langfuse():
    fake = FakeLangfuse()
    tracing.reset(fake)
    yield fake
    tracing.reset()


@pytest.fixture(autouse=True)
def _fresh_tracing(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NM_MODEL_ENV", "test")
    tracing.reset()
    yield
    tracing.reset()


def _call(snapshot: dict, run_id: str, node_id: str = "match", step: int = 1, attempt: int = 1) -> ModelCall:
    return ModelCall(
        run_id=run_id,
        snapshot=snapshot,
        node_id=node_id,
        attempt=attempt,
        step=step,
        profile="reasoning",
        system=SYSTEM,
        messages=MESSAGES,
        tools=[],
    )


def _acts(provider=None) -> PackActivities:
    return PackActivities(provider=provider or FakeProvider({AGENT: [TURN]}))


EXPECTED = {"content": TURN.content, "stop_reason": "end_turn", "cost_minor": COST_MINOR}
USAGE = {"input_tokens": 400_000, "output_tokens": 100_000, "cost_minor": COST_MINOR}


# --- off by default ----------------------------------------------------------------------------------


def test_without_the_keys_no_client_is_built_and_the_result_is_unchanged(snapshot, no_commit, monkeypatch):
    monkeypatch.setattr(tracing, "_connect", lambda *a: pytest.fail("a tracing client was built"))
    assert _acts().model_call(_call(snapshot, "run_a")) == EXPECTED
    assert tracing.client() is None
    assert no_commit == [[("model.usage", USAGE)]]


@pytest.mark.parametrize("missing", KEYS)
def test_one_missing_key_turns_tracing_off(monkeypatch, missing):
    for key in KEYS:
        monkeypatch.setenv(key, "value")
    assert settings.langfuse_keys() == ("value", "value", "value")
    monkeypatch.setenv(missing, "  ")
    assert settings.langfuse_keys() is None


def test_a_client_that_does_not_start_is_logged_once_and_tracing_stays_off(
    snapshot, no_commit, monkeypatch, caplog
):
    for key in KEYS:
        monkeypatch.setenv(key, "value")
    attempts = []

    def connect(*keys):
        attempts.append(keys)
        raise ConnectionError("no route")

    monkeypatch.setattr(tracing, "_connect", connect)
    with caplog.at_level(logging.WARNING, logger="app.runtime.tracing"):
        assert _acts().model_call(_call(snapshot, "run_a")) == EXPECTED
        assert _acts().model_call(_call(snapshot, "run_a", step=2)) == EXPECTED
    assert attempts == [("value", "value", "value")]
    assert "tracing client did not start" in caplog.text


def test_concurrent_first_calls_build_one_client(monkeypatch):
    """A worker's first model calls arrive on several activity threads at once: one client, shared by all."""
    for key in KEYS:
        monkeypatch.setenv(key, "value")
    built: list = []
    threads_n = 8
    gate = threading.Barrier(threads_n)

    def connect(*keys):
        built.append(keys)
        time.sleep(0.05)  # long enough for every other thread to arrive while this one builds
        return FakeLangfuse()

    monkeypatch.setattr(tracing, "_connect", connect)
    seen: list = [None] * threads_n

    def first_call(i: int) -> None:
        gate.wait()
        seen[i] = tracing.client()

    threads = [threading.Thread(target=first_call, args=(i,)) for i in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(built) == 1
    assert isinstance(seen[0], FakeLangfuse) and all(s is seen[0] for s in seen)


# --- with a client ----------------------------------------------------------------------------------


def test_each_model_call_is_one_generation_in_the_trace_of_its_run(snapshot, no_commit, fake_langfuse):
    acts = _acts()
    assert acts.model_call(_call(snapshot, "run_a", "match", step=1)) == EXPECTED
    assert acts.model_call(_call(snapshot, "run_a", "report", step=2, attempt=2)) == EXPECTED
    assert acts.model_call(_call(snapshot, "run_b", "match", step=1)) == EXPECTED

    first, second, other = fake_langfuse.observations
    assert [o.started["name"] for o in (first, second, other)] == ["match", "report", "match"]
    assert first.started["trace_context"] == second.started["trace_context"]
    assert first.started["trace_context"]["trace_id"] == fake_langfuse.create_trace_id(seed="run_a")
    assert other.started["trace_context"]["trace_id"] != first.started["trace_context"]["trace_id"]

    assert first.started["as_type"] == "generation"
    assert first.started["model"] == "fake-reasoning"
    assert first.started["input"] == {"system": SYSTEM, "messages": MESSAGES}
    assert first.started["metadata"] == {
        "run_id": "run_a",
        "node_id": "match",
        "step": 1,
        "attempt": 1,
        "profile": "reasoning",
        "org_id": "org_demo",
    }
    assert second.started["metadata"]["attempt"] == 2 and second.started["metadata"]["step"] == 2
    assert first.updates == [
        {
            "output": TURN.content,
            "usage_details": {"input": 400_000, "output": 100_000},
            "cost_details": {"total": 1.5},
            "metadata": {"cost_minor": COST_MINOR},
        }
    ]
    assert all(o.ended for o in fake_langfuse.observations)


def test_the_snapshot_and_tools_never_reach_the_trace(snapshot, no_commit, fake_langfuse):
    call = _call(snapshot, "run_a")
    call.tools = [{"name": "stripe.list_charges", "description": "d", "input_schema": {"type": "object"}}]
    _acts().model_call(call)
    [observation] = fake_langfuse.observations
    sent = {**observation.started, **{k: v for u in observation.updates for k, v in u.items()}}
    assert "snapshot" not in str(sent) and "stripe.list_charges" not in str(sent)
    assert set(observation.started) == {"trace_context", "name", "as_type", "model", "input", "metadata"}


def test_a_provider_error_is_recorded_and_re_raised_unchanged(snapshot, no_commit, fake_langfuse):
    error = RuntimeError("rate limited")
    with pytest.raises(RuntimeError) as raised:
        _acts(_FailingProvider(error)).model_call(_call(snapshot, "run_a"))
    assert raised.value is error
    assert no_commit == []
    [observation] = fake_langfuse.observations
    assert observation.updates == [{"level": "ERROR", "status_message": "RuntimeError: rate limited"}]
    assert observation.ended


def test_a_long_error_message_is_cut_as_the_receipt_cuts_it(snapshot, no_commit, fake_langfuse):
    assert tracing.MAX_STATUS_CHARS == activities.MAX_ERROR_CHARS
    with pytest.raises(RuntimeError):
        _acts(_FailingProvider(RuntimeError("x" * 1000))).model_call(_call(snapshot, "run_a"))
    [observation] = fake_langfuse.observations
    message = observation.updates[0]["status_message"]
    assert message.startswith("RuntimeError: xxx") and len(message) == activities.MAX_ERROR_CHARS


def test_inside_an_activity_the_metadata_carries_temporal_attempt(
    snapshot, no_commit, fake_langfuse, monkeypatch
):
    """A model call Temporal retried (a provider error) is told apart from the node's own attempt."""
    monkeypatch.setattr(tracing.activity, "in_activity", lambda: True)
    monkeypatch.setattr(tracing.activity, "info", lambda: SimpleNamespace(attempt=3))
    _acts().model_call(_call(snapshot, "run_a", attempt=1))
    [observation] = fake_langfuse.observations
    assert observation.started["metadata"]["activity_attempt"] == 3
    assert observation.started["metadata"]["attempt"] == 1


class _BrokenStart(FakeLangfuse):
    def start_observation(self, **fields):
        raise ValueError("broken start")


class _BrokenUpdate(FakeLangfuse):
    def start_observation(self, **fields):
        observation = super().start_observation(**fields)
        observation.update = lambda **_: (_ for _ in ()).throw(ValueError("broken update"))
        return observation


@pytest.mark.parametrize("broken", [_BrokenStart, _BrokenUpdate])
def test_a_tracing_failure_changes_nothing_about_the_call(snapshot, no_commit, caplog, broken):
    tracing.reset(broken())
    with caplog.at_level(logging.WARNING, logger="app.runtime.tracing"):
        assert _acts().model_call(_call(snapshot, "run_a")) == EXPECTED
        error = RuntimeError("still the provider's")
        with pytest.raises(RuntimeError) as raised:
            _acts(_FailingProvider(error)).model_call(_call(snapshot, "run_a", step=2))
    assert raised.value is error
    assert "broken" in caplog.text
    assert len(no_commit) == 1


def test_shutdown_sends_the_batched_traces_and_forgets_the_client(fake_langfuse):
    assert tracing.client() is fake_langfuse
    tracing.shutdown()
    assert fake_langfuse.shutdowns == 1
    assert tracing.client() is None  # the keys are unset: no new client
    tracing.shutdown()  # nothing to do, nothing raised


def test_shutdown_swallows_a_client_error(caplog):
    class Stuck(FakeLangfuse):
        def shutdown(self):
            raise TimeoutError("flush timed out")

    tracing.reset(Stuck())
    with caplog.at_level(logging.WARNING, logger="app.runtime.tracing"):
        tracing.shutdown()
    assert "may not have been sent" in caplog.text


def test_shutdown_stops_waiting_on_a_client_that_hangs(caplog):
    release = threading.Event()

    class Hanging(FakeLangfuse):
        def shutdown(self):
            release.wait(30)

    tracing.reset(Hanging())
    started = time.monotonic()
    try:
        with caplog.at_level(logging.WARNING, logger="app.runtime.tracing"):
            tracing.shutdown(timeout=0.2)
    finally:
        release.set()
    assert time.monotonic() - started < 2
    assert "did not finish within 0.2s" in caplog.text
    assert tracing.client() is None


def test_flush_sends_and_keeps_the_client(fake_langfuse):
    tracing.flush()
    assert fake_langfuse.flushes == 1 and fake_langfuse.shutdowns == 0
    assert tracing.client() is fake_langfuse


def test_the_api_keeps_the_client_while_its_worker_still_runs(monkeypatch):
    """The lifespan's last step: shutdown within the budget left after the worker stopped; only a flush (the
    client stays) when the worker is still running."""
    from app import main as api_main

    calls: list = []
    monkeypatch.setattr(tracing, "shutdown", lambda timeout: calls.append(("shutdown", timeout)))
    monkeypatch.setattr(tracing, "flush", lambda timeout: calls.append(("flush", timeout)))
    api_main._send_traces(True, 8.9)
    api_main._send_traces(True, 0.3)
    api_main._send_traces(False, 5.0)
    assert calls == [
        ("shutdown", tracing.FLUSH_TIMEOUT_S),
        ("shutdown", 1.0),
        ("flush", tracing.FLUSH_TIMEOUT_S),
    ]


# --- the SDK itself, exporting in memory --------------------------------------------------------------


def test_the_sdk_groups_the_run_under_one_trace_with_session_and_tag(snapshot, no_commit, monkeypatch):
    """The real client with an in-memory exporter (no network): the deterministic trace id, the run as the
    session, the model env as the tag and the generation fields all arrive on the exported spans."""
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=f"pk-test-{uuid.uuid4().hex[:8]}",  # the SDK keeps one resource set per public key
        secret_key="sk-test",
        host="http://127.0.0.1:9",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
    )
    tracing.reset(client)
    try:
        acts = _acts()
        acts.model_call(_call(snapshot, "run_a", "match", step=1))
        acts.model_call(_call(snapshot, "run_a", "report", step=2))
        client.flush()
    finally:
        tracing.shutdown()

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["match", "report"]
    assert {format(s.context.trace_id, "032x") for s in spans} == {Langfuse.create_trace_id(seed="run_a")}
    for span in spans:
        attributes = dict(span.attributes)
        assert attributes["session.id"] == "run_a"
        assert list(attributes["langfuse.trace.tags"]) == ["test"]
        assert attributes["langfuse.trace.name"] == "order-payment-reconciliation run_a"
        assert attributes["langfuse.observation.type"] == "generation"
        assert attributes["langfuse.observation.model.name"] == "fake-reasoning"
        assert attributes["langfuse.observation.usage_details"] == '{"input": 400000, "output": 100000}'
        assert attributes["langfuse.observation.cost_details"] == '{"total": 1.5}'
        assert attributes["langfuse.observation.metadata.cost_minor"] == COST_MINOR
