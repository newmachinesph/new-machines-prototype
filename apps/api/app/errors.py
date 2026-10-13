import logging
from collections.abc import Callable, Iterable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
log = logging.getLogger("app.errors")


class ProblemIssue(BaseModel):
    """One located error inside a problem (for example a definition validation error)."""

    kind: str
    key: str
    path: str
    message: str


class Problem(BaseModel):
    """RFC 9457 problem details with a stable machine code (API.md section 2)."""

    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str
    errors: list[ProblemIssue] | None = None  # only on INVALID_DEFINITION


class ApiProblem(Exception):
    def __init__(self, status: int, code: str, detail: str, errors: list[ProblemIssue] | None = None) -> None:
        self.status, self.code, self.detail, self.errors = status, code, detail, errors


TITLES = {
    400: "Bad request",
    401: "Sign in required",
    403: "Not allowed",
    404: "Not found",
    409: "Conflict",
    422: "Invalid request",
    500: "Server error",
    503: "Unavailable",
}
HTTP_CODES = {
    401: "AUTHENTICATION_REQUIRED",
    403: "TENANT_SCOPE_DENIED",
    404: "NOT_FOUND",
    405: "SCHEMA_INVALID",
    409: "CONFLICT",
}


# Declared on every route (see `ApiRouter`), so clients get a typed `Problem` error. Declaring 422 replaces
# FastAPI's default `HTTPValidationError`, which this API never sends.
ERROR_STATUSES = (401, 403, 404, 409, 422)
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": Problem, "description": TITLES[status]} for status in ERROR_STATUSES
}


def problem(
    status: int,
    code: str,
    detail: str,
    headers: dict[str, str] | None = None,
    errors: list[ProblemIssue] | None = None,
) -> JSONResponse:
    body = Problem(title=TITLES.get(status, "Error"), status=status, code=code, detail=detail, errors=errors)
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


def document_problem_json(app: FastAPI) -> None:
    """FastAPI documents every response under the route's media type (`application/json`). Error responses
    are sent as `application/problem+json`, so the OpenAPI document says so."""
    generate: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        spec = generate()
        for operations in spec.get("paths", {}).values():
            for operation in operations.values():
                for status, response in operation.get("responses", {}).items():
                    content = response.get("content", {})
                    if status[0] in "45" and "application/json" in content:
                        response["content"] = {PROBLEM_JSON: content["application/json"]}
        return spec

    app.openapi = openapi  # type: ignore[method-assign]


def install_error_handlers(app: FastAPI, allowed_origins: Iterable[str] = ()) -> None:
    origins = frozenset(allowed_origins)

    @app.exception_handler(ApiProblem)
    async def _api(_: Request, exc: ApiProblem) -> JSONResponse:
        return problem(exc.status, exc.code, exc.detail, errors=exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {"loc": [], "msg": "Invalid request"}
        where = ".".join(str(p) for p in first["loc"] if p != "body")
        return problem(422, "SCHEMA_INVALID", f"{where}: {first['msg']}" if where else first["msg"])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(exc.status_code, HTTP_CODES.get(exc.status_code, "ERROR"), str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Starlette runs this handler in ServerErrorMiddleware, outside CORSMiddleware, so the CORS header
        # for an allowed origin is added here; otherwise the browser would hide the 500 behind a CORS error.
        log.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        origin = request.headers.get("origin", "")
        headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} if origin in origins else None
        return problem(500, "INTERNAL", "Something went wrong on our side. Try again.", headers)
