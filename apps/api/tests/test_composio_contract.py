"""Every connector tool sends only arguments its Composio tool takes, with Composio's types, enums and bounds,
requires what Composio requires, and pins the Composio toolkit version its schema was recorded at. Composio's
schemas are recorded in tests/fixtures/composio by
`uv run --env-file ../../.env python scripts/composio_schemas.py`; this test needs no network."""

import json
from pathlib import Path

import pytest
import yaml

from app import settings
from app.runtime.drivers import META_TOOL_PREFIX

FIXTURES = Path(__file__).parent / "fixtures" / "composio"
RECORD = "run `uv run --env-file ../../.env python scripts/composio_schemas.py`"


def _tools() -> list[tuple[str, dict]]:
    """(connector key, tool) for every connector tool with a slug, except Composio meta tools."""
    found = []
    for path in sorted((settings.defs_dir() / "connectors").glob("*.yaml")):
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
        for tool in body.get("tools") or []:
            slug = tool.get("slug")
            if slug and not str(slug).upper().startswith(META_TOOL_PREFIX):
                found.append((str(body["key"]), tool))
    return found


TOOLS = _tools()


def _types(schema: dict) -> set[str]:
    """The JSON types a schema allows: its `type` (a name or a list), else the union over its `anyOf`."""
    raw = schema.get("type")
    if raw is not None:
        return {raw} if isinstance(raw, str) else set(raw)
    return set().union(*(_types(s) for s in schema.get("anyOf") or [] if isinstance(s, dict)))


def _type_fits(have: set[str], want: set[str]) -> bool:
    return all(t in want or (t == "integer" and "number" in want) for t in have)


def _problems(ours: dict, theirs: dict, at: str) -> list[str]:
    """Why a value valid for `ours` might be refused by `theirs` (empty when it fits)."""
    have, want = _types(ours), _types(theirs)
    found = (
        [f"{at} is {sorted(want)}, not {sorted(have)}"]
        if have and want and not _type_fits(have, want)
        else []
    )
    branches = [b for b in theirs.get("anyOf") or [] if isinstance(b, dict)]
    if not branches:
        return found + _shape_problems(ours, theirs, at)
    # Their alternatives: ours must fit at least one that shares a type with it.
    base = {k: v for k, v in theirs.items() if k != "anyOf"}
    alike = [{**base, **b} for b in branches]
    alike = [b for b in alike if not have or not _types(b) or any(_type_fits({t}, _types(b)) for t in have)]
    tries = [_shape_problems(ours, b, at) for b in alike]
    return found + (min(tries, key=len) if tries and all(tries) else [])


def _values(enum: list) -> set[str]:
    """Enum values as comparable text (they may be objects or lists)."""
    return {json.dumps(v, sort_keys=True) for v in enum}


def _bound(schema: dict, lower: bool) -> tuple[float, bool, str] | None:
    """The tightest (value, exclusive, keyword) lower or upper bound a schema sets, or None."""
    names = ("minimum", "exclusiveMinimum") if lower else ("maximum", "exclusiveMaximum")
    found = [
        (schema[n], n.startswith("exclusive"), n) for n in names if isinstance(schema.get(n), int | float)
    ]
    if not found:
        return None
    # Lower: the larger value is tighter; upper: the smaller. At equal values the exclusive one is.
    return max(found, key=lambda b: (b[0], b[1])) if lower else min(found, key=lambda b: (b[0], not b[1]))


def _bound_problems(ours: dict, theirs: dict, at: str) -> list[str]:
    found = []
    for lower in (True, False):
        want = _bound(theirs, lower)
        if want is None:
            continue
        have = _bound(ours, lower)
        if have is not None and have[2] == want[2]:
            shown = str(have[0])
        else:
            shown = f"{have[2]} {have[0]}" if have else "none"
        inside = have is not None and (
            (have[0] > want[0] if lower else have[0] < want[0])
            or (have[0] == want[0] and (have[1] or not want[1]))
        )
        if not inside:
            found.append(f"{at} has {want[2]} {want[0]}, not {shown}")
    for keyword, tighter in (
        ("minLength", lambda o, t: o >= t),
        ("maxLength", lambda o, t: o <= t),
        ("minItems", lambda o, t: o >= t),
        ("maxItems", lambda o, t: o <= t),
    ):
        if keyword in theirs and not (keyword in ours and tighter(ours[keyword], theirs[keyword])):
            found.append(f"{at} has {keyword} {theirs[keyword]}, not {ours.get(keyword, 'none')}")
    if "pattern" in theirs and ours.get("pattern") != theirs["pattern"]:
        mine = repr(ours["pattern"]) if "pattern" in ours else "none"
        found.append(f"{at} has pattern {theirs['pattern']!r}, not {mine}")
    return found


