"""Worker entrypoint: `uv run python -m app.worker` (reads TEMPORAL_*, NM_* and the model/connector keys
from the environment; load demo-app/.env with `uv run --env-file ../../.env python -m app.worker`)."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from app import db, settings
from app.temporal_client import connect  # one set of connection rules for the API and the worker
from app.worker.activities import PackActivities
from app.worker.workflow import PackRunner

ACTIVITY_THREADS = db.POOL_MAX_SIZE  # one pooled DB connection per concurrent activity

log = logging.getLogger("app.worker")


async def main() -> None:
    client = await connect()
    try:
        await _serve(client)
    finally:
        db.reset_pool()  # close Postgres connections before the interpreter shuts down


def build_worker(client: Client, executor: ThreadPoolExecutor) -> Worker:
    return Worker(
        client,
        task_queue=settings.task_queue(),
        workflows=[PackRunner],
        activities=PackActivities().all(),
        activity_executor=executor,
        max_concurrent_activities=ACTIVITY_THREADS,  # never more activities than threads or connections
    )


async def _serve(client: Client) -> None:
    with ThreadPoolExecutor(max_workers=ACTIVITY_THREADS) as pool:
        worker = build_worker(client, pool)
        log.info(
            "worker polling %s on %s (namespace %s, models %s, connectors %s)",
            settings.task_queue(),
            settings.temporal_target(),
            settings.temporal_namespace(),
            settings.model_env(),
            settings.connector_mode(),
        )
        await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("worker stopped")
