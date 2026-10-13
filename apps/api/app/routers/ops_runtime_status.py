"""Operator console: is the runtime up? Database, Temporal and the embedded worker, with no secrets.

Both probes run at once and each is bounded, so the route answers within a few seconds even in an outage."""

import logging
from concurrent.futures import ThreadPoolExecutor, wait

from app import db, settings, temporal_client
from app.auth import CurrentOps
from app.models.ops import RuntimeStatus
from app.routing import ApiRouter

log = logging.getLogger(__name__)

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

PROBE_TIMEOUT_S = 3.0


def _database() -> int:
    return db.probe(PROBE_TIMEOUT_S)


def _temporal() -> None:
    temporal_client.system_info(PROBE_TIMEOUT_S)


def _worker() -> str:
    if not (settings.runtime_enabled() and settings.embedded_worker()):
        return "not_embedded"
    from app.worker import embedded  # loads the worker modules only when a worker is configured

    current = embedded.current()
    return "running" if current is not None and current.running else "stopped"


def _probe_both() -> tuple[bool, int, bool]:
    """(database reachable, definitions applied, temporal reachable). A probe that fails or is still running
    after its bound counts as an error; only the exception type is logged (messages can carry secrets)."""
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="status-probe")
    try:
        futures = {"database": pool.submit(_database), "temporal": pool.submit(_temporal)}
        # One deadline shared by both probes, so two hung probes cost one bound, not two.
        wait(futures.values(), timeout=PROBE_TIMEOUT_S + 1)
        results: dict[str, object] = {}
        for name, future in futures.items():
            if not future.done():
                log.warning("runtime status: %s check did not finish in time", name)
                continue
            try:
                results[name] = future.result()
            except Exception as exc:
                log.warning("runtime status: %s check failed (%s)", name, type(exc).__name__)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    applied = results.get("database")
    return "database" in results, applied if isinstance(applied, int) else 0, "temporal" in results


@router.get("/runtime/status", operation_id="opsGetRuntimeStatus", response_model=RuntimeStatus)
def ops_get_runtime_status(_: CurrentOps) -> RuntimeStatus:
    workspace = "live" if settings.workspace_mode() == "live" else "demo"
    if not settings.runtime_enabled():
        return RuntimeStatus(
            runtime="off",
            workspace=workspace,
            database="off",
            temporal="off",
            worker="not_embedded",
            definitions_applied=0,
        )
    database_ok, applied, temporal_ok = _probe_both()
    return RuntimeStatus(
        runtime="on",
        workspace=workspace,
        database="ok" if database_ok else "error",
        temporal="ok" if temporal_ok else "error",
        worker=_worker(),
        definitions_applied=applied,
    )
