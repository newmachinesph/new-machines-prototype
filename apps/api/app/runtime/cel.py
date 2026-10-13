"""CEL over the run state. Values starting with "=" in node config are expressions; results are plain JSON."""

import datetime
from functools import lru_cache
from typing import Any

import celpy
from celpy import celtypes

_ENV = celpy.Environment()


class CelError(ValueError):
    """An expression failed to compile or evaluate."""


@lru_cache(maxsize=512)
def _program(expr: str):
    try:
        return _ENV.program(_ENV.compile(expr))
    except celpy.CELParseError as exc:
        raise CelError(f"cannot compile {expr!r}: {str(exc).strip().splitlines()[0]}") from exc


def _to_json(value: Any) -> Any:
    """Convert celpy values back to plain JSON types (bool before int: BoolType subclasses int)."""
    if value is None:
        return None
    if isinstance(value, celtypes.BoolType | bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, celtypes.TimestampType):
        return value.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, celtypes.DurationType):
        return value.total_seconds()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _to_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_to_json(v) for v in value]
    raise CelError(f"unsupported CEL result type {type(value).__name__}")


def evaluate(expr: str, state: dict) -> Any:
    """Evaluate `expr` (with or without a leading "=") over `state`; top-level state keys are variables."""
    source = expr[1:] if expr.startswith("=") else expr
    activation = {k: celpy.json_to_cel(v) for k, v in state.items()}
    try:
        result = _program(source).evaluate(activation)
    except celpy.CELEvalError as exc:
        raise CelError(f"cannot evaluate {source!r}: {exc.args[0] if exc.args else exc}") from exc
    if isinstance(result, celpy.CELEvalError):
        raise CelError(f"cannot evaluate {source!r}: {result.args[0] if result.args else result}")
    return _to_json(result)


def resolve(value: Any, state: dict) -> Any:
    """Return a copy of `value` with every "=..." string (at any depth) replaced by its CEL result."""
    if isinstance(value, str):
        return evaluate(value, state) if value.startswith("=") else value
    if isinstance(value, dict):
        return {k: resolve(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, state) for v in value]
    return value
