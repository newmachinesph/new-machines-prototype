"""The PackRunner worker hosted inside the API process (NM_EMBEDDED_WORKER=1 with NM_RUNTIME=temporal).

It runs on its own thread with its own event loop, apart from both uvicorn's loop and the API's Temporal
client loop, so workflow tasks and the sync activities (a ThreadPoolExecutor, as in the standalone worker)
never delay a request. The supervisor reconnects with backoff when the worker or its connection fails, so
a Temporal outage never blocks or crashes the API.
"""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from app import settings
from app.temporal_client import connect
from app.worker.runtime import activity_threads, build_worker

log = logging.getLogger("app.worker.embedded")

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0
STABLE_AFTER_S = 60.0  # a worker that ran this long starts its next backoff over
STOP_TIMEOUT_S = 8.0  # Cloud Run sends SIGKILL 10 s after SIGTERM


class EmbeddedWorker:
    def __init__(
        self,
        connector: Callable[[], Awaitable[Client]] = connect,
        factory: Callable[[Client, ThreadPoolExecutor], Worker] = build_worker,
    ) -> None:
        self._connector = connector
        self._factory = factory
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._running = False
        self.attempts = 0

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._thread_main, name="embedded-worker", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> bool:
        """Ask the worker to stop and wait up to STOP_TIMEOUT_S. True when its thread has ended."""
        thread, loop, stop = self._thread, self._loop, self._stop
        if thread is None:
            return True
        if loop is not None and stop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop.set)
        thread.join(timeout=STOP_TIMEOUT_S)
        if thread.is_alive():
            log.warning("embedded worker did not stop within %ss", STOP_TIMEOUT_S)
            return False
        self._thread = None
        return True

    def _thread_main(self) -> None:
        asyncio.run(self._supervise())

    async def _supervise(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._ready.set()
        delay = BACKOFF_START_S
        while not self._stop.is_set():
            self.attempts += 1
            started = self._loop.time()
            try:
                await self._run_once()
            except Exception:  # never crash the API; log (no secrets in the message) and retry
                log.exception("embedded worker failed; retrying in %.0fs", delay)
            finally:
                self._running = False
            if self._stop.is_set():
                break
            if self._loop.time() - started >= STABLE_AFTER_S:
                delay = BACKOFF_START_S
            await self._sleep_or_stop(delay)
            delay = min(delay * 2, BACKOFF_MAX_S)

    async def _sleep_or_stop(self, seconds: float) -> None:
        assert self._stop is not None
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    async def _run_once(self) -> None:
        assert self._stop is not None
        connecting = asyncio.ensure_future(self._connector())
        stopping = asyncio.ensure_future(self._stop.wait())
        try:
            await asyncio.wait({connecting, stopping}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopping.cancel()
            if not connecting.done():
                connecting.cancel()  # a stop never waits for a connect that is hanging
        if connecting.cancelled() or not connecting.done():
            with contextlib.suppress(asyncio.CancelledError):
                await connecting
            return
        client = connecting.result()
        # No `with`: leaving it would block on activity threads still running after the graceful timeout.
        pool = ThreadPoolExecutor(max_workers=activity_threads(), thread_name_prefix="activity")
        try:
            worker = self._factory(client, pool)
            runner = asyncio.create_task(worker.run())
            stopper = asyncio.create_task(self._stop.wait())
            self._running = True
            log.info("embedded worker polling")
            try:
                await asyncio.wait({runner, stopper}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                if not runner.done():
                    await worker.shutdown()
                stopper.cancel()
            await runner  # re-raises a worker failure so the supervisor logs and retries
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


_current: EmbeddedWorker | None = None


def start_embedded() -> EmbeddedWorker:
    global _current
    if settings.worker_concurrency() >= settings.db_pool_max():
        log.warning(
            "NM_WORKER_CONCURRENCY (%d) is not below NM_DB_POOL_MAX (%d): with the API sharing the pool, "
            "requests can starve while every activity holds a connection",
            settings.worker_concurrency(),
            settings.db_pool_max(),
        )
    _current = EmbeddedWorker()
    _current.start()
    return _current


def stop_embedded() -> bool:
    """Stop the embedded worker; False when its thread is still running (it may still use the DB pool)."""
    global _current
    worker, _current = _current, None
    return True if worker is None else worker.stop()


def current() -> EmbeddedWorker | None:
    return _current
