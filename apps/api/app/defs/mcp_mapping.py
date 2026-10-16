"""What a `driver: mcp` connector tool's `mcp` mapping may say. Neutral ground for the definition validator
(publish time) and `runtime.mcp` / `PlatformMcpDriver` (every call, because a pinned run snapshot skips the
publish-time checks): placeholders, the MCP tools a mapping may name per action class, and the operators no
mapping may hold. Nothing here imports the runtime."""

import re
from typing import Any

NOW = "now"  # the one built-in placeholder: the call time, ISO-8601 UTC with milliseconds (an EJSON `$date`)
# The `mcp` fields handed to the MCP tool as arguments, after their placeholders are filled.
ARGUMENT_FIELDS = ("pipeline", "filter", "projection", "limit", "update")

READ_TOOLS = frozenset({"aggregate", "find", "count"})  # the MCP tools a read may call
WRITE_TOOLS = frozenset({"update-many"})  # the MCP tool a write may call, and only with writes switched on
# Operators that write (`$out`, `$merge`) or run JavaScript on the database server, which no mapping may use.
BANNED_OPERATORS = frozenset({"$out", "$merge", "$where", "$function", "$accumulator"})

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def placeholders(value: Any) -> set[str]:
    """The names of every `{{placeholder}}` in a nested value's strings (dict keys included)."""
    if isinstance(value, str):
        return set(PLACEHOLDER.findall(value))
    if isinstance(value, dict):
        return set().union(*(placeholders(k) | placeholders(v) for k, v in value.items()))
    if isinstance(value, list):
        return set().union(*(placeholders(v) for v in value))
    return set()


def key_placeholders(value: Any) -> set[str]:
    """The placeholders in dict keys at any depth: a key names a field or an operator, so an argument must
    never choose one."""
    if isinstance(value, dict):
        found: set[str] = set()
        for key, inner in value.items():
            found |= placeholders(key) | key_placeholders(inner)
        return found
    if isinstance(value, list):
        return set().union(*(key_placeholders(v) for v in value))
    return set()


def banned_operators(value: Any) -> set[str]:
    """The banned operators used as a key anywhere in a nested value."""
    if isinstance(value, dict):
        found = {k for k in value if k in BANNED_OPERATORS}
        for inner in value.values():
            found |= banned_operators(inner)
        return found
    if isinstance(value, list):
        return set().union(*(banned_operators(v) for v in value))
    return set()


class Refusal(str):
    """Why a mapping may not run: the text, and a `code` (read_tool, read_only, write_tool, missing_filter,
    operator) for callers that react to one reason."""

    code: str

    def __new__(cls, code: str, text: str) -> Refusal:
        obj = super().__new__(cls, text)
        obj.code = code
        return obj


def refusal(action_class: Any, spec: dict, *, writes_enabled: bool) -> Refusal | None:
    """Why this mapping may not run, else None. A read names `aggregate`, `find` or `count`. Anything that
    is not a read is a write: refused unless writes are switched on, and then it names `update-many` with a
    non-empty filter. No mapping holds a banned operator."""
    tool = spec.get("tool")
    if action_class == "read":
        if tool not in READ_TOOLS:
            return Refusal("read_tool", f"a read may call only {', '.join(sorted(READ_TOOLS))}, not {tool!r}")
    elif not writes_enabled:
        return Refusal(
            "read_only", "the platform's MCP server is read-only, so a write cannot be mapped to it"
        )
    elif tool not in WRITE_TOOLS:
        return Refusal("write_tool", f"a write may call only {', '.join(sorted(WRITE_TOOLS))}, not {tool!r}")
    elif not (isinstance(spec.get("filter"), dict) and spec["filter"]):
        return Refusal("missing_filter", "a write needs a non-empty filter")
    used = banned_operators(spec)
    if used:
        return Refusal("operator", f"the operator {', '.join(sorted(used))} is not allowed in a mapping")
    return None
