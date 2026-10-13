import copy
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app import main as app_main
from app import settings
from app.defs import registry
from app.defs.digest import canonical, digest
from app.defs.loader import LoadError, load_bundle, parse_definition
from app.defs.model import Bundle
from app.defs.validate import validate_bundle

FIXTURE = Path(__file__).parent / "fixtures" / "defs_min"
API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle() -> Bundle:
    return load_bundle(FIXTURE)


def mutated(bundle: Bundle, kind: str, key: str, edit) -> Bundle:
    """Copy of `bundle` with definition kind/key replaced by edit(body_copy, files_copy)."""
    d = bundle.get(kind, key)
    body, files = copy.deepcopy(d.body), dict(d.files)
    edit(body, files)
    items = dict(bundle.items)
    items[(kind, key)] = replace(d, body=body, files=files)
    return Bundle(items=items)


def only_error(bundle: Bundle, *, mentions: str, kind: str):
    errors = validate_bundle(bundle)
    assert len(errors) == 1, errors
    assert mentions in errors[0].message
    assert errors[0].kind == kind
    return errors[0]


# --- loading ---------------------------------------------------------------------------------------


def test_loads_every_definition_with_kind_and_key(bundle):
    assert sorted(bundle.items) == [
        ("agent", "helper-agent"),
        ("connector", "shop"),
        ("contract", "demo-pack"),
        ("decision_rules", "triage"),
        ("memory_space", "notes"),
        ("models", "default"),
        ("pack", "demo-pack"),
        ("schema", "demo-pack/input"),
        ("schema", "demo-pack/output"),
        ("taxonomy", "default"),
        ("workflow", "demo-pack"),
    ]
    agent = bundle.get("agent", "helper-agent")
    assert sorted(agent.files) == ["instructions.md", "skills/lookup.md"]
    assert "kind" not in agent.body and "key" not in agent.body
    assert agent.path == "agents/helper-agent/agent.yaml"
    assert [d.key for d in bundle.of("schema")] == ["demo-pack/input", "demo-pack/output"]


def test_fixture_bundle_is_valid(bundle):
    assert validate_bundle(bundle) == []


def test_parse_definition_rejects_mismatched_key():
    with pytest.raises(LoadError):
        parse_definition("connector", "shop", "kind: connector\nkey: other\n", {}, "connectors/shop.yaml")


def test_parse_definition_rejects_bad_yaml():
    with pytest.raises(LoadError):
        parse_definition("connector", "shop", "a: [", {}, "connectors/shop.yaml")


# --- validation ------------------------------------------------------------------------------------


def test_route_to_missing_node(bundle):
    bad = mutated(bundle, "workflow", "demo-pack", lambda b, f: b["nodes"][0]["routes"].update(next="ghost"))
    err = only_error(bad, mentions="'ghost'", kind="workflow")
    assert "nodes[0]" in err.message and err.path == "packs/demo-pack/workflow.yaml"


def test_agent_tool_not_in_any_connector(bundle):
    bad = mutated(bundle, "agent", "helper-agent", lambda b, f: b["runtime"]["tools"].append("shop.missing"))
    only_error(bad, mentions="shop.missing", kind="agent")


def test_cel_syntax_error_in_decision_rule(bundle):
    bad = mutated(
        bundle, "decision_rules", "triage", lambda b, f: b["rules"][0].update(when="facts.total_minor <")
    )
    only_error(bad, mentions="rules[0].when", kind="decision_rules")


def test_cel_syntax_error_in_workflow_argument(bundle):
    bad = mutated(bundle, "workflow", "demo-pack", lambda b, f: b["nodes"][1]["config"].update(input="=run."))
    only_error(bad, mentions="config.input", kind="workflow")


def test_pack_industry_not_in_taxonomy(bundle):
    bad = mutated(bundle, "pack", "demo-pack", lambda b, f: b["industries"].append("underwater-basketry"))
    only_error(bad, mentions="industries[1]", kind="pack")


