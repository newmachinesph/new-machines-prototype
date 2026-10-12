from typing import Any

from fastapi import APIRouter

from app.errors import ERROR_RESPONSES


class ApiRouter(APIRouter):
    """Responses omit unset optional fields, so clients see `undefined`, never `null`. Every route documents
    the shared problem+json error responses."""

    def add_api_route(self, path: str, endpoint: Any, **kwargs: Any) -> None:
        kwargs["response_model_exclude_none"] = True
        kwargs["responses"] = {**ERROR_RESPONSES, **(kwargs.get("responses") or {})}
        super().add_api_route(path, endpoint, **kwargs)