def _shape_problems(ours: dict, theirs: dict, at: str) -> list[str]:
    found = []
    if "enum" in theirs and not ("enum" in ours and _values(ours["enum"]) <= _values(theirs["enum"])):
        found.append(f"{at} takes only {theirs['enum']}, not {ours.get('enum', 'any value')}")
    found += _bound_problems(ours, theirs, at)
    our_props, their_props = ours.get("properties") or {}, theirs.get("properties")
    extra = theirs.get("additionalProperties")
    if their_props is not None:
        missing = sorted(set(theirs.get("required") or []) - set(ours.get("required") or []))
        found += [f"{at} requires {missing}"] if missing else []
        unknown_required = sorted(set(ours.get("required") or []) - set(their_props))
        found += [f"{at} takes no argument {unknown_required} that we require"] if unknown_required else []
    for name, prop in our_props.items():
        if their_props is not None and name in their_props:
            found += _problems(prop, their_props[name], f"{at}.{name}")
        elif isinstance(extra, dict):
            found += _problems(prop, extra, f"{at}.{name}")
        elif their_props is not None or extra is False:
            found.append(f"{at} takes no argument {name!r}")
    if isinstance(ours.get("items"), dict) and isinstance(theirs.get("items"), dict):
        found += _problems(ours["items"], theirs["items"], f"{at}[]")
    return found


def test_every_connector_tool_has_a_recorded_composio_schema():
    missing = sorted(t["slug"] for _, t in TOOLS if not (FIXTURES / f"{t['slug']}.json").is_file())
    assert missing == [], RECORD


def test_every_recorded_schema_belongs_to_a_connector_tool():
    stale = sorted({p.stem for p in FIXTURES.glob("*.json")} - {t["slug"] for _, t in TOOLS})
    assert stale == [], f"{stale} are no connector tool's slug; {RECORD} to remove them"


@pytest.mark.parametrize(("connector", "tool"), TOOLS, ids=[f"{c}.{t['id']}" for c, t in TOOLS])
def test_a_connector_tool_matches_its_composio_tool(connector, tool):
    recorded = json.loads((FIXTURES / f"{tool['slug']}.json").read_text(encoding="utf-8"))
    assert recorded["version"] == tool.get("version"), (
        f"{connector}.{tool['id']} pins {tool.get('version')}, the schema is {recorded['version']}; {RECORD}"
    )
    ours = tool.get("input_schema") or {}
    assert ours.get("additionalProperties") is False, (
        f"{connector}.{tool['id']} must refuse undeclared arguments"
    )
    assert _problems(ours, recorded["input_parameters"] or {}, tool["slug"]) == []


def test_meta_tools_are_not_contract_checked(monkeypatch, tmp_path):
    (tmp_path / "connectors").mkdir()
    tools = [
        {"id": "meta", "slug": "composio_multi_execute_tool"},
        {"id": "send", "slug": "GMAIL_SEND_EMAIL"},
    ]
    body = {"key": "x", "toolkit": "x", "tools": tools}
    (tmp_path / "connectors" / "x.yaml").write_bytes(yaml.safe_dump(body).encode("utf-8"))
    monkeypatch.setenv("NM_DEFS_DIR", str(tmp_path))
    assert [t["slug"] for _, t in _tools()] == ["GMAIL_SEND_EMAIL"]


OBJ = {"type": "object", "additionalProperties": False}