def test_contract_missing_a_used_capability(bundle):
    bad = mutated(
        bundle, "contract", "demo-pack", lambda b, f: b["authorization"].update(tool_capabilities=[])
    )
    only_error(bad, mentions="shop.orders.read", kind="contract")


def test_missing_skill_file(bundle):
    bad = mutated(bundle, "agent", "helper-agent", lambda b, f: f.pop("skills/lookup.md"))
    only_error(bad, mentions="skills/lookup.md", kind="agent")


def test_workflow_contract_ref_must_resolve(bundle):
    bad = mutated(bundle, "workflow", "demo-pack", lambda b, f: b.update(work_contract_ref="ghost-contract"))
    only_error(bad, mentions="'ghost-contract'", kind="workflow")


def test_malformed_definitions_return_errors_without_raising(bundle):
    bad = mutated(bundle, "connector", "shop", lambda b, f: b["tools"][0].pop("id"))
    bad = mutated(bad, "workflow", "demo-pack", lambda b, f: b["nodes"][1].pop("config"))
    bad = mutated(bad, "workflow", "demo-pack", lambda b, f: b["nodes"].__setitem__(2, 7))
    bad = mutated(bad, "taxonomy", "default", lambda b, f: b["functions"].append({"name": "no id"}))
    errors = validate_bundle(bad)  # must not raise
    assert {e.kind for e in errors} >= {"connector", "workflow", "taxonomy"}
    assert any("tools[0]" in e.message and "id" in e.message for e in errors if e.kind == "connector")


def test_schemas_dir_is_overridable(bundle, tmp_path, monkeypatch):
    (tmp_path / "nm.taxonomy.v1.schema.json").write_text('{"type": "array"}', encoding="utf-8")
    monkeypatch.setenv("NM_SCHEMAS_DIR", str(tmp_path))
    errors = validate_bundle(Bundle(items={("taxonomy", "default"): bundle.get("taxonomy", "default")}))
    assert [e.kind for e in errors] == ["taxonomy"] and "array" in errors[0].message


def test_schema_violation_names_the_field(bundle):
    bad = mutated(bundle, "pack", "demo-pack", lambda b, f: b.update(risk_class="extreme"))
    only_error(bad, mentions="risk_class", kind="pack")


def test_hosted_agent_needs_no_endpoint_but_others_do(bundle):
    bad = mutated(bundle, "agent", "helper-agent", lambda b, f: b["runtime"].update(adapter="approved_http"))
    only_error(bad, mentions="endpoint_ref", kind="agent")


def test_agent_file_path_cannot_escape_folder(bundle):
    bad = mutated(
        bundle, "agent", "helper-agent", lambda b, f: b["runtime"].update(instructions="../../secrets.md")
    )
    only_error(bad, mentions="inside the agent folder", kind="agent")


# --- digest ----------------------------------------------------------------------------------------


def test_canonical_ignores_key_order_and_whitespace():
    assert canonical({"b": 1, "a": [1, 2]}) == canonical({"a": [1, 2], "b": 1}) == b'{"a":[1,2],"b":1}'


def test_digest_is_stable_across_key_order_and_changes_with_files(bundle):
    d = bundle.get("agent", "helper-agent")
    reordered = replace(
        d, body=dict(reversed(list(d.body.items()))), files=dict(reversed(list(d.files.items())))
    )
    assert digest(d) == digest(reordered)
    assert digest(d).startswith("sha256:")
    changed = replace(d, files={**d.files, "instructions.md": d.files["instructions.md"] + "More.\n"})
    assert digest(changed) != digest(d)


# --- registry (needs Postgres) ---------------------------------------------------------------------


def test_apply_bundle_is_idempotent_and_seeds_memory(db, bundle):
    first = registry.apply_bundle(db, bundle)
    db.commit()
    assert len(first) == len(bundle.items)
    assert all(v.version == 1 and v.source == "file" for v in first)
    assert registry.apply_bundle(db, bundle) == []
    seeded = db.execute("SELECT id, space, source FROM memory_items").fetchall()
    assert [(r["space"], r["source"]) for r in seeded] == [("notes", "seed")]
    assert seeded[0]["id"].startswith("mem_") and len(seeded[0]["id"]) == 16


