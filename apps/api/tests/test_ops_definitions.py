"""Operator endpoints for definitions, memory and real-run receipts. Needs Postgres (the `db` fixture); the
runtime is on with the real definitions bundle applied. Temporal is not needed."""

import pytest
import yaml
from fastapi.testclient import TestClient

from app import settings, temporal_client
from app.auth import OpsActor, get_ops_actor
from app.defs import refs, registry
from app.defs.loader import load_bundle
from app.main import create_app
from app.store import reset_store

PACK = "order-payment-reconciliation"
REASON = "Raise the turn limit"
START = {"packSlug": PACK, "input": "2026-10-06..2026-10-12", "budgetMinor": 2000}


@pytest.fixture
def api(db, monkeypatch) -> TestClient:
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    monkeypatch.setattr(temporal_client, "start_run", lambda *a, **k: None)
    monkeypatch.setattr(temporal_client, "terminate_run", lambda *a, **k: None)
    reset_store()
    return TestClient(create_app())


@pytest.fixture
def as_support(api):
    api.app.dependency_overrides[get_ops_actor] = lambda: OpsActor("u", "support@newmachin.es", "support")
    yield api
    api.app.dependency_overrides.clear()


def agent_edit(api, max_turns: int) -> dict:
    detail = api.get("/v1/ops/definitions/agent/finance-agent").json()
    text = detail["yaml"].replace("max_turns: 6", f"max_turns: {max_turns}")
    assert text != detail["yaml"]
    return {"yaml": text, "files": detail["files"]}


def broken_workflow(api) -> str:
    """The latest workflow YAML with the first node routed to a node that does not exist."""
    data = yaml.safe_load(api.get(f"/v1/ops/definitions/workflow/{PACK}").json()["yaml"])
    data["nodes"][0]["routes"]["next"] = "nowhere"
    return yaml.safe_dump(data, sort_keys=False)


def audit_for(api, target_type, target_id):
    return api.get("/v1/ops/audit", params={"targetType": target_type, "targetId": target_id}).json()


# --- refs (pure) ----------------------------------------------------------------------------------------


def test_refs_follow_pack_workflow_and_agent_links():
    bundle = load_bundle(settings.defs_dir())
    assert ("workflow", PACK) in refs.refs_in(bundle, "pack", PACK)
    assert ("agent", "finance-agent") in refs.refs_in(bundle, "pack", PACK)
    wf = refs.refs_in(bundle, "workflow", PACK)
    assert ("contract", PACK) in wf and ("memory_space", "retail-commerce") in wf
    assert ("connector", "shopify") in wf and ("schema", f"{PACK}/output") in wf
    assert ("pack", PACK) in refs.used_by(bundle, "workflow", PACK)
    assert ("models", "default") in refs.refs_in(bundle, "agent", "finance-agent")
    assert ("workflow", PACK) in refs.used_by(bundle, "memory_space", "retail-commerce")
    assert refs.refs_in(bundle, "agent", "nope") == []


# --- list and detail ------------------------------------------------------------------------------------


def test_list_shows_every_kind_of_the_bundle(api):
    rows = api.get("/v1/ops/definitions").json()
    bundle = load_bundle(settings.defs_dir())
    assert {(r["kind"], r["key"]) for r in rows} == set(bundle.items)
    assert {r["kind"] for r in rows} >= {"pack", "workflow", "contract", "agent", "connector", "models"}
    pack = next(r for r in rows if r["kind"] == "pack")
    assert pack["name"] == bundle.get("pack", PACK).body["name"]
    assert pack["version"] == 1 and pack["source"] == "file" and pack["digest"].startswith("sha256:")
    connector = next(r for r in rows if (r["kind"], r["key"]) == ("connector", "shopify"))
    assert connector["name"] == bundle.get("connector", "shopify").body["app"]
    rules = next(r for r in rows if r["kind"] == "decision_rules")
    assert rules["name"] == bundle.get("decision_rules", rules["key"]).body["question"]
    taxonomy = next(r for r in rows if r["kind"] == "taxonomy")
    assert taxonomy["name"] == "default"


