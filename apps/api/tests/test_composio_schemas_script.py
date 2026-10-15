"""scripts/composio_schemas.py records each connector tool's Composio input schema; the client is faked."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).parents[1] / "scripts" / "composio_schemas.py"

THEIRS = {
    "type": "object",
    "title": "Request",
    "required": ["q"],
    "properties": {
        "q": {
            "type": "string",
            "description": "search",
            "examples": ["x"],
            "human_parameter_name": "Query",
            "minLength": 30,
            "maxLength": 99,
        },
        "n": {"type": "integer", "minimum": 1, "maximum": 9, "default": 3, "exclusiveMaximum": 10},
        "rows": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {"anyOf": [{"type": "string", "title": "s"}, {"type": "null"}]},
        },
        "when": {"type": "object", "additionalProperties": {"type": "integer", "description": "unix"}},
        "kind": {"type": "string", "enum": ["a", "b"], "pattern": "^[ab]$", "exclusiveMinimum": 0},
    },
}
STRIPPED = {
    "type": "object",
    "required": ["q"],
    "properties": {
        "q": {"type": "string", "minLength": 30, "maxLength": 99},
        "n": {"type": "integer", "minimum": 1, "maximum": 9, "exclusiveMaximum": 10},
        "rows": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "when": {"type": "object", "additionalProperties": {"type": "integer"}},
        "kind": {"type": "string", "enum": ["a", "b"], "pattern": "^[ab]$", "exclusiveMinimum": 0},
    },
}


def _load_script():
    spec = importlib.util.spec_from_file_location("composio_schemas", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ToolNotFoundError(Exception):
    pass


class _FakeComposio:
    """Stands in for composio.Composio: hands out schemas at the toolkit version it was built with."""

    made: list[dict] = []
    asked: list[tuple[str, str]] = []
    unknown: set[str] = set()
    schemas: dict[str, dict] = {}

    tracking: list[bool] = []  # `allow_tracking` each client was built with

    def __init__(self, toolkit_versions: dict | None = None, *, allow_tracking: bool = True) -> None:
        self.versions = toolkit_versions or {}
        _FakeComposio.made.append(self.versions)
        _FakeComposio.tracking.append(allow_tracking)
        self.tools = self

    def get_raw_composio_tool_by_slug(self, slug: str):
        version = next(iter(self.versions.values()), "latest")
        _FakeComposio.asked.append((slug, version))
        if slug in _FakeComposio.unknown:
            raise _ToolNotFoundError(f"Tool with slug {slug} not found")
        schema = _FakeComposio.schemas.get(slug, THEIRS)
        return types.SimpleNamespace(version=version, input_parameters=schema)

    def execute(self, *args, **kwargs):  # pragma: no cover - recording must never run a tool
        raise AssertionError("the recorder executed a tool")


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    defs, out = tmp_path / "defs", tmp_path / "out"
    (defs / "connectors").mkdir(parents=True)
    connectors = {
        "mail": [
            ("MAIL_LIST", "20261010_00"),
            ("COMPOSIO_MULTI_EXECUTE_TOOL", None),
            ("MAIL_DRAFT", "20261010_00"),
        ],
        "pay": [("PAY_LIST", "20261007_00"), ("composio_search_tools", "20261007_00")],
    }
    for key, tools in connectors.items():
        body = {
            "key": key,
            "toolkit": key,
            "tools": [{"id": s.lower(), "slug": s, "version": v} for s, v in tools],
        }
        (defs / "connectors" / f"{key}.yaml").write_bytes(yaml.safe_dump(body).encode("utf-8"))
    monkeypatch.setenv("NM_DEFS_DIR", str(defs))
    fake = types.SimpleNamespace(Composio=_FakeComposio)
    monkeypatch.setitem(sys.modules, "composio", fake)
    monkeypatch.setitem(
        sys.modules, "composio.exceptions", types.SimpleNamespace(ToolNotFoundError=_ToolNotFoundError)
    )
    _FakeComposio.made, _FakeComposio.asked, _FakeComposio.unknown = [], [], set()
    _FakeComposio.schemas, _FakeComposio.tracking = {}, []
    script = _load_script()
    monkeypatch.setattr(script, "OUT", out)
    return script, out


def test_the_recorder_writes_each_slug_at_its_pinned_toolkit_version(recorder):
    script, out = recorder

    script.main()

    assert sorted(_FakeComposio.asked) == [
        ("MAIL_DRAFT", "20261010_00"),
        ("MAIL_LIST", "20261010_00"),
        ("PAY_LIST", "20261007_00"),
    ]
    assert {"mail": "20261010_00"} in _FakeComposio.made and {"pay": "20261007_00"} in _FakeComposio.made
    assert _FakeComposio.tracking and set(_FakeComposio.tracking) == {False}  # no SDK telemetry
    assert sorted(p.stem for p in out.glob("*.json")) == ["MAIL_DRAFT", "MAIL_LIST", "PAY_LIST"]
    raw = (out / "PAY_LIST.json").read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"}\n")
    assert json.loads(raw) == {"slug": "PAY_LIST", "version": "20261007_00", "input_parameters": STRIPPED}


def test_the_recorder_never_asks_for_a_meta_tool(recorder):
    script, out = recorder

    script.main()

    assert not any(slug.upper().startswith("COMPOSIO_") for slug, _ in _FakeComposio.asked)
    assert not any(p.stem.upper().startswith("COMPOSIO_") for p in out.glob("*.json"))


def test_the_recorder_removes_schemas_no_connector_tool_uses(recorder):
    script, out = recorder
    out.mkdir()
    (out / "OLD_TOOL.json").write_bytes(b"{}\n")
    (out / "notes.txt").write_bytes(b"kept\n")

    script.main()

    assert not (out / "OLD_TOOL.json").exists()
    assert (out / "notes.txt").exists()


def test_the_recorder_reports_every_unknown_slug_then_fails(recorder, capsys):
    script, out = recorder
    _FakeComposio.unknown = {"MAIL_DRAFT", "PAY_LIST"}

    with pytest.raises(SystemExit) as exited:
        script.main()

    assert exited.value.code == 1
    err = capsys.readouterr().err
    assert "MAIL_DRAFT" in err and "PAY_LIST" in err
    assert [p.stem for p in out.glob("*.json")] == ["MAIL_LIST"]


@pytest.mark.parametrize("keyword", ["oneOf", "allOf", "$ref", "$defs", "const", "not"])
def test_the_recorder_refuses_a_schema_keyword_the_contract_test_cannot_check(recorder, capsys, keyword):
    script, out = recorder
    nested = {"type": "object", "properties": {"deep": {"type": "array", "items": {keyword: {}}}}}
    _FakeComposio.schemas = {"PAY_LIST": {"type": "object", "properties": {"f": nested}}}

    with pytest.raises(SystemExit) as exited:
        script.main()

    assert exited.value.code == 1
    err = capsys.readouterr().err
    assert f"PAY_LIST.f.deep[] uses {keyword}" in err
    assert sorted(p.stem for p in out.glob("*.json")) == ["MAIL_DRAFT", "MAIL_LIST"]


def test_a_property_named_like_a_keyword_is_recorded(recorder):
    script, out = recorder
    named = {"type": "object", "properties": {"const": {"type": "string"}, "not": {"type": "integer"}}}
    _FakeComposio.schemas = {"PAY_LIST": named}

    script.main()

    assert json.loads((out / "PAY_LIST.json").read_bytes())["input_parameters"] == named


def test_one_slug_pinned_at_two_versions_is_refused(recorder):
    script, _ = recorder
    defs = Path(script.settings.defs_dir())
    body = {
        "key": "mail2",
        "toolkit": "mail",
        "tools": [{"id": "l", "slug": "MAIL_LIST", "version": "20261011_00"}],
    }
    (defs / "connectors" / "mail2.yaml").write_bytes(yaml.safe_dump(body).encode("utf-8"))

    with pytest.raises(ValueError, match="MAIL_LIST is pinned at 20261010_00 and 20261011_00"):
        script.tools()
    assert _FakeComposio.asked == []