def test_publish_edit_creates_version_two_and_unchanged_raises(db, bundle):
    registry.apply_bundle(db, bundle)
    agent = bundle.get("agent", "helper-agent")
    edited = replace(agent, files={**agent.files, "instructions.md": "# Helper agent\n\nBe brief.\n"})
    v2 = registry.publish(db, edited, actor="ops@example.com", reason="tighten wording")
    assert (v2.version, v2.source, v2.published_by, v2.reason) == (
        2,
        "console",
        "ops@example.com",
        "tighten wording",
    )
    with pytest.raises(registry.NoChange):
        registry.publish(db, edited, actor="ops@example.com", reason="again")
    assert [v.version for v in registry.versions(db, "agent", "helper-agent")] == [2, 1]
    assert registry.latest(db, "agent", "helper-agent").digest == digest(edited)
    assert registry.get_version(db, "agent", "helper-agent", 1).digest == digest(agent)
    assert registry.get_version(db, "agent", "helper-agent", 3) is None
    assert registry.latest(db, "agent", "nope") is None


def _console_edit(db, bundle) -> None:
    agent = bundle.get("agent", "helper-agent")
    registry.publish(db, replace(agent, files={**agent.files, "instructions.md": "x\n"}), "a", "r")


def _changed_file(bundle) -> Bundle:
    return mutated(bundle, "agent", "helper-agent", lambda b, f: f.update({"instructions.md": "y\n"}))


def test_apply_again_after_console_edit_keeps_the_console_version(db, bundle, caplog):
    registry.apply_bundle(db, bundle)
    _console_edit(db, bundle)
    with caplog.at_level("WARNING", logger="app.defs.registry"):
        again = registry.apply_bundle(db, bundle)  # file unchanged since the last apply: nothing to do
    assert again == [] and not caplog.records
    assert registry.latest(db, "agent", "helper-agent").source == "console"


def test_changed_file_does_not_replace_a_console_version_without_force(db, bundle, caplog):
    registry.apply_bundle(db, bundle)
    _console_edit(db, bundle)
    changed = _changed_file(bundle)
    with caplog.at_level("WARNING", logger="app.defs.registry"):
        assert registry.apply_bundle(db, changed) == []
    assert "agent/helper-agent: v2 was published from the console" in caplog.text
    assert [v.source for v in registry.versions(db, "agent", "helper-agent")] == ["console", "file"]
    forced = registry.apply_bundle(db, changed, force=True)
    assert [(v.kind, v.key, v.version, v.source) for v in forced] == [("agent", "helper-agent", 3, "file")]


def test_file_apply_still_updates_file_versions(db, bundle):
    registry.apply_bundle(db, bundle)
    created = registry.apply_bundle(db, _changed_file(bundle))
    assert [(v.key, v.version, v.source) for v in created] == [("helper-agent", 2, "file")]


def test_console_publish_survives_a_restart_apply(db, bundle, tmp_path, monkeypatch):
    """The API applies files on every start (NM_DEFS_AUTO_APPLY); a console publish must outlive it."""
    _use_defs(monkeypatch, FIXTURE)
    app_main.apply_definitions()
    _console_edit(db, bundle)
    db.commit()
    app_main.apply_definitions()
    db.commit()
    assert [v.source for v in registry.versions(db, "agent", "helper-agent")] == ["console", "file"]


# --- startup apply validates first ----------------------------------------------------------------------


def _use_defs(monkeypatch, root: Path) -> None:
    monkeypatch.setenv("NM_SCHEMAS_DIR", str(settings.schemas_dir()))  # the fixture has no _schemas
    monkeypatch.setenv("NM_DEFS_DIR", str(root))