def test_agent_detail_has_files_and_refs(api):
    detail = api.get("/v1/ops/definitions/agent/finance-agent").json()
    skills = [p for p in detail["files"] if p.startswith("skills/")]
    assert len(skills) == 2 and "instructions.md" in detail["files"]
    assert {"kind": "models", "key": "default"} in detail["refs"]
    assert {"kind": "pack", "key": PACK} in detail["usedBy"]
    assert detail["summary"]["version"] == 1 and [v["version"] for v in detail["versions"]] == [1]
    assert detail["yaml"].startswith("kind: agent\nkey: finance-agent\n")
    # The parsed body, so the console can read fields without a YAML parser.
    assert detail["body"]["runtime"]["model_profile"] == "reasoning"


def test_unknown_definition_version_and_kind(api):
    assert api.get("/v1/ops/definitions/agent/nope").status_code == 404
    assert api.get("/v1/ops/definitions/agent/finance-agent", params={"version": 9}).status_code == 404
    assert api.get("/v1/ops/definitions/widget/x").status_code == 422


def test_schema_keys_with_a_slash_are_reachable(api):
    detail = api.get(f"/v1/ops/definitions/schema/{PACK}/input").json()
    assert detail["summary"]["key"] == f"{PACK}/input"
    assert {"kind": "contract", "key": PACK} in detail["usedBy"]
    export = api.get(f"/v1/ops/definitions/schema/{PACK}/input/export").json()
    assert list(export["files"]) == [f"packs/{PACK}/schemas/input.json"]


# --- validate -------------------------------------------------------------------------------------------


def test_validate_accepts_the_unchanged_definition(api):
    detail = api.get(f"/v1/ops/definitions/workflow/{PACK}").json()
    res = api.post(f"/v1/ops/definitions/workflow/{PACK}:validate", json={"yaml": detail["yaml"]})
    assert res.status_code == 200 and res.json() == {"ok": True, "errors": []}


def test_validate_reports_a_route_to_a_missing_node(api):
    broken = broken_workflow(api)
    body = api.post(f"/v1/ops/definitions/workflow/{PACK}:validate", json={"yaml": broken}).json()
    assert body["ok"] is False
    [error] = body["errors"]
    assert error["kind"] == "workflow" and error["key"] == PACK
    assert "target node 'nowhere' does not exist" in error["message"] and "routes.next" in error["message"]
    assert api.get(f"/v1/ops/definitions/workflow/{PACK}").json()["summary"]["version"] == 1


def test_validate_reports_unparseable_yaml_and_bad_files(api):
    res = api.post("/v1/ops/definitions/agent/finance-agent:validate", json={"yaml": "a: [unclosed"}).json()
    assert res["ok"] is False and res["errors"][0]["path"] == "(root)"
    res = api.post(
        "/v1/ops/definitions/connector/shopify:validate",
        json={"yaml": "app: x", "files": {"../escape.md": "x"}},
    ).json()
    assert any("only agents" in e["message"] for e in res["errors"])
    agent = agent_edit(api, 7)
    agent["files"]["../escape.md"] = "x"
    res = api.post("/v1/ops/definitions/agent/finance-agent:validate", json=agent).json()
    assert any("stay inside" in e["message"] for e in res["errors"])


def test_kind_and_key_in_the_yaml_must_match_the_url(api):
    text = api.get("/v1/ops/definitions/agent/finance-agent").json()["yaml"]
    res = api.post("/v1/ops/definitions/agent/ops-agent:validate", json={"yaml": text})
    assert res.status_code == 422 and res.json()["code"] == "KEY_MISMATCH"
    res = api.post("/v1/ops/definitions/agent/ops-agent:publish", json={"yaml": text, "reason": REASON})
    assert res.status_code == 422 and res.json()["code"] == "KEY_MISMATCH"


def test_unparseable_yaml_gets_a_user_facing_message(api):
    res = api.post("/v1/ops/definitions/agent/finance-agent:validate", json={"yaml": "a: 1\nb: [unclosed"})
    [error] = res.json()["errors"]
    assert error["message"].startswith("YAML is not valid: line ")
    for internal in ("\\", ".py", "yaml/", "Traceback", "<"):
        assert internal not in error["message"]
    res = api.post("/v1/ops/definitions/schema/x/y:validate", json={"yaml": "{nope"})
    assert res.json()["errors"][0]["message"].startswith("JSON is not valid: line 1")
    res = api.post("/v1/ops/definitions/agent/finance-agent:validate", json={"yaml": "- a\n- b"})
    assert res.json()["errors"][0]["message"] == "The top level must be a mapping."


