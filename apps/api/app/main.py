import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import check_auth_config
from app.errors import document_problem_json, install_error_handlers


def allowed_origins() -> list[str]:
    """`ALLOWED_ORIGINS` is comma separated; entries are trimmed and lose a trailing slash, which the browser
    never sends in an `Origin` header."""
    raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3100").split(",")
    return [o.strip().rstrip("/") for o in raw if o.strip().rstrip("/")]


def create_app() -> FastAPI:
    check_auth_config()
    app = FastAPI(
        title="New Machines API",
        version="0.1.0",
        separate_input_output_schemas=False,
    )
    origins = allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "DELETE"],
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
        memory,
        ops_catalog,
        ops_health,
        ops_overview,
        ops_people,
        ops_platform,
        ops_tenants,
        org,
        runs,
        tasks,
    )

    for module in (
        catalog,
        runs,
        approvals,
        tasks,
        memory,
        connections,
        org,
        ops_catalog,
        ops_health,
        ops_overview,
        ops_people,
        ops_platform,
        ops_tenants,
    ):
        app.include_router(module.router)

    return app


app = create_app()