def test_startup_apply_skips_invalid_files_and_still_starts(db, tmp_path, monkeypatch, caplog):
    root = tmp_path / "defs"
    shutil.copytree(FIXTURE, root)
    workflow = root / "packs" / "demo-pack" / "workflow.yaml"
    text = workflow.read_text(encoding="utf-8")
    workflow.write_text(text.replace("entry_node_id: start", "entry_node_id: nowhere"), encoding="utf-8")
    _use_defs(monkeypatch, root)
    with caplog.at_level("ERROR", logger="app.main"):
        app_main.apply_definitions()  # must not raise
    db.commit()
    assert "entry_node_id: node 'nowhere' does not exist" in caplog.text
    assert "no definition files were applied" in caplog.text
    assert db.execute("SELECT count(*) AS n FROM definition_versions").fetchone()["n"] == 0
    assert db.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] >= 1


def test_startup_apply_skips_unreadable_files(db, tmp_path, monkeypatch, caplog):
    root = tmp_path / "defs"
    shutil.copytree(FIXTURE, root)
    (root / "taxonomy.yaml").write_text("kind: taxonomy\nkey: [unclosed\n", encoding="utf-8")
    _use_defs(monkeypatch, root)
    with caplog.at_level("ERROR", logger="app.main"):
        app_main.apply_definitions()
    db.commit()
    assert "were not applied" in caplog.text
    assert db.execute("SELECT count(*) AS n FROM definition_versions").fetchone()["n"] == 0


def test_startup_apply_skips_when_schemas_are_missing(db, tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("NM_DEFS_DIR", str(FIXTURE))
    monkeypatch.setenv("NM_SCHEMAS_DIR", str(tmp_path / "no-schemas"))
    with caplog.at_level("ERROR", logger="app.main"):
        app_main.apply_definitions()  # must not raise
    db.commit()
    assert "schemas could not be read" in caplog.text
    assert db.execute("SELECT count(*) AS n FROM definition_versions").fetchone()["n"] == 0


def test_startup_apply_applies_valid_files(db, monkeypatch):
    _use_defs(monkeypatch, FIXTURE)
    app_main.apply_definitions()
    db.commit()
    assert db.execute("SELECT count(*) AS n FROM definition_versions").fetchone()["n"] == 11


def test_export_files_round_trip_to_same_digest(db, bundle):
    registry.apply_bundle(db, bundle)
    for v in registry.latest_all(db):
        files = registry.export_files(v)
        main = next(p for p in files if p.endswith((".yaml", ".json")))
        folder = main.rsplit("/", 1)[0] + "/" if "/" in main else ""
        rel_files = {p.removeprefix(folder): t for p, t in files.items() if p != main}
        parsed = parse_definition(v.kind, v.key, files[main], rel_files, main)
        assert digest(parsed) == v.digest, (v.kind, v.key)
    agent_files = registry.export_files(registry.latest(db, "agent", "helper-agent"))
    assert sorted(agent_files) == [
        "agents/helper-agent/agent.yaml",
        "agents/helper-agent/instructions.md",
        "agents/helper-agent/skills/lookup.md",
    ]
    assert agent_files["agents/helper-agent/agent.yaml"].startswith("kind: agent\nkey: helper-agent\n")


def test_latest_bundle_validates_clean(db, bundle):
    registry.apply_bundle(db, bundle)
    stored = registry.latest_bundle(db)
    assert sorted(stored.items) == sorted(bundle.items)
    assert validate_bundle(stored) == []


# --- CLI -------------------------------------------------------------------------------------------


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "app.defs", *args], cwd=API_DIR, capture_output=True, text=True, timeout=60
    )


def test_cli_validate_ok_and_failure(tmp_path):
    ok = run_cli("validate", "--dir", str(FIXTURE))
    assert ok.returncode == 0 and "11 definitions" in ok.stdout

    broken = tmp_path / "defs"
    (broken / "decisions").mkdir(parents=True)
    (broken / "decisions" / "bad.yaml").write_text(
        "kind: decision_rules\nkey: bad\nquestion: q\n", encoding="utf-8"
    )
    bad = run_cli("validate", "--dir", str(broken))
    assert bad.returncode == 1 and "decision_rules/bad" in bad.stderr