def test_yaml_anchors_aliases_and_oversized_text_are_refused(api):
    bomb = "a: &x [1, 2]\nb: *x\n"
    res = api.post("/v1/ops/definitions/agent/finance-agent:validate", json={"yaml": bomb})
    assert res.json()["ok"] is False and "anchors" in res.json()["errors"][0]["message"]
    res = api.post("/v1/ops/definitions/agent/finance-agent:publish", json={"yaml": bomb, "reason": REASON})
    assert res.status_code == 422 and res.json()["code"] == "INVALID_DEFINITION"
    big = "a: " + "x" * 65_536
    assert api.post("/v1/ops/definitions/agent/finance-agent:validate", json={"yaml": big}).status_code == 422
    files = {"instructions.md": "x" * 65_537}
    res = api.post("/v1/ops/definitions/agent/finance-agent:validate", json={"yaml": "a: 1", "files": files})
    assert res.status_code == 422


# --- create ---------------------------------------------------------------------------------------------


def publish_new(api, kind, key, text, files=None):
    body = {"yaml": text, "files": files or {}, "reason": "Add it"}
    return api.post(f"/v1/ops/definitions/{kind}/{key}:publish", json=body)


def copy_as(api, kind, key, new_key, **changes) -> str:
    data = yaml.safe_load(api.get(f"/v1/ops/definitions/{kind}/{key}").json()["yaml"])
    data["key"] = new_key
    data.update(changes)
    return yaml.safe_dump(data, sort_keys=False)


def test_create_a_memory_space_and_a_connector(api):
    space = copy_as(api, "memory_space", "retail-commerce", "returns-policy", name="Returns policy")
    checked = api.post("/v1/ops/definitions/memory_space/returns-policy:validate", json={"yaml": space})
    assert checked.json() == {"ok": True, "errors": []}
    res = publish_new(api, "memory_space", "returns-policy", space)
    assert res.status_code == 201, res.text
    assert res.json()["summary"]["version"] == 1 and res.json()["summary"]["source"] == "console"
    assert res.json()["summary"]["name"] == "Returns policy"
    connector = copy_as(api, "connector", "shopify", "shopify2")
    assert publish_new(api, "connector", "shopify2", connector).status_code == 201
    rows = {(r["kind"], r["key"]): r for r in api.get("/v1/ops/definitions").json()}
    assert rows[("memory_space", "returns-policy")]["version"] == 1
    assert rows[("connector", "shopify2")]["version"] == 1
    [entry] = audit_for(api, "definition", "memory_space/returns-policy")
    assert entry["action"] == "definition.create" and entry["summary"] == "created v1"
    assert api.get("/v1/ops/memory/spaces/returns-policy/items").json() == []
    assert publish_new(api, "memory_space", "returns-policy", space).status_code == 409


def test_create_a_pack_needs_its_workflow_and_contract_first(api):
    pack = copy_as(api, "pack", PACK, "new-pack", slug="new-pack", workflow="new-pack", contract="new-pack")
    res = publish_new(api, "pack", "new-pack", pack)
    assert res.status_code == 422 and res.json()["code"] == "INVALID_DEFINITION"
    messages = " ".join(e["message"] for e in res.json()["errors"])
    assert "workflow 'new-pack' does not exist" in messages
    assert "contract 'new-pack' does not exist" in messages
    assert audit_for(api, "definition", "pack/new-pack") == []

    contract = copy_as(api, "contract", PACK, "new-pack", contract_id="new-pack")
    wf = copy_as(api, "workflow", PACK, "new-pack", workflow_id="new-pack", work_contract_ref="new-pack")
    assert publish_new(api, "workflow", "new-pack", wf).status_code == 422  # contract not there yet
    assert publish_new(api, "contract", "new-pack", contract).status_code == 201
    assert publish_new(api, "workflow", "new-pack", wf).status_code == 201
    created = publish_new(api, "pack", "new-pack", pack)
    assert created.status_code == 201, created.text
    assert {"kind": "workflow", "key": "new-pack"} in created.json()["refs"]
    rows = {(r["kind"], r["key"]): r["version"] for r in api.get("/v1/ops/definitions").json()}
    assert [rows[(k, "new-pack")] for k in ("pack", "workflow", "contract")] == [1, 1, 1]


