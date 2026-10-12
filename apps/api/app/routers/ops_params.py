"""Shared path parameter type for the operator routes: a huge id is a 422, not a lookup."""

from typing import Annotated

from fastapi import Path

PATH_ID_MAX_LENGTH = 100

PathId = Annotated[str, Path(max_length=PATH_ID_MAX_LENGTH)]
