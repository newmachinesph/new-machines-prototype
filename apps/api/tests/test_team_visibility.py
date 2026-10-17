"""Sub-project C, part 2: an org's own packs and agents are seen, added and run by that org only. Every read
that lists definitions is checked across orgs."""

from app import live_catalog
from app.defs import owners, registry
from app.defs.model import Definition, path_for
from app.runtime import memory
from tests.team_seed import clone_agent, clone_pack
from tests.test_live_catalog import INPUT, PACK, PACK_NAME, As, _rows, ana, ben, live, starts  # noqa: F401
from tests.test_ops_state import OPS


def _add(user: As, slug: str):
    return user.post(
        f"/v1/organizations/{user.org_id}/agent-installations", json={"packSlug": slug, "capMinor": 2000}
    )


def _start(user: As, slug: str):
    return user.post("/v1/workflow-runs", json={"packSlug": slug, "input": INPUT, "budgetMinor": 1000})


def test_a_team_pack_is_in_its_own_orgs_marketplace_only(db, ana, ben):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    mine = {p["slug"]: p for p in ana.get("/v1/workflow-packs").json()}
    assert mine[key]["builtByTeam"] is True and mine[key]["certified"] is False
    assert "builtByTeam" not in mine[PACK] and mine[PACK]["certified"] is True
    assert key not in {p["slug"] for p in ben.get("/v1/workflow-packs").json()}
    assert ana.get(f"/v1/workflow-packs/{key}").json()["builtByTeam"] is True
    assert ben.get(f"/v1/workflow-packs/{key}").status_code == 404


def test_only_the_owning_org_can_add_and_run_a_team_pack(db, ana, ben, starts):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    assert _add(ben, key).status_code == 404
    assert _start(ben, key).status_code == 404
    assert _add(ana, key).status_code == 201
    for app in ("shopify", "stripe", "googlesheets"):
        assert ana.connect(app).status_code == 200
    res = _start(ana, key)
    assert res.status_code == 202, res.text
    assert starts.calls[-1][1] == ana.org_id
    assert _rows(db, "SELECT org_id, pack_slug FROM runs") == [{"org_id": ana.org_id, "pack_slug": key}]


def test_a_team_agent_is_in_its_own_orgs_catalog_only(db, ana, ben):  # noqa: F811
    key = clone_agent(db, "writer-agent", ana.org_id, "writer")
    mine = {a["id"]: a for a in ana.get("/v1/agents").json()}
    assert mine[key]["builtByTeam"] is True and mine[key]["certified"] is False
    assert "builtByTeam" not in mine["writer-agent"]
    assert key not in {a["id"] for a in ben.get("/v1/agents").json()}
    assert ana.get(f"/v1/agents/{key}").status_code == 200
    assert ben.get(f"/v1/agents/{key}").status_code == 404


def test_connections_follow_only_the_orgs_own_packs(db, ana, ben):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    assert _add(ana, key).status_code == 201
    assert {c["key"] for c in ana.get("/v1/connections").json()} == {"shopify", "stripe", "googlesheets"}
    assert ben.get("/v1/connections").json() == []
    # Connecting grants the team pack exactly what its own contract allows: every connection's grants for the
    # pack, taken together, are the contract's tool capabilities (the contract is the org's own copy).
    for app in ("shopify", "stripe", "googlesheets"):
        assert ana.connect(app).status_code == 200
    granted = {
        g["capability"]
        for c in ana.get("/v1/connections").json()
        for g in c["grants"]
        if g["install"] == f"Team {PACK_NAME}"
    }
    contract = registry.latest(db, "contract", key).body
    assert granted == set(contract["authorization"]["tool_capabilities"]) and granted