def test_create_an_agent_with_files(api):
    detail = api.get("/v1/ops/definitions/agent/finance-agent").json()
    text = copy_as(api, "agent", "finance-agent", "audit-agent", agent_id="audit-agent")
    res = publish_new(api, "agent", "audit-agent", text, detail["files"])
    assert res.status_code == 201, res.text
    assert set(res.json()["files"]) == set(detail["files"])


def test_new_keys_and_kinds_are_checked(api):
    text = "name: x\n"
    for key in ("Bad Key", "a" * 70, "UPPER", "a/b"):
        res = publish_new(api, "memory_space", key, text)
        assert res.status_code == 422 and res.json()["code"] == "INVALID_KEY"
    assert publish_new(api, "schema", "just-one", "{}").json()["code"] == "INVALID_KEY"
    assert publish_new(api, "taxonomy", "other", text).json()["code"] == "INVALID_KEY"
    assert publish_new(api, "widget", "x", text).status_code == 422


# --- publish --------------------------------------------------------------------------------------------


def test_publish_an_edit_makes_version_2_and_audits_it(api):
    res = api.post(
        "/v1/ops/definitions/agent/finance-agent:publish", json={**agent_edit(api, 7), "reason": REASON}
    )
    assert res.status_code == 201, res.text
    detail = res.json()
    assert detail["summary"]["version"] == 2 and detail["summary"]["source"] == "console"
    assert detail["summary"]["publishedBy"] == "ops@newmachin.es"
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert detail["versions"][0]["reason"] == REASON and "max_turns: 7" in detail["yaml"]
    [entry] = audit_for(api, "definition", "agent/finance-agent")
    assert entry["action"] == "definition.publish" and entry["summary"] == "v1 → v2"
    assert entry["reason"] == REASON
    old = api.get("/v1/ops/definitions/agent/finance-agent", params={"version": 1}).json()
    assert "max_turns: 6" in old["yaml"] and old["summary"]["version"] == 1
    assert len(old["versions"]) == 2


def test_publish_the_same_content_is_409_no_change(api):
    api.post("/v1/ops/definitions/agent/finance-agent:publish", json={**agent_edit(api, 7), "reason": REASON})
    again = api.get("/v1/ops/definitions/agent/finance-agent").json()
    res = api.post(
        "/v1/ops/definitions/agent/finance-agent:publish",
        json={"yaml": again["yaml"], "files": again["files"], "reason": REASON},
    )
    assert res.status_code == 409 and res.json()["code"] == "NO_CHANGE"
    assert api.get("/v1/ops/definitions/agent/finance-agent").json()["summary"]["version"] == 2


def test_publish_from_the_latest_base_version_succeeds(api):
    edit = {**agent_edit(api, 7), "reason": REASON, "baseVersion": 1}
    res = api.post("/v1/ops/definitions/agent/finance-agent:publish", json=edit)
    assert res.status_code == 201 and res.json()["summary"]["version"] == 2


def test_publish_from_a_stale_base_version_is_409_version_conflict(api):
    stale = {**agent_edit(api, 8), "reason": REASON, "baseVersion": 1}
    first = {**agent_edit(api, 7), "reason": REASON, "baseVersion": 1}
    assert api.post("/v1/ops/definitions/agent/finance-agent:publish", json=first).status_code == 201
    res = api.post("/v1/ops/definitions/agent/finance-agent:publish", json=stale)
    assert res.status_code == 409 and res.json()["code"] == "VERSION_CONFLICT"
    assert "v2" in res.json()["detail"] and "v1" in res.json()["detail"]
    latest = api.get("/v1/ops/definitions/agent/finance-agent").json()
    assert latest["summary"]["version"] == 2 and "max_turns: 7" in latest["yaml"]
    assert len(audit_for(api, "definition", "agent/finance-agent")) == 1