@pytest.mark.parametrize(
    ("ours", "theirs", "problem"),
    [
        ({"type": "integer"}, {"type": "number"}, None),
        ({"type": "number"}, {"type": "integer"}, "x is ['integer'], not ['number']"),
        ({"type": ["string", "null"]}, {"anyOf": [{"type": "string"}, {"type": "null"}]}, None),
        (
            {"type": ["string", "null"]},
            {"anyOf": [{"type": "string"}]},
            "x is ['string'], not ['null', 'string']",
        ),
        ({"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["a", "b"]}, None),
        ({"type": "string", "enum": ["a", "c"]}, {"type": "string", "enum": ["a", "b"]}, "x takes only"),
        ({"type": "string"}, {"type": "string", "enum": ["a"]}, "x takes only"),
        (
            {"type": "integer", "minimum": 1, "maximum": 50},
            {"type": "integer", "minimum": 1, "maximum": 100},
            None,
        ),
        (
            {"type": "integer", "maximum": 500},
            {"type": "integer", "maximum": 100},
            "x has maximum 100, not 500",
        ),
        ({"type": "integer"}, {"type": "integer", "minimum": 1}, "x has minimum 1, not none"),
        (
            {**OBJ, "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {}},
            "no argument 'a'",
        ),
        (
            {**OBJ, "properties": {"a": {"type": "integer"}}},
            {"additionalProperties": {"type": "string"}},
            "x.a is",
        ),
        (
            {**OBJ, "properties": {"a": {"type": "string"}}},
            {"properties": {"a": {}}, "required": ["b"]},
            "requires",
        ),
        ({**OBJ, "required": ["a"], "properties": {}}, {"properties": {}}, "takes no argument ['a']"),
        ({"items": {"items": {"type": "boolean"}}}, {"items": {"items": {"type": "string"}}}, "x[][] is"),
        (
            {"items": {"type": "integer"}},
            {"items": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
            None,
        ),
        # Exclusive bounds: tighter or equal fits, looser does not.
        ({"type": "integer", "minimum": 1}, {"type": "integer", "exclusiveMinimum": 0}, None),
        (
            {"type": "integer", "minimum": 0},
            {"type": "integer", "exclusiveMinimum": 0},
            "x has exclusiveMinimum 0",
        ),
        ({"type": "number", "exclusiveMaximum": 5}, {"type": "number", "maximum": 5}, None),
        (
            {"type": "number", "maximum": 5},
            {"type": "number", "exclusiveMaximum": 5},
            "x has exclusiveMaximum 5",
        ),
        ({"type": "integer", "exclusiveMinimum": 3}, {"type": "integer", "minimum": 3}, None),
        # Lengths, item counts and patterns.
        ({"type": "string", "minLength": 30}, {"type": "string", "minLength": 30}, None),
        (
            {"type": "string", "minLength": 3},
            {"type": "string", "minLength": 30},
            "x has minLength 30, not 3",
        ),
        ({"type": "string"}, {"type": "string", "minLength": 30}, "x has minLength 30, not none"),
        ({"type": "string", "maxLength": 200}, {"type": "string", "maxLength": 150}, "x has maxLength 150"),
        ({"type": "string", "maxLength": 100}, {"type": "string", "maxLength": 150}, None),
        (
            {"type": "array", "minItems": 1},
            {"type": "array", "minItems": 1, "maxItems": 9},
            "x has maxItems 9",
        ),
        ({"type": "array", "minItems": 0}, {"type": "array", "minItems": 1}, "x has minItems 1, not 0"),
        ({"type": "string", "pattern": "^[a-z]+$"}, {"type": "string", "pattern": "^[a-z]+$"}, None),
        ({"type": "string"}, {"type": "string", "pattern": "^[a-z]+$"}, "x has pattern '^[a-z]+$', not none"),
        ({"type": "string", "pattern": "^a"}, {"type": "string", "pattern": "^[a-z]+$"}, "x has pattern"),
        # Enum values need not be hashable.
        ({"enum": [{"a": 1}, [1, 2]]}, {"enum": [[1, 2], {"a": 1}, None]}, None),
        ({"enum": [{"a": 2}]}, {"enum": [{"a": 1}]}, "x takes only"),
    ],
)
def test_the_schema_check_catches_what_composio_would_refuse(ours, theirs, problem):
    found = _problems(ours, theirs, "x")
    if problem is None:
        assert found == []
    else:
        assert len(found) == 1 and problem in found[0], found
