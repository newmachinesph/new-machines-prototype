"""Sorting an MCP server's tools for packs: read tools run freely, write tools ask a person first, and a tool
that deletes or moves money, or whose inputs cannot be checked, is blocked and never offered. The server's
hints count first; the words come from the Composio importer's lists (`app.tool_words`)."""

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app import tool_words as words
from app.runtime.drivers import MCP_TRANSPORT, META_TOOL_PREFIX

ToolClass = Literal["read", "write", "blocked"]
Why = Literal[
    "marked_read_only",
    "changes_data",
    "changes_access",
    "marked_destructive",
    "deletes",
    "moves_money",
    "reserved_name",
    "schema_unusable",
    "schema_too_large",
]
MAX_NAME_CHARS = 128  # a longer name, or an empty one, is not a tool id the connector can hold
MAX_TOOLS = 100  # tools taken from one server: the first it lists
MAX_SCHEMA_BYTES = 64 * 1024  # an input schema as compact JSON
ID_MAX = 64
DESCRIPTION_LIMIT = 240
DEFAULTS = {"read": "permit", "write": "require_approval", "delete": "deny", "money": "deny"}
# Extra delete words for MCP tools only (the Composio importer keeps its own sets). DROP counts only as the
# first word of a name ("drop_table", not "get_drop_off_points"); RESET is a change, so it asks first.
MCP_DELETE_WORDS = words.DELETE_WORDS | {"WIPE", "ERASE", "TRUNCATE", "TERMINATE", "UNINSTALL"}
# Money words that stop a name from plainly reading when chained after a read ("list_and_refund"). PAY and
# CAPTURE already stop it (tool_words.MONEY_VERBS); "list_refunds" and "get_transfer_status" still read.
MCP_MONEY_VERBS = {"REFUND", "CHARGE", "TRANSFER", "PAYOUT"}
_CHAIN = {"AND", "THEN", "OR"}
_TOOL_ID = re.compile(r"^[a-z][a-z0-9_-]*$")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NOT_ID = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ListedTool:
    """One tool as the server lists it."""

    name: str
    description: str
    input_schema: Any
    output_schema: Any = None
    read_only: bool | None = None  # annotations.readOnlyHint
    destructive: bool | None = None  # annotations.destructiveHint, only when the server sets it


@dataclass(frozen=True)
class SortedTool:
    """A listed tool, sorted, as `mcp_servers.tools` stores it. A blocked tool keeps no schema or sample."""

    id: str
    name: str
    description: str
    tool_class: ToolClass
    why: Why
    on: bool
    input_schema: dict[str, Any]
    sample: dict[str, Any] | None = None
    admin_off: bool = False  # the admin's own off choice, kept apart from `blocked` so an unblock keeps it

    def stored(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_stored(cls, row: dict[str, Any]) -> Self:
        return cls(
            admin_off=admin_off_of(row),
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row.get("description") or ""),
            tool_class=row["tool_class"],
            why=row["why"],
            on=bool(row.get("on")),
            input_schema=dict(row.get("input_schema") or {}),
            sample=row.get("sample"),
        )


def admin_off_of(row: dict[str, Any]) -> bool:
    """Whether the admin switched a stored tool off. Rows stored before `admin_off` existed count a
    switched-off tool that was not blocked."""
    if "admin_off" in row:
        return bool(row["admin_off"])
    return not row.get("on") and row.get("tool_class") != "blocked"


