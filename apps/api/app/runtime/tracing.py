"""Model-call traces to Langfuse: one trace per run, one generation per agent model call.

Off unless LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are all set (`settings.langfuse_keys`);
off, nothing here imports the SDK. Never in the way of a run: every failure of this layer is logged at
warning, and the model call returns (or raises) exactly what it would with tracing off. What leaves the
process: the prompt (system + messages), the output blocks, token usage, the run's own cost and the ids in
`_metadata`. Never the snapshot, keys or connection tokens.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from temporalio import activity

from app import settings
from app.runtime.providers import ModelTurn

log = logging.getLogger("app.runtime.tracing")

MINOR_PER_MAJOR = 100  # cost_minor is USD cents (definitions/models.yaml)
MAX_STATUS_CHARS = 300  # as MAX_ERROR_CHARS in the activities: an error message is cut at the same length
FLUSH_TIMEOUT_S = 3.0  # the most a shutdown waits on the network (Cloud Run kills 10 s after SIGTERM)

# The first model calls of a worker arrive on several activity threads at once; the lock makes one of them
# build the client while the others wait for it instead of running untraced.
_lock = threading.Lock()
_client: Any | None = None
_started = False  # one attempt per process: a client that did not start is not retried on every call


class TracedCall(Protocol):
    """What a model call (the worker's ModelCall) shares with its trace."""

    run_id: str
    node_id: str
    step: int
    attempt: int
    profile: str
    system: str
    messages: list[dict]
    snapshot: dict


def client() -> Any | None:
    """The process's Langfuse client, built on first use; None with tracing off or when it did not start."""
    global _client, _started
    if _started:
        return _client
    with _lock:
        if not _started:
            keys = settings.langfuse_keys()
            if keys is not None:
                try:
                    _client = _connect(*keys)
                except Exception:
                    log.warning("model-call tracing is off: the tracing client did not start", exc_info=True)
            _started = True  # after the client: a reader outside the lock that sees it set sees the client
    return _client


def _connect(host: str, public_key: str, secret_key: str) -> Any:
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider

    # Its own tracer provider: the SDK would otherwise register itself as the process-wide OpenTelemetry
    # provider and export every span other libraries emit (the agent framework's, request bodies included).
    return Langfuse(public_key=public_key, secret_key=secret_key, host=host, tracer_provider=TracerProvider())


def reset(replacement: Any | None = None) -> None:
    """Forget the process client (tests); `replacement` stands in for one built from the settings."""
    global _client, _started
    with _lock:
        _client, _started = replacement, replacement is not None


def shutdown(timeout: float = FLUSH_TIMEOUT_S) -> None:
    """Send what is still batched and stop the client's threads, waiting at most `timeout`: the last thing a
    process does once nothing in it can make a model call any more (otherwise `flush`)."""
    global _client, _started
    with _lock:
        current, _client, _started = _client, None, False
    if current is not None:
        _bounded(current.shutdown, "shutdown", timeout)


def flush(timeout: float = FLUSH_TIMEOUT_S) -> None:
    """Send what is still batched and keep the client: model calls may still be running (an embedded worker
    that did not stop in time), and one of them must not build a second client."""
    current = _client
    if current is not None:
        _bounded(current.flush, "flush", timeout)


def _bounded(action: Callable[[], None], what: str, timeout: float) -> None:
    """Run the SDK call on its own thread and stop waiting for it after `timeout`: the thread is a daemon, so
    a network that never answers cannot hold the process either."""

    def run() -> None:
        try:
            action()
        except Exception:
            log.warning(
                "tracing %s failed; some model-call traces may not have been sent", what, exc_info=True
            )

    thread = threading.Thread(target=run, name=f"tracing-{what}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        log.warning(
            "tracing %s did not finish within %.1fs; some model-call traces may not have been sent",
            what,
            timeout,
        )


class Generation:
    """One model call's observation; `record` adds its outcome. Without an observation, every method is a
    no-op."""

    def __init__(self, observation: Any | None) -> None:
        self._observation = observation

    def record(self, turn: ModelTurn, cost_minor: int) -> None:
        if self._observation is None:
            return
        try:
            self._observation.update(
                output=turn.content,
                usage_details={"input": turn.input_tokens, "output": turn.output_tokens},
                # The run's own figure, so Langfuse shows it rather than a price inferred from the model name.
                cost_details={"total": cost_minor / MINOR_PER_MAJOR},
                metadata={"cost_minor": cost_minor},
            )
        except Exception:
            log.warning("a model-call trace is incomplete", exc_info=True)

    def fail(self, error: BaseException) -> None:
        if self._observation is None:
            return
        try:
            message = f"{type(error).__name__}: {error}"[:MAX_STATUS_CHARS]
            self._observation.update(level="ERROR", status_message=message)
        except Exception:
            log.warning("a model-call trace is incomplete", exc_info=True)

    def end(self) -> None:
        if self._observation is None:
            return
        try:
            self._observation.end()
        except Exception:
            log.warning("a model-call trace is incomplete", exc_info=True)


@contextmanager
def generation(call: TracedCall, model: str) -> Iterator[Generation]:
    """Trace the model call made in the body as a generation named after its node. The body's result and
    exceptions pass through unchanged; an exception is recorded at ERROR before it goes on."""
    gen = Generation(_start(call, model))
    try:
        yield gen
    except BaseException as error:
        gen.fail(error)
        gen.end()
        raise
    gen.end()


def _start(call: TracedCall, model: str) -> Any | None:
    langfuse = client()
    if langfuse is None:
        return None
    try:
        from langfuse import propagate_attributes

        # Derived from the run id: every node and every retry of the run lands in the same trace.
        trace_id = langfuse.create_trace_id(seed=call.run_id)
        with propagate_attributes(
            session_id=call.run_id, tags=[settings.model_env()], trace_name=_trace_name(call)
        ):
            return langfuse.start_observation(
                trace_context={"trace_id": trace_id},
                name=call.node_id,
                as_type="generation",
                model=model,
                input={"system": call.system, "messages": call.messages},
                metadata=_metadata(call),
            )
    except Exception:
        log.warning("model call %s/%s is not traced", call.run_id, call.node_id, exc_info=True)
        return None


def _metadata(call: TracedCall) -> dict:
    meta = {
        "run_id": call.run_id,
        "node_id": call.node_id,
        "step": call.step,
        "attempt": call.attempt,
        "profile": call.profile,
    }
    extra = {"org_id": call.snapshot.get("org_id") or None, "activity_attempt": _activity_attempt()}
    return {**meta, **{k: v for k, v in extra.items() if v is not None}}


def _activity_attempt() -> int | None:
    """Temporal's own attempt of the activity (None outside one): a model call retried after a provider error
    is told apart from the node's `attempt`, which the workflow counts."""
    return activity.info().attempt if activity.in_activity() else None


def _trace_name(call: TracedCall) -> str:
    """`<pack slug> <run id>`: a run's snapshot pins exactly one pack."""
    pack = next(iter(call.snapshot.get("defs", {}).get("pack") or {}), None)
    return f"{pack} {call.run_id}" if pack else call.run_id
