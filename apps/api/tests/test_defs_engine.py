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
from app.defs.model import Bundle, path_for
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


def test_shared_schemas_load_under_the_shared_prefix():
    real = load_bundle(settings.defs_dir())
    drafts = real.get("schema", "shared/drafts")
    assert drafts is not None and drafts.path == "schemas/drafts.json"
    assert path_for("schema", "shared/drafts") == "schemas/drafts.json"
    assert path_for("schema", "demo-pack/input") == "packs/demo-pack/schemas/input.json"
    assert real.get("schema", "shared/review-items") is not None


def test_fixture_bundle_is_valid(bundle):
    assert validate_bundle(bundle) == []


def test_parse_definition_rejects_mismatched_key():
    with pytest.raises(LoadError):
        parse_definition("connector", "shop", "kind: connector\nkey: other\n", {}, "connectors/shop.yaml")


def test_parse_definition_rejects_bad_yaml():
    with pytest.raises(LoadError):
        parse_definition("connector", "shop", "a: [", {}, "connectors/shop.yaml")


def test_load_bundle_rejects_an_owner_namespaced_key(tmp_path):
    """A key with "--" belongs to a workspace's own definitions, so the files can never take one."""
    (tmp_path / "connectors").mkdir()
    text = "kind: connector\nkey: org-1--shop\napp: Shop\ntools: []\n"
    (tmp_path / "connectors" / "shop.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(LoadError, match="org-1--shop"):
        load_bundle(tmp_path)


# --- validation ------------------------------------------------------------------------------------


def test_route_to_missing_node(bundle):
    bad = mutated(bundle, "workflow", "demo-pack", lambda b, f: b["nodes"][0]["routes"].update(next="ghost"))
    err = only_error(bad, mentions="'ghost'", kind="workflow")
    assert "nodes[0]" in err.message and err.path == "packs/demo-pack/workflow.yaml"


def test_agent_tool_not_in_any_connector(bundle):
    bad = mutated(bundle, "agent", "helper-agent", lambda b, f: b["runtime"]["tools"].append("shop.missing"))
    only_error(bad, mentions="shop.missing", kind="agent")


def _team_agent_needing_thread(bundle: Bundle, *, maps: dict | None) -> Bundle:
    """The fixture pack running an org-built copy of helper-agent whose input schema requires thread_id."""
    key = "org-abc--helper"
    agent = bundle.get("agent", "helper-agent")
    body = {**copy.deepcopy(agent.body), "agent_id": key, "input_schema_ref": "demo-pack/input"}
    schema = bundle.get("schema", "demo-pack/input")
    items = dict(bundle.items)
    items[("agent", key)] = replace(agent, key=key, body=body, path=path_for("agent", key))
    items[("schema", "demo-pack/input")] = replace(
        schema,
        body={**schema.body, "required": ["thread_id"], "properties": {"thread_id": {"type": "string"}}},
    )
    wf = bundle.get("workflow", "demo-pack")
    nodes = copy.deepcopy(wf.body["nodes"])
    nodes[1]["config"]["agent"] = key
    if maps is not None:
        nodes[1]["config"]["inputs"] = maps
    items[("workflow", "demo-pack")] = replace(wf, body={**wf.body, "nodes": nodes})
    return Bundle(items=items)


def test_agent_step_must_map_the_agents_required_inputs(bundle):
    errors = validate_bundle(_team_agent_needing_thread(bundle, maps=None))
    messages = [e.message for e in errors if e.kind == "workflow"]
    assert len(messages) == 1 and "nodes[1] (analyse)" in messages[0] and "thread_id" in messages[0]


def test_agent_step_that_maps_every_required_input_is_valid(bundle):
    assert validate_bundle(_team_agent_needing_thread(bundle, maps={"thread_id": "=x"})) == []


def test_the_exempt_listing_check_name_is_the_studios_check_pack_name():
    """validate cannot import studio (studio imports validate), so the two copies must agree."""
    from app import studio
    from app.defs import validate

    assert validate.LISTING_CHECK == studio.CHECK_NAME


def test_cel_syntax_error_in_decision_rule(bundle):
    bad = mutated(
        bundle, "decision_rules", "triage", lambda b, f: b["rules"][0].update(when="facts.total_minor <")
    )
    only_error(bad, mentions="rules[0].when", kind="decision_rules")


def test_cel_syntax_error_in_workflow_argument(bundle):
    bad = mutated(bundle, "workflow", "demo-pack", lambda b, f: b["nodes"][1]["config"].update(input="=run."))
    only_error(bad, mentions="config.input", kind="workflow")


def _view(**items) -> dict:
    return {
        "kind": "Email drafts",
        "summary": "=string(size(deliverable.drafts)) + ' drafts'",
        "facts": [{"label": "Drafts created", "value": "=size(deliverable.drafts)"}],
        "items": {"from": "=deliverable.drafts", "label": "=item.to", "detail": "=item.body"} | items,
    }


def test_a_pack_deliverable_view_is_valid(bundle):
    good = mutated(bundle, "pack", "demo-pack", lambda b, f: b.update(deliverable_view=_view()))
    assert validate_bundle(good) == []


def test_cel_syntax_error_in_pack_deliverable_view(bundle):
    bad = mutated(bundle, "pack", "demo-pack", lambda b, f: b.update(deliverable_view=_view(label="=item.")))
    only_error(bad, mentions="deliverable_view.items.label", kind="pack")


def test_pack_deliverable_view_kind_and_labels_are_not_cel(bundle):
    view = _view() | {"kind": "=Drafts ("}
    view["facts"][0]["label"] = "=Count ("
    ok = mutated(bundle, "pack", "demo-pack", lambda b, f: b.update(deliverable_view=view))
    assert validate_bundle(ok) == []  # shown as written, never compiled


def test_cel_syntax_error_in_a_deliverable_view_fact_value(bundle):
    view = _view()
    view["facts"][0]["value"] = "=size("
    bad = mutated(bundle, "pack", "demo-pack", lambda b, f: b.update(deliverable_view=view))
    only_error(bad, mentions="deliverable_view.facts[0].value", kind="pack")


def test_pack_deliverable_view_shape_is_checked(bundle):
    view = _view() | {"kind": "x" * 41}
    bad = mutated(bundle, "pack", "demo-pack", lambda b, f: b.update(deliverable_view=view))
    only_error(bad, mentions="deliverable_view.kind", kind="pack")


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


def _memory(db) -> list[tuple[str, str, str, str]]:
    """Every memory row (ids aside), sorted: a list, so a duplicated row shows up."""
    db.commit()
    rows = db.execute("SELECT space, text, source, org_id FROM memory_items").fetchall()
    return sorted((r["space"], r["text"], r["source"], r["org_id"] or "") for r in rows)


def test_apply_keeps_seed_items_equal_to_the_file(db, bundle):
    registry.apply_bundle(db, bundle)
    [old] = bundle.get("memory_space", "notes").body["seed_items"]
    others = [
        ("mem_console0001", "notes", "Added by an operator.", "console", None),
        ("mem_org00000001", "notes", "Learned in a run.", "run:run_1", "org_a"),
        ("mem_other000001", "other-space", old, "seed", None),
    ]
    for row in others:
        db.execute(
            "INSERT INTO memory_items (id, space, text, source, created_by, org_id) "
            "VALUES (%s, %s, %s, %s, 'x', %s)",
            row,
        )
    db.commit()
    reworded = mutated(
        bundle,
        "memory_space",
        "notes",
        lambda b, f: b.update(seed_items=["Orders over 200 USD need a look.", "New."]),
    )
    registry.apply_bundle(db, reworded)
    after = _memory(db)
    # The reworded seed replaces the old one; the operator's, the org's and another space's rows stay.
    assert after == sorted(
        [
            ("notes", "Orders over 200 USD need a look.", "seed", ""),
            ("notes", "New.", "seed", ""),
            *((space, text, source, org or "") for _, space, text, source, org in others),
        ]
    )
    registry.apply_bundle(db, reworded)
    assert _memory(db) == after  # a second apply changes nothing


def test_apply_leaves_the_seeds_of_a_console_published_memory_space_alone(db, bundle, caplog):
    registry.apply_bundle(db, bundle)
    notes = bundle.get("memory_space", "notes")
    [old] = notes.body["seed_items"]
    registry.publish(db, replace(notes, body={**notes.body, "seed_items": [old, "Console seed."]}), "a", "r")
    db.commit()
    before = _memory(db)
    reworded = mutated(bundle, "memory_space", "notes", lambda b, f: b.update(seed_items=["From the file."]))
    with caplog.at_level("INFO", logger="app.defs.registry"):
        registry.apply_bundle(db, reworded)
    # The operator's version stays the space's definition, so the file's seed_items do not replace its seeds.
    assert _memory(db) == before
    skipped = [r for r in caplog.records if r.levelname == "INFO" and "memory_space/notes" in r.getMessage()]
    assert len(skipped) == 1
    registry.apply_bundle(db, reworded, force=True)  # force applies the file, seeds included
    assert _memory(db) == [("notes", "From the file.", "seed", "")]


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