def test_a_new_definition_publishes_from_base_version_0_once(api):
    space = copy_as(api, "memory_space", "retail-commerce", "returns-policy", name="Returns policy")
    body = {"yaml": space, "reason": REASON, "baseVersion": 0}
    assert api.post("/v1/ops/definitions/memory_space/returns-policy:publish", json=body).status_code == 201
    other = copy_as(api, "memory_space", "retail-commerce", "returns-policy", name="Other policy")
    res = api.post("/v1/ops/definitions/memory_space/returns-policy:publish", json={**body, "yaml": other})
    assert res.status_code == 409 and res.json()["code"] == "VERSION_CONFLICT"


def test_a_negative_base_version_is_refused(api):
    edit = {**agent_edit(api, 7), "reason": REASON, "baseVersion": -1}
    res = api.post("/v1/ops/definitions/agent/finance-agent:publish", json=edit)
    assert res.status_code == 422 and res.json()["code"] == "SCHEMA_INVALID"


def test_publish_an_invalid_edit_is_422_with_errors_and_nothing_changes(api):
    broken = broken_workflow(api)
    res = api.post(f"/v1/ops/definitions/workflow/{PACK}:publish", json={"yaml": broken, "reason": REASON})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "INVALID_DEFINITION"
    assert body["errors"][0]["key"] == PACK and "nowhere" in body["errors"][0]["message"]
    assert api.get(f"/v1/ops/definitions/workflow/{PACK}").json()["summary"]["version"] == 1
    assert audit_for(api, "definition", f"workflow/{PACK}") == []


def test_publish_requires_a_reason(api):
    res = api.post("/v1/ops/definitions/agent/finance-agent:publish", json=agent_edit(api, 7))
    assert res.status_code == 422 and res.json()["code"] == "SCHEMA_INVALID"


def test_support_can_read_but_not_write(as_support):
    api = as_support
    assert api.get("/v1/ops/definitions").status_code == 200
    assert api.get("/v1/ops/definitions/agent/finance-agent").status_code == 200
    assert (
        api.post("/v1/ops/definitions/agent/finance-agent:validate", json=agent_edit(api, 7)).status_code
        == 200
    )
    res = api.post(
        "/v1/ops/definitions/agent/finance-agent:publish", json={**agent_edit(api, 7), "reason": REASON}
    )
    assert res.status_code == 403
    assert api.get("/v1/ops/definitions/agent/finance-agent").json()["summary"]["version"] == 1
    assert (
        api.post(
            "/v1/ops/memory/spaces/retail-commerce/items", json={"text": "x", "reason": REASON}
        ).status_code
        == 403
    )
    assert api.post("/v1/ops/memory/items/mem_x:delete", json={"reason": REASON}).status_code == 403


# --- export ---------------------------------------------------------------------------------------------


def test_export_round_trips_through_the_loader(api, tmp_path):
    published = api.post(
        "/v1/ops/definitions/agent/finance-agent:publish", json={**agent_edit(api, 7), "reason": REASON}
    )
    assert published.status_code == 201
    latest = api.get("/v1/ops/definitions/agent/finance-agent/export").json()["files"]
    assert "max_turns: 7" in latest["agents/finance-agent/agent.yaml"]
    assert "agents/finance-agent/skills/match-orders.md" in latest
    first = api.get("/v1/ops/definitions/agent/finance-agent/export", params={"version": 1}).json()["files"]
    assert "max_turns: 6" in first["agents/finance-agent/agent.yaml"]
    assert api.get("/v1/ops/definitions/agent/finance-agent/export", params={"version": 5}).status_code == 404
    # Writing every definition's latest export out and loading it back gives the same bundle.
    for row in api.get("/v1/ops/definitions").json():
        files = api.get(f"/v1/ops/definitions/{row['kind']}/{row['key']}/export").json()["files"]
        for rel, text in files.items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    loaded = load_bundle(tmp_path)
    assert loaded.get("agent", "finance-agent").body["runtime"]["max_turns"] == 7
    assert set(loaded.items) == {(r["kind"], r["key"]) for r in api.get("/v1/ops/definitions").json()}


