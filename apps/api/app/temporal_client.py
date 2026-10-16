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
    """Connect to TEMPORAL_TARGET / TEMPORAL_NAMESPACE. With TEMPORAL_API_KEY set the connection uses TLS and
    the key, whatever the host (tmprl.cloud:7233 or a regional *.api.temporal.io:7233); without one it is
    plaintext, which is the local dev server.

    Both carry GoogleAdkPlugin (ADK's payload converter and sandbox passthrough); workers built from the
    client inherit it. Imported here, not at module load: google.adk takes seconds to import."""
    from temporalio.contrib.google_adk_agents import GoogleAdkPlugin

    target, namespace = settings.temporal_target(), settings.temporal_namespace()
    api_key = settings.temporal_api_key()
    if api_key:
        return await Client.connect(
            target, namespace=namespace, api_key=api_key, tls=True, plugins=[GoogleAdkPlugin()]
        )
    if target.endswith(CLOUD_SUFFIX):
        raise RuntimeError("TEMPORAL_API_KEY is required for a Temporal Cloud namespace")
    return await Client.connect(target, namespace=namespace, plugins=[GoogleAdkPlugin()])


def _background_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="temporal-client", daemon=True).start()
            _loop = loop
        return _loop


def _result[T](future: Future[T], timeout: float | None = None) -> T:
    """Wait for `future`; on a timeout (or any other failure) cancel it, so the call never completes later,
    for example a workflow start after the API has already failed the run."""
    try:
        return future.result(timeout=CALL_TIMEOUT_S if timeout is None else timeout)
    except BaseException:
        future.cancel()
        raise


def _wait[T](coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    return _result(asyncio.run_coroutine_threadsafe(coro, _background_loop()), timeout)


def _drop_connect(future: Future) -> None:
    """Forget a failed (or abandoned) connect so the next call starts a new one."""
    global _connecting
    with _lock:
        if _connecting is future:
            _connecting = None


def get_client(timeout: float | None = None) -> Client:
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
        # A caller that chose its own short bound only stops waiting; the shared connect keeps going for
        # the other waiters, and the next call caches the client once it lands.
        client = _result(future) if timeout is None else future.result(timeout=timeout)
    except TimeoutError:
        if timeout is None:
            _drop_connect(future)
        raise
    except BaseException:
        _drop_connect(future)
        raise
    with _lock:
        if _client is None:
            _client, _connecting = client, None
        return _client


def system_info(timeout: float = 3.0) -> None:
    """Round-trip to the Temporal service (connecting first if needed), failing within about `timeout`
    seconds for each of the two steps. Raises on any failure; used by the ops status route."""
    from datetime import timedelta

    from temporalio.api.workflowservice.v1 import GetSystemInfoRequest

    client = get_client(timeout)
    _wait(
        client.workflow_service.get_system_info(GetSystemInfoRequest(), timeout=timedelta(seconds=timeout)),
        timeout,
    )


def workflow_id(run_id: str) -> str:
    """The Temporal workflow id of a run: the run id behind NM_WORKFLOW_ID_PREFIX. Built only here."""
    return f"{settings.workflow_id_prefix()}{run_id}"


def start_run(run_id: str, snapshot: dict, input: dict) -> None:
    """Start PackRunner with workflow id = workflow_id(run id). The input carries the bare run id: the
    worker records events against it, so only Temporal's own id has the prefix."""
    from app.worker.workflow import RunInput  # the worker modules load only when a real run starts

    client = get_client()
    _wait(
        client.start_workflow(
            WORKFLOW,
            RunInput(run_id=run_id, snapshot=snapshot, input=input),
            id=workflow_id(run_id),
            task_queue=settings.task_queue(),
        )
    )


def signal_human(
    run_id: str, task_id: str, outcome: str, note: str, resolutions: list[dict] | None = None
) -> None:
    """`human_result(task_id, outcome resolved|rejected, note, resolutions)`."""
    handle = get_client().get_workflow_handle(workflow_id(run_id))
    _wait(handle.signal("human_result", args=[task_id, outcome, note, resolutions or []]))


def terminate_run(run_id: str, reason: str) -> None:
    """Terminate the run's workflow (a start the API gave up on). Raises when there is no such workflow."""
    handle = get_client().get_workflow_handle(workflow_id(run_id))
    _wait(handle.terminate(reason=reason))


def signal_approval(run_id: str, task_id: str, decision: str, by: str) -> None:
    """`approval(task_id, decision granted|denied, by)`."""
    handle = get_client().get_workflow_handle(workflow_id(run_id))
    _wait(handle.signal("approval", args=[task_id, decision, by]))