def test_suggest_never_offers_another_orgs_pack(db, ana, ben):  # noqa: F811
    title = "Zebra Quokka Wombat"
    # The title shares no word with any platform pack, so the only pack it can match is Ana's own.
    platform = live_catalog.definitions()
    clashing = [
        v.key
        for v in platform.packs()
        if live_catalog._words(title) & live_catalog._pack_words(platform, v.body).keys()
    ]
    assert clashing == [], f"pick a title no platform pack uses a word of: {clashing}"
    key = clone_pack(db, PACK, ana.org_id, "recon", title=title)
    mine = ana.post("/v1/workflow-packs:suggest", json={"text": title})
    assert mine.status_code == 200 and mine.json()["pack"]["slug"] == key
    theirs = ben.post("/v1/workflow-packs:suggest", json={"text": title})
    assert theirs.status_code == 200 and theirs.json().get("pack") is None


def test_an_agents_uses_never_name_another_orgs_pack(db, ana, ben):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    mine = {u["slug"] for a in ana.get("/v1/agents").json() for u in a["usedBy"]}
    assert {PACK, key} <= mine
    theirs = {u["slug"] for a in ben.get("/v1/agents").json() for u in a["usedBy"]}
    assert PACK in theirs and key not in theirs


def _own_space(db, org_id: str, name: str) -> str:
    """Publish a copy of the retail-commerce memory space as the org's own. Returns its key."""
    key = owners.org_key(org_id, name)
    body = {**registry.latest(db, "memory_space", "retail-commerce").body, "name": f"Team {name}"}
    registry.claim(db, "memory_space", key, owners.org_owner(org_id), "test")
    d = Definition(kind="memory_space", key=key, body=body, files={}, path=path_for("memory_space", key))
    registry.publish(db, d, "test", "team copy for a test", source=registry.BUILDER)
    db.commit()
    return key


def test_the_ops_console_never_lists_or_opens_an_orgs_own_memory_space(db, live_ops):
    owner = As(live_ops, "ana")
    key = _own_space(db, owner.org_id, "notes")
    listed = {s["key"] for s in live_ops.get("/v1/ops/memory/spaces", headers=OPS).json()}
    assert "retail-commerce" in listed and key not in listed
    assert live_ops.get(f"/v1/ops/memory/spaces/{key}/items", headers=OPS).status_code == 404
    body = {"text": "Hi", "reason": "Testing an org's own space"}
    assert live_ops.post(f"/v1/ops/memory/spaces/{key}/items", headers=OPS, json=body).status_code == 404


def test_the_ops_console_never_deletes_an_item_in_an_orgs_own_memory_space(db, live_ops):
    owner = As(live_ops, "ana")
    key = _own_space(db, owner.org_id, "notes")
    item = memory.remember(db, key, "Our notes.", "test", "uid_ana", owner.org_id)
    db.commit()
    body = {"reason": "Testing an org's own space"}
    res = live_ops.post(f"/v1/ops/memory/items/{item['id']}:delete", headers=OPS, json=body)
    assert res.status_code == 404 and key not in res.text
    assert _rows(db, "SELECT id FROM memory_items WHERE id = %s", item["id"]) == [{"id": item["id"]}]


def test_the_ops_console_never_lists_or_opens_an_orgs_own_definitions(db, live_ops):
    owner = As(live_ops, "ana")
    key = clone_pack(db, PACK, owner.org_id, "recon")
    listed = {(d["kind"], d["key"]) for d in live_ops.get("/v1/ops/definitions", headers=OPS).json()}
    assert ("pack", PACK) in listed and ("pack", key) not in listed
    for path in (f"/v1/ops/definitions/pack/{key}", f"/v1/ops/definitions/pack/{key}/export"):
        assert live_ops.get(path, headers=OPS).status_code == 404
    edit = live_ops.post(f"/v1/ops/definitions/pack/{key}:validate", headers=OPS, json={"yaml": "slug: x\n"})
    assert edit.status_code == 404


def test_the_ops_console_cannot_create_an_owner_namespaced_key(live_ops):
    body = {"yaml": '{"type": "object"}'}
    res = live_ops.post("/v1/ops/definitions/schema/shared/a--b:validate", headers=OPS, json=body)
    assert res.status_code == 422 and res.json()["code"] == "INVALID_KEY"
