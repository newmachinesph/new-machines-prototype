"""Worker construction shared by `python -m app.worker` and the embedded worker."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker

from app import settings
from app.runtime import adk_agent
from app.worker.activities import PackActivities
from app.worker.workflow import PackRunner

GRACEFUL_SHUTDOWN = timedelta(seconds=5)  # Cloud Run gives a container 10 s after SIGTERM


def activity_threads() -> int:
    """One pooled DB connection per concurrent activity, so never more threads than the pool holds."""
    return min(settings.worker_concurrency(), settings.db_pool_max())


def build_worker(client: Client, executor: ThreadPoolExecutor) -> Worker:
    """The client carries GoogleAdkPlugin (see temporal_client.connect); the Worker inherits it."""
    adk_agent.warm_up()  # ADK's first-turn imports happen here, not inside a workflow activation
    return Worker(
        client,
        task_queue=settings.task_queue(),
        workflows=[PackRunner],
        activities=PackActivities().all(),
        activity_executor=executor,
        max_concurrent_activities=activity_threads(),  # never more activities than threads or connections
        graceful_shutdown_timeout=GRACEFUL_SHUTDOWN,
    )