def _remote_ref(schema: Any) -> bool:
    """Whether any `$ref` or `$dynamicRef` points outside the schema (iterative: no recursion limit)."""
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in ("$ref", "$dynamicRef"):
                ref = node.get(key)
                if isinstance(ref, str) and not ref.startswith("#"):
                    return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def schema_problem(schema: Any) -> Why | None:
    """Why an input schema cannot be used, or None: it must be a JSON object schema (`type: object`) of at
    most MAX_SCHEMA_BYTES, valid under Draft 2020-12, with no reference outside itself."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return "schema_unusable"
    try:
        size = len(json.dumps(schema, separators=(",", ":")).encode("utf-8"))
    except TypeError, ValueError, RecursionError:
        return "schema_unusable"
    if size > MAX_SCHEMA_BYTES:
        return "schema_too_large"
    if _remote_ref(schema):
        return "schema_unusable"
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError, RecursionError:
        return "schema_unusable"
    return None


def classify(tool: ListedTool) -> tuple[ToolClass, Why]:
    """(class, why) for one tool. Order: reserved names, unusable schemas, the destructive hint, delete words,
    money words (unless the name plainly reads), access words (asks first), the read-only hint (unless the
    name has a write word), else asks first."""
    if not 1 <= len(tool.name) <= MAX_NAME_CHARS or tool.name.upper().startswith(META_TOOL_PREFIX):
        return "blocked", "reserved_name"
    if problem := schema_problem(tool.input_schema):
        return "blocked", problem
    if tool.destructive is True:
        return "blocked", "marked_destructive"
    found = words.name_words(tool.name)
    named = set(found)
    reads = words.plainly_reads(found)
    # A name that could not be split ("deletecustomer") is one word: a delete word may start it.
    starters = MCP_DELETE_WORDS | {"DROP"}
    unsplit = len(found) == 1 and any(found[0].startswith(w) for w in starters)
    if MCP_DELETE_WORDS & named or found[:1] == ["DROP"] or unsplit:
        return "blocked", "deletes"
    chained = any(b in MCP_MONEY_VERBS for a, b in zip(found, found[1:], strict=False) if a in _CHAIN)
    if words.MONEY_WORDS & named and (not reads or chained):
        return "blocked", "moves_money"
    if words.ACCESS_WORDS & named and not reads:
        return "write", "changes_access"
    if tool.read_only is True and not words.WRITE_WORDS & named:
        return "read", "marked_read_only"
    return "write", "changes_data"


def harden(schema: dict[str, Any]) -> dict[str, Any]:
    """A copy of `schema` that refuses undeclared arguments at the top, unless it says otherwise."""
    out = json.loads(json.dumps(schema))
    out.setdefault("additionalProperties", False)
    return out


def sample_of(output_schema: Any) -> dict[str, Any] | None:
    """A sandbox response from the tool's output schema: an object of at most MAX_SCHEMA_BYTES, or None."""
    if not isinstance(output_schema, dict):
        return None
    defs = output_schema.get("$defs")
    try:
        value = words.example(output_schema, defs if isinstance(defs, dict) else {})
        size = len(json.dumps(value))
    except TypeError, ValueError, AttributeError, RecursionError:
        return None
    return value if isinstance(value, dict) and size <= MAX_SCHEMA_BYTES else None


def describe(text: str | None, fallback: str) -> str:
    """The description on one line, at most DESCRIPTION_LIMIT characters; `fallback` when empty."""
    flat = " ".join(str(text or "").split())
    if not flat:
        return fallback
    return flat if len(flat) <= DESCRIPTION_LIMIT else flat[: DESCRIPTION_LIMIT - 3].rstrip() + "..."


def tool_id(name: str, taken: set[str]) -> str:
    """A tool id from an MCP name, unique in `taken`: "getCustomer" -> get_customer, then get_customer_2."""
    snake = _CAMEL.sub("_", name).lower()
    base = "_".join(w for w in _NOT_ID.split(snake) if w)[:ID_MAX] or "tool"
    if not base[0].isalpha():
        base = f"tool_{base}"[:ID_MAX]
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def sort_tools(listed: list[ListedTool], previous: list[dict[str, Any]] | None = None) -> list[SortedTool]:
    """The first MAX_TOOLS tools, sorted. A tool listed before (by name, in `previous`) keeps its id and its
    switch (the admin's off choice survives a spell as blocked); a new tool starts on unless it is blocked."""
    before = {str(p.get("name")): p for p in previous or []}
    taken: set[str] = set()
    seen: set[str] = set()
    listed_names = {t.name for t in listed[:MAX_TOOLS]}
    kept: dict[str, str] = {}  # ids of tools still listed are theirs, whatever the listing order
    for name, old in before.items():
        stored = str(old.get("id") or "")
        if name in listed_names and _TOOL_ID.fullmatch(stored) and stored not in taken:
            taken.add(stored)
            kept[name] = stored
    out: list[SortedTool] = []
    for tool in listed[:MAX_TOOLS]:
        if tool.name in seen:
            continue
        seen.add(tool.name)
        tool_class, why = classify(tool)
        old = before.get(tool.name) or {}
        tid = kept.get(tool.name) or tool_id(tool.name, taken)
        taken.add(tid)
        admin_off = admin_off_of(old) if old else False
        blocked = tool_class == "blocked"
        out.append(
            SortedTool(
                id=tid,
                name=tool.name,
                description=describe(tool.description, tool.name),
                tool_class=tool_class,
                why=why,
                on=not blocked and not admin_off,
                admin_off=admin_off,
                input_schema={} if blocked else harden(tool.input_schema),
                sample=None if blocked else sample_of(tool.output_schema),
            )
        )
    return out


def usable(tools: list[SortedTool]) -> list[SortedTool]:
    """The tools a pack can use: switched on and not blocked."""
    return [t for t in tools if t.on and t.tool_class != "blocked"]


def _entry(tool: SortedTool, prefix: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": tool.id,
        "slug": tool.name,
        "action_class": tool.tool_class,
        "capability": f"{prefix}.{tool.tool_class}",
        "description": tool.description,
        "input_schema": tool.input_schema,
    }
    if tool.sample is not None:
        out["sample"] = tool.sample
    return out


def connector_body(app: str, server_id: str, tools: list[SortedTool], prefix: str) -> dict[str, Any]:
    """The org-owned connector definition: the usable tools, each with capability `<prefix>.<class>`."""
    return {
        "app": app,
        "transport": MCP_TRANSPORT,
        "server": server_id,
        "tools": [_entry(t, prefix) for t in usable(tools)],
        "defaults": dict(DEFAULTS),
    }