# --- memory ---------------------------------------------------------------------------------------------


def test_memory_add_list_and_delete_with_audit(api):
    spaces = api.get("/v1/ops/memory/spaces").json()
    space = next(s for s in spaces if s["key"] == "retail-commerce")
    assert space["name"] and space["itemCount"] >= 0
    before = space["itemCount"]
    res = api.post(
        "/v1/ops/memory/spaces/retail-commerce/items",
        json={"text": "  Refunds settle in 5 days.  ", "reason": "Learned from finance"},
    )
    assert res.status_code == 201
    item = res.json()
    assert item["text"] == "Refunds settle in 5 days." and item["source"] == "console"
    assert item["createdBy"] == "ops@newmachin.es" and item["space"] == "retail-commerce"
    items = api.get("/v1/ops/memory/spaces/retail-commerce/items").json()
    assert items[0]["id"] == item["id"] and len(items) == before + 1
    count = next(s for s in api.get("/v1/ops/memory/spaces").json() if s["key"] == "retail-commerce")
    assert count["itemCount"] == before + 1
    [added] = audit_for(api, "memory", item["id"])
    assert added["action"] == "memory.add" and "Refunds settle" in added["summary"]
    res = api.post(f"/v1/ops/memory/items/{item['id']}:delete", json={"reason": "Outdated"})
    assert res.status_code == 204
    assert all(i["id"] != item["id"] for i in api.get("/v1/ops/memory/spaces/retail-commerce/items").json())
    assert [e["action"] for e in audit_for(api, "memory", item["id"])] == ["memory.delete", "memory.add"]
    assert api.post(f"/v1/ops/memory/items/{item['id']}:delete", json={"reason": "again"}).status_code == 404


def test_memory_validation(api):
    url = "/v1/ops/memory/spaces/retail-commerce/items"
    assert (
        api.post("/v1/ops/memory/spaces/nope/items", json={"text": "x", "reason": REASON}).status_code == 404
    )
    assert api.get("/v1/ops/memory/spaces/nope/items").status_code == 404
    assert api.post(url, json={"text": "   ", "reason": REASON}).status_code == 422
    assert api.post(url, json={"text": "x" * 2001, "reason": REASON}).status_code == 422
    assert api.post(url, json={"text": "x" * 2000, "reason": REASON}).status_code == 201
    assert api.post(url, json={"text": "x"}).status_code == 422


# --- runs -----------------------------------------------------------------------------------------------


def test_ops_run_detail_has_the_run_and_its_receipt(api):
    started = api.post("/v1/workflow-runs", json=START)
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    detail = api.get(f"/v1/ops/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run"]["id"] == run_id and body["run"]["packSlug"] == PACK
    assert body["receipt"]["runId"] == run_id and body["receipt"]["verified"] is True
    assert body["receipt"]["items"][0]["type"] == "run.started"
    assert any(p["kind"] == "pack" for p in body["receipt"]["pinned"])
    listed = [r for r in api.get("/v1/ops/runs").json() if r["id"] == run_id]
    assert listed and listed[0]["tenantId"] == "org_hp01" and listed[0]["pack"] == PACK
    assert listed[0]["real"] is True
    assert api.get("/v1/ops/runs").json()[0]["id"] == run_id


def test_ops_run_detail_is_404_for_fixture_and_unknown_runs(api):
    fixture_id = api.get("/v1/workflow-runs").json()[0]["id"]
    assert api.get(f"/v1/ops/runs/{fixture_id}").status_code == 404
    assert api.get("/v1/ops/runs/run_nope").status_code == 404


# --- runtime off ----------------------------------------------------------------------------------------


def test_new_endpoints_are_503_with_the_runtime_off(client):
    for path in ("/v1/ops/definitions", "/v1/ops/memory/spaces", "/v1/ops/definitions/agent/x"):
        res = client.get(path)
        assert res.status_code == 503 and res.json()["code"] == "RUNTIME_UNAVAILABLE"
    assert client.get("/v1/ops/runs/run_2001").status_code == 404
    runs = client.get("/v1/ops/runs")
    assert runs.status_code == 200 and not any(r["real"] for r in runs.json())
