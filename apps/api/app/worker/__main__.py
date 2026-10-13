"""Worker entrypoint: `uv run python -m app.worker` (reads TEMPORAL_*, NM_* and the model/connector keys
from the environment; load demo-app/.env with `uv run --env-file ../../.env python -m app.worker`)."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client

from app import db, settings
from app.temporal_client import connect  # one set of connection rules for the API and the worker
from app.worker.runtime import activity_threads, build_worker

log = logging.getLogger("app.worker")


async def main() -> None:
    client = await connect()
    try:
        await _serve(client)
    finally:
        db.reset_pool()  # close Postgres connections before the interpreter shuts down


async def _serve(client: Client) -> None:
    with ThreadPoolExecutor(max_workers=activity_threads()) as pool:
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
