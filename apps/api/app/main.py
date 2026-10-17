import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, settings, workspace
from app.auth import check_auth_config
from app.defs.loader import LoadError, load_bundle
from app.defs.model import Bundle
from app.defs.registry import apply_bundle
from app.defs.validate import validate_bundle
from app.errors import document_problem_json, install_error_handlers
from app.runtime import tracing

log = logging.getLogger(__name__)


def allowed_origins() -> list[str]:
    """`ALLOWED_ORIGINS` is comma separated; entries are trimmed and lose a trailing slash, which the browser
    never sends in an `Origin` header."""
    raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3100").split(",")
    return [o.strip().rstrip("/") for o in raw if o.strip().rstrip("/")]


def valid_bundle(root: Path) -> Bundle | None:
    """The definition files under `root`, or None (with the problems logged) when they do not load or do not
    validate: a broken file must never be pinned into new runs."""
    try:
        bundle = load_bundle(root)
    except (LoadError, OSError) as exc:
        log.error("Startup: definition files in %s were not applied: %s", root, exc)
        return None
    try:
        errors = validate_bundle(bundle)
    except OSError as exc:
        log.error("Startup: definition schemas could not be read, so no files were applied: %s", exc)
        return None
    for e in errors:
        log.error("Startup: invalid definition: %s", e)
    if errors:
        log.error("Startup: %d definition errors, so no definition files were applied.", len(errors))
        return None
    return bundle


def apply_definitions() -> None:
    """Migrate the database and publish the definition files as new versions where they changed. Files that
    fail validation are not applied; the API still starts and serves the versions already stored."""
    with db.connect() as conn:
        applied = db.migrate(conn)
        bundle = valid_bundle(settings.defs_dir())
        created = apply_bundle(conn, bundle) if bundle is not None else []
        conn.commit()
    log.info("Startup: %d migrations, %d new definition versions.", len(applied), len(created))


# Cloud Run sends SIGKILL 10 s after SIGTERM: stopping the worker and sending its traces share this budget.
SHUTDOWN_BUDGET_S = 9.0


def _send_traces(worker_stopped: bool, budget_s: float) -> None:
    """Send the embedded worker's model-call traces still batched, within what is left of the shutdown budget.
    A worker that did not stop keeps its client: a model call still in flight must not build a second one."""
    timeout = max(1.0, min(tracing.FLUSH_TIMEOUT_S, budget_s))
    if worker_stopped:
        tracing.shutdown(timeout)
    else:
        tracing.flush(timeout)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """With NM_DEFS_AUTO_APPLY on, the server applies migrations and definition files before serving; with
    NM_EMBEDDED_WORKER on (and the runtime on) it then starts the PackRunner worker in-process. On shutdown
    the worker's model-call traces are sent, then the Postgres pool (opened on first use) is closed."""
    if settings.defs_auto_apply():
        apply_definitions()
    embedded = settings.runtime_enabled() and settings.embedded_worker()
    if embedded:
        from app.worker.embedded import start_embedded

        start_embedded()  # its own thread and loop; a failure is logged and retried, never raised here
    worker_stopped = True
    try:
        yield
    finally:
        if embedded:
            from app.worker.embedded import stop_embedded

            started = asyncio.get_running_loop().time()
            worker_stopped = await asyncio.to_thread(stop_embedded)
            left = SHUTDOWN_BUDGET_S - (asyncio.get_running_loop().time() - started)
            await asyncio.to_thread(_send_traces, worker_stopped, left)
        if worker_stopped:
            db.reset_pool()
        else:
            log.warning("Shutdown: the embedded worker is still running, so the database pool stays open.")


def create_app() -> FastAPI:
    check_auth_config()
    workspace.check_config()
    app = FastAPI(
        title="New Machines API",
        version="0.1.0",
        separate_input_output_schemas=False,
        lifespan=lifespan,
    )
    origins = allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Every method a route serves: a browser preflights PUT and PATCH, and a missing one fails there only.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
        max_age=600,
    )
    install_error_handlers(app, origins)
    document_problem_json(app)

    @app.get("/healthz", operation_id="healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    from app.routers import (
        approvals,
        catalog,
        connections,
        mcp_servers,
        me,
        memory,
        ops_catalog,
        ops_definitions,
        ops_health,
        ops_listings,
        ops_memory,
        ops_overview,
        ops_people,
        ops_platform,
        ops_runs,
        ops_runtime_status,
        ops_tenants,
        org,
        publisher,
        reviewers,
        runs,
        studio,
        studio_earnings,
        studio_listings,
        tasks,
    )

    for module in (
        catalog,
        runs,
        approvals,
        tasks,
        memory,
        connections,
        mcp_servers,
        me,
        org,
        reviewers,
        studio,
        publisher,
        studio_listings,
        studio_earnings,
        ops_catalog,
        ops_listings,
        ops_definitions,
        ops_health,
        ops_memory,
        ops_overview,
        ops_people,
        ops_platform,
        ops_runs,
        ops_runtime_status,
        ops_tenants,
    ):
        app.include_router(module.router)

    return app


app = create_app()
