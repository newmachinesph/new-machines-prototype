"""Temporal access for the API: start PackRunner runs and signal their human tasks and approvals.

Routes are sync and run in Starlette's threadpool, while the Temporal client is async and bound to the loop
it connected on. So the client lives on one private event loop in a daemon thread, and the functions below
submit coroutines to it and wait for the result.
"""

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

from temporalio.client import Client

from app import settings

CLOUD_SUFFIX = "tmprl.cloud:7233"
CALL_TIMEOUT_S = 15
WORKFLOW = "PackRunner"

_loop: asyncio.AbstractEventLoop | None = None
_client: Client | None = None
_connecting: Future | None = None
_lock = threading.Lock()


async def connect() -> Client:
    """Connect to TEMPORAL_TARGET / TEMPORAL_NAMESPACE; Temporal Cloud uses TEMPORAL_API_KEY over TLS."""
    target, namespace = settings.temporal_target(), settings.temporal_namespace()
    if not target.endswith(CLOUD_SUFFIX):
        return await Client.connect(target, namespace=namespace)
    api_key = settings.temporal_api_key()
    if not api_key:
        raise RuntimeError("TEMPORAL_API_KEY is required for a Temporal Cloud namespace")
    return await Client.connect(target, namespace=namespace, api_key=api_key, tls=True)


def _background_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="temporal-client", daemon=True).start()
            _loop = loop
        return _loop


def _result[T](future: Future[T]) -> T:
    """Wait for `future`; on a timeout (or any other failure) cancel it, so the call never completes later,
    for example a workflow start after the API has already failed the run."""
    try:
        return future.result(timeout=CALL_TIMEOUT_S)
    except BaseException:
        future.cancel()
        raise


def _wait[T](coro: Coroutine[Any, Any, T]) -> T:
    return _result(asyncio.run_coroutine_threadsafe(coro, _background_loop()))


def get_client() -> Client:
    """The API's Temporal client: connected on first use, then cached. Concurrent first calls share one
    connection attempt; the module lock is never held while it runs."""
    global _client, _connecting
    loop = _background_loop()
    with _lock:
        if _client is not None:
            return _client
        if _connecting is None:
            _connecting = asyncio.run_coroutine_threadsafe(connect(), loop)
        future = _connecting
    try:
        client = _result(future)
    except BaseException:
        with _lock:
            if _connecting is future:
                _connecting = None
        raise
    with _lock:
        if _client is None:
            _client, _connecting = client, None
        return _client


def start_run(run_id: str, snapshot: dict, input: dict) -> None:
    """Start PackRunner with workflow id = run id."""
    from app.worker.workflow import RunInput  # the worker modules load only when a real run starts

    client = get_client()
    _wait(
        client.start_workflow(
            WORKFLOW,
            RunInput(run_id=run_id, snapshot=snapshot, input=input),
            id=run_id,
            task_queue=settings.task_queue(),
        )
    )


def signal_human(
    run_id: str, task_id: str, outcome: str, note: str, resolutions: list[dict] | None = None
) -> None:
    """`human_result(task_id, outcome resolved|rejected, note, resolutions)`."""
    handle = get_client().get_workflow_handle(run_id)
    _wait(handle.signal("human_result", args=[task_id, outcome, note, resolutions or []]))


def terminate_run(run_id: str, reason: str) -> None:
    """Terminate the run's workflow (a start the API gave up on). Raises when there is no such workflow."""
    handle = get_client().get_workflow_handle(run_id)
    _wait(handle.terminate(reason=reason))


def signal_approval(run_id: str, task_id: str, decision: str, by: str) -> None:
    """`approval(task_id, decision granted|denied, by)`."""
    handle = get_client().get_workflow_handle(run_id)
    _wait(handle.signal("approval", args=[task_id, decision, by]))
