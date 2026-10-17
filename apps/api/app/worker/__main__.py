"""Worker entrypoint: `uv run python -m app.worker` (reads TEMPORAL_*, NM_* and the model/connector keys
from the environment; load demo-app/.env with `uv run --env-file ../../.env python -m app.worker`)."""

import asyncio
import logging
import signal
import sys
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from app import db, settings
from app.runtime import tracing
from app.temporal_client import connect  # one set of connection rules for the API and the worker
from app.worker.runtime import activity_threads, build_worker

log = logging.getLogger("app.worker")

# The shutdown task, held until it is done: a task nobody references can be garbage-collected mid-way.
_stopping: set[asyncio.Task] = set()


async def main() -> None:
    client = await connect()
    try:
        await _serve(client)
    finally:
        db.reset_pool()  # close Postgres connections before the interpreter shuts down
        tracing.shutdown()  # send the model-call traces still batched


async def _serve(client: Client) -> None:
    with ThreadPoolExecutor(max_workers=activity_threads()) as pool:
        worker = build_worker(client, pool)
        _stop_on_signal(worker)
        log.info(
            "worker polling %s on %s (namespace %s, models %s, connectors %s)",
            settings.task_queue(),
            settings.temporal_target(),
            settings.temporal_namespace(),
            settings.model_env(),
            settings.connector_mode(),
        )
        await worker.run()


def _stop_on_signal(worker: Worker) -> None:
    """SIGTERM (containers, `kill`) and, on Windows, Ctrl+Break stop the worker gracefully: running
    activities finish within the graceful timeout, then `main` closes the pool and sends the traces."""
    loop = asyncio.get_running_loop()

    def begin() -> None:
        task = loop.create_task(worker.shutdown())
        _stopping.add(task)
        task.add_done_callback(_stopping.discard)

    def stop(*_: object) -> None:
        log.info("stop requested; finishing the running activities")
        loop.call_soon_threadsafe(begin)

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, stop)  # Windows has no SIGTERM; a parent sends CTRL_BREAK_EVENT
    else:
        loop.add_signal_handler(signal.SIGTERM, stop)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("worker stopped")
