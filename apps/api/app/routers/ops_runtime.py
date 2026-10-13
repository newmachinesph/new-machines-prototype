"""Shared by the operator routers that need Postgres: they answer 503 while the runtime is off."""

from app import settings
from app.errors import ApiProblem, Problem

RUNTIME_RESPONSES = {
    503: {"model": Problem, "description": "The runtime is off or unavailable (RUNTIME_UNAVAILABLE)."}
}


def require_runtime() -> None:
    if not settings.runtime_enabled():
        raise ApiProblem(503, "RUNTIME_UNAVAILABLE", "This needs the runtime, which is off.")
