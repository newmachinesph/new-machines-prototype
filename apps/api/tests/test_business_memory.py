"""A business adds its own memory: POST /v1/memory writes an org-scoped row in the live workspace (recalled
by the org's runs only, retractable by its owners and admins like any own item) and a fixture item in the
demo; GET /v1/memory/spaces lists where it can go; owners and admins only; at most 100 active team items.

Shared memory follows the packs a business has added: a new business with no packs sees no other business's
policies, and a memory can only be added to a space one of its packs uses."""

from dataclasses import replace

import pytest

from app import auth, live_catalog, live_work, settings
from app.defs import registry
from app.defs.loader import load_bundle
from app.routers import memory as memory_router
from app.runtime import memory
from tests.test_live_catalog import PACK, _rows, ana, ben, live, starts  # noqa: F401  (fixtures)
from tests.test_live_connections_guards import _as_role

SPACE = "retail-commerce"  # used by the reconciliation pack (PACK)
SPACE_NAME = "Retail & Commerce company knowledge"
O2C = "order-to-cash-exception-desk"
O2C_SPACE, O2C_SPACE_NAME = "o2c-policy", "Order-to-cash policy"
SEED_LABEL = "Definitions seed"
TEXT = "Never refund an opened item without a person's approval."
QUERY = "refund opened item"
MANAGERS_ONLY = "Only owners and admins can retract a memory added by your team."
NO_PACK_USES = "space: none of the packs you have added uses {name}. Add a pack first."
# The o2c-policy seed on payment terms as it was worded before the field name was written out.
OLD_SEED = (
    "Payment terms are per customer. An invoice is past its terms only when the days since its invoice date "
    "are more than the customer's payment_terms_days; 0-day terms mean payment is due on delivery."
)


def _recalled(db, org_id: str | None) -> set[str]:
    return {i["id"] for i in memory.recall(db, SPACE, QUERY, limit=50, org_id=org_id)}


def _team_items(db) -> int:
    return _rows(db, "SELECT count(*) AS n FROM memory_items WHERE source = 'team'")[0]["n"]


def _status(db, item_id: str) -> str:
    return _rows(db, "SELECT status FROM memory_items WHERE id = %s", item_id)[0]["status"]


def _add(user, text: str = TEXT, space: str = SPACE):
    return user.post("/v1/memory", json={"space": space, "text": text})


def _hire(user, slug: str) -> None:
    body = {"packSlug": slug, "capMinor": 2000, "reviewerPool": "team_then_network"}
    res = user.post(f"/v1/organizations/{user.org_id}/agent-installations", json=body)
    assert res.status_code == 201, res.text


def _seed_items(space: str) -> list[str]:
    return list(live_work.latest_bodies("memory_space")[space]["seed_items"])


def _in_use(org_id: str) -> set[str]:
    return set(live_work.spaces_in_use(org_id, live_work.readable_spaces(org_id)))


def _seed_texts(db, space: str) -> set[str]:
    rows = _rows(
        db, "SELECT text FROM memory_items WHERE space = %s AND source = 'seed' AND org_id IS NULL", space
    )
    return {r["text"] for r in rows}


@pytest.fixture
def hired(ana, ben):  # noqa: F811
    """Both businesses have added the reconciliation pack, so the retail-commerce space is in use."""
    for user in (ana, ben):
        _hire(user, PACK)


# --- shared memory follows the packs a business has added ------------------------------------------------


def test_a_new_business_with_no_packs_sees_no_shared_memory_and_has_nowhere_to_add(ana, db):  # noqa: F811
    assert _rows(db, "SELECT count(*) AS n FROM memory_items WHERE source = 'seed'")[0]["n"] > 0
    assert ana.get("/v1/memory").json() == []
    assert ana.get("/v1/memory/spaces").json() == []
    res = _add(ana)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "SCHEMA_INVALID"
    assert res.json()["detail"] == NO_PACK_USES.format(name=SPACE_NAME)
    assert _team_items(db) == 0


def test_adding_the_o2c_pack_brings_its_space_and_seeds_into_use(ana, ben, db):  # noqa: F811
    _hire(ana, O2C)
    listed = ana.get("/v1/memory").json()
    assert listed and all(m["source"] == SEED_LABEL and m["scopeName"] == O2C_SPACE_NAME for m in listed)
    assert sorted(m["text"] for m in listed) == sorted(_seed_items(O2C_SPACE))
    assert ana.get("/v1/memory/spaces").json() == [{"id": O2C_SPACE, "name": O2C_SPACE_NAME}]
    assert _add(ana, "Chase nothing on public holidays.", O2C_SPACE).status_code == 201
    other = _add(ana, space=SPACE)  # readable, but no pack of Ana's uses it
    assert other.status_code == 422 and other.json()["detail"] == NO_PACK_USES.format(name=SPACE_NAME)
    assert ben.get("/v1/memory").json() == [] and ben.get("/v1/memory/spaces").json() == []
    _hire(ana, PACK)
    assert {m["scopeName"] for m in ana.get("/v1/memory").json()} == {O2C_SPACE_NAME, SPACE_NAME}
    assert {s["id"] for s in ana.get("/v1/memory/spaces").json()} == {O2C_SPACE, SPACE}


def test_an_orgs_own_item_stays_listed_when_no_pack_uses_its_space(ana, db):  # noqa: F811
    run = memory.remember(
        db, SPACE, "Payouts batch on Fridays.", "run:run_a:recall:1", "workflow", ana.org_id
    )
    db.commit()
    listed = ana.get("/v1/memory").json()
    assert [m["id"] for m in listed] == [run["id"]]
    assert listed[0]["scopeName"] == SPACE_NAME and listed[0]["source"] == "Run run_a"


def test_a_packs_spaces_come_from_its_workflow_and_agents(ana):  # noqa: F811
    defs = live_catalog.definitions(None)
    by_slug = {live_catalog.slug_of(v): live_work.pack_spaces(defs, v.body) for v in defs.packs()}
    assert by_slug[PACK] == {SPACE}
    assert by_slug[O2C] == {O2C_SPACE}
    assert by_slug["refund-triage"] == by_slug["overdue-invoice-follow-up"] == {"customer-accounts"}
    assert by_slug["inbox-lead-tracker"] == set()  # no memory node and no agent that writes a space
    # An agent that writes a space counts even without a memory node in the workflow.
    pack = {"workflow": "no-such-workflow", "agents": ["o2c-triage-agent"]}
    assert live_work.pack_spaces(defs, pack) == {O2C_SPACE}


def test_the_spaces_in_use_follow_the_pack_version_an_installation_pins(ana, ben, db):  # noqa: F811
    """Ana added the reconciliation pack at version 1. Version 2 adds an agent that writes o2c-policy; Ben
    adds the pack after that. Each sees the spaces of the version their runs recall from."""
    _hire(ana, PACK)
    pack = load_bundle(settings.defs_dir()).get("pack", PACK)
    agents = [*pack.body["agents"], "o2c-triage-agent"]
    registry.publish(db, replace(pack, body={**pack.body, "agents": agents}), "ops", "writes o2c-policy too")
    db.commit()
    _hire(ben, PACK)
    pinned = _rows(db, "SELECT org_id, pack_version FROM installations ORDER BY pack_version")
    assert pinned == [{"org_id": ana.org_id, "pack_version": 1}, {"org_id": ben.org_id, "pack_version": 2}]
    assert _in_use(ana.org_id) == {SPACE}
    assert _in_use(ben.org_id) == {SPACE, O2C_SPACE}
    assert {s["id"] for s in ana.get("/v1/memory/spaces").json()} == {SPACE}
    assert {s["id"] for s in ben.get("/v1/memory/spaces").json()} == {SPACE, O2C_SPACE}
    assert {m["scopeName"] for m in ana.get("/v1/memory").json()} == {SPACE_NAME}
    assert {m["scopeName"] for m in ben.get("/v1/memory").json()} == {SPACE_NAME, O2C_SPACE_NAME}
    assert _add(ana, space=O2C_SPACE).status_code == 422 and _add(ben, space=O2C_SPACE).status_code == 201


def test_applying_the_definitions_retires_a_reworded_seed_and_keeps_the_teams_items(ana, db):  # noqa: F811
    _hire(ana, O2C)
    team = _add(ana, "Chase nothing on public holidays.", O2C_SPACE).json()["id"]
    db.execute(
        "INSERT INTO memory_items (id, space, text, source, created_by) VALUES (%s, %s, %s, 'seed', 'apply')",
        ("mem_old_seed", O2C_SPACE, OLD_SEED),
    )
    db.commit()
    assert OLD_SEED in _seed_texts(db, O2C_SPACE)
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    texts = _seed_texts(db, O2C_SPACE)
    assert OLD_SEED not in texts and texts == set(_seed_items(O2C_SPACE))
    assert any("the customer's payment terms in days" in t for t in texts)
    assert _rows(db, "SELECT id FROM memory_items WHERE id = 'mem_old_seed'") == []
    assert _status(db, team) == "active"
    listed = {m["id"]: m["text"] for m in ana.get("/v1/memory").json()}
    assert team in listed and OLD_SEED not in listed.values()


def test_applying_the_definitions_again_keeps_the_seeds_as_they_are(db, starts):  # noqa: F811
    before = _rows(db, "SELECT id, space, text FROM memory_items WHERE source = 'seed' ORDER BY id")
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    assert _rows(db, "SELECT id, space, text FROM memory_items WHERE source = 'seed' ORDER BY id") == before
    for space, body in live_work.latest_bodies("memory_space").items():
        texts = {r["text"] for r in before if r["space"] == space}
        assert texts == set(body["seed_items"]), space


# --- the business's own memory ---------------------------------------------------------------------------


def test_an_owner_adds_a_memory_that_only_the_orgs_runs_recall(hired, ana, ben, db):  # noqa: F811
    res = _add(ana, f"  {TEXT}  ")
    assert res.status_code == 201, res.text
    item = res.json()
    assert item["text"] == TEXT  # trimmed
    assert (item["state"], item["source"], item["scopeName"]) == ("APPROVED", "Your team", SPACE_NAME)
    assert item["proposedBy"] == "uid_ana" and "retracted" not in item and "sourceRun" not in item
    [row] = _rows(db, "SELECT org_id, source, status, created_by FROM memory_items WHERE id = %s", item["id"])
    assert row == {"org_id": ana.org_id, "source": "team", "status": "active", "created_by": "uid_ana"}
    listed = {m["id"]: m for m in ana.get("/v1/memory").json()}
    assert listed[item["id"]]["source"] == "Your team" and listed[item["id"]]["state"] == "APPROVED"
    assert item["id"] not in {m["id"] for m in ben.get("/v1/memory").json()}
    assert item["id"] in _recalled(db, ana.org_id)
    assert item["id"] not in _recalled(db, ben.org_id)
    assert item["id"] not in _recalled(db, None)  # a run without an org recalls shared items only


def test_an_admin_adds_a_memory_and_the_org_retracts_it(hired, ana, db):  # noqa: F811
    _as_role(db, ana, "admin")
    added = _add(ana)
    assert added.status_code == 201, added.text
    item_id = added.json()["id"]
    assert item_id in _recalled(db, ana.org_id)
    res = ana.post(f"/v1/memory/{item_id}:retract")
    assert res.status_code == 200 and res.json()["retracted"] is True
    assert item_id not in _recalled(db, ana.org_id)


def test_a_member_retracts_a_runs_item_but_not_the_teams(hired, ana, ben, db):  # noqa: F811
    team = _add(ana).json()["id"]
    run = memory.remember(
        db, SPACE, "Payouts batch on Fridays.", "run:run_a:recall:1", "workflow", ana.org_id
    )
    db.commit()
    assert ben.post(f"/v1/memory/{team}:retract").status_code == 404  # another org's item
    _as_role(db, ana, "member")
    res = ana.post(f"/v1/memory/{team}:retract")
    assert res.status_code == 403, res.text
    assert (res.json()["code"], res.json()["detail"]) == ("POLICY_DENIED", MANAGERS_ONLY)
    assert _status(db, team) == "active"
    assert team in _recalled(db, ana.org_id)
    assert ana.post(f"/v1/memory/{run['id']}:retract").json()["retracted"] is True  # today's rule for runs


@pytest.mark.parametrize("role", ["member", "reviewer"])
def test_a_member_or_reviewer_cannot_add_a_memory(hired, ana, db, role):  # noqa: F811
    _as_role(db, ana, role)
    res = _add(ana)
    assert res.status_code == 403, res.text
    assert res.json()["code"] == "POLICY_DENIED"
    assert _team_items(db) == 0


def test_active_team_items_are_capped_per_org(hired, ana, ben, db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(live_work, "MAX_TEAM_MEMORY", 2)
    first = _add(ana, "Rule one.").json()["id"]
    assert _add(ana, "Rule two.").status_code == 201
    memory.remember(db, SPACE, "A run's item does not count.", "run:run_a:n:1", "workflow", ana.org_id)
    db.commit()
    res = _add(ana, "Rule three.")
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "CONFLICT"
    assert res.json()["detail"] == (
        "Your workspace has 2 memories added by your team. Retract one before adding another."
    )
    assert _team_items(db) == 2
    assert _add(ben, "Another org's rule.").status_code == 201  # the cap is per org
    assert ana.post(f"/v1/memory/{first}:retract").status_code == 200
    assert _add(ana, "Rule three.").status_code == 201  # a retracted item frees its place


@pytest.mark.parametrize(
    "body",
    [
        {"space": "no-such-space", "text": TEXT},
        {"space": "", "text": TEXT},
        {"space": SPACE, "text": "   "},
        {"space": SPACE, "text": "x" * 2001},
        {"space": SPACE},
        {"space": SPACE, "text": TEXT, "source": "seed"},
    ],
)
def test_an_unknown_space_or_bad_text_is_422_and_writes_nothing(hired, ana, db, body):  # noqa: F811
    res = ana.post("/v1/memory", json=body)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "SCHEMA_INVALID"
    assert _team_items(db) == 0


@pytest.mark.parametrize("text", ["\x00", "a\x00b", "a\x1bb", "a\x7fb", "a\x0bb", "a\x08b"])
def test_control_characters_are_422_not_500(hired, ana, db, text):  # noqa: F811
    res = _add(ana, text)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "SCHEMA_INVALID"
    assert _team_items(db) == 0


def test_windows_and_mac_line_endings_are_stored_as_newlines(hired, ana, db):  # noqa: F811
    res = _add(ana, "Line one.\r\nLine two.\rLine three.")
    assert res.status_code == 201, res.text
    assert res.json()["text"] == "Line one.\nLine two.\nLine three."
    # The limit applies to the stored text: 2001 characters as sent, 2000 once "\r\n" is one character.
    res = _add(ana, "a\r\n" + "x" * 1998)
    assert res.status_code == 201, res.text
    assert len(res.json()["text"]) == 2000
    assert _team_items(db) == 2


def test_text_of_the_full_length_with_newlines_and_tabs_is_accepted(hired, ana, db):  # noqa: F811
    res = _add(ana, "Line one.\n\tLine two." + "x" * 1980)  # 20 characters, then 1980: the limit exactly
    assert res.status_code == 201, res.text
    assert len(res.json()["text"]) == 2000
    assert _team_items(db) == 1


def test_the_spaces_an_org_adds_to_are_the_ones_its_packs_use(hired, ana):  # noqa: F811
    spaces = ana.get("/v1/memory/spaces").json()
    assert spaces == [{"id": SPACE, "name": SPACE_NAME}]
    assert {s["id"] for s in spaces} == _in_use(ana.org_id)
    assert set(live_work.readable_spaces(ana.org_id)) > _in_use(ana.org_id)


def test_a_space_another_org_reads_is_not_offered_and_is_422(hired, ana, ben, db, monkeypatch):  # noqa: F811
    bodies = live_work.latest_bodies("memory_space")
    theirs = {**bodies, "ben-notes": {"name": "Ben's notes", "readers": [ben.org_id]}}
    monkeypatch.setattr(live_work, "latest_bodies", lambda kind, org_id=None: theirs)
    uses = live_work.pack_spaces  # the reconciliation pack uses ben-notes too
    monkeypatch.setattr(live_work, "pack_spaces", lambda defs, pack: uses(defs, pack) | {"ben-notes"})
    assert "ben-notes" not in {s["id"] for s in ana.get("/v1/memory/spaces").json()}
    assert {"id": "ben-notes", "name": "Ben's notes"} in ben.get("/v1/memory/spaces").json()
    res = _add(ana, space="ben-notes")
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "SCHEMA_INVALID"
    assert _team_items(db) == 0
    assert _add(ben, space="ben-notes").status_code == 201


# --- the demo workspace ------------------------------------------------------------------------------------


def test_in_the_demo_an_added_memory_joins_the_fixture_list_in_use(client):
    assert {"id": SPACE, "name": SPACE_NAME} in client.get("/v1/memory/spaces").json()
    res = client.post("/v1/memory", json={"space": SPACE, "text": TEXT})
    assert res.status_code == 201, res.text
    item = res.json()
    assert (item["state"], item["source"], item["scopeName"]) == ("APPROVED", "Your team", SPACE_NAME)
    assert item["proposedBy"] == "You"  # the dev actor has no name
    assert client.get("/v1/memory").json()[0]["id"] == item["id"]
    assert client.post(f"/v1/memory/{item['id']}:retract").json()["retracted"] is True
    assert client.post("/v1/memory", json={"space": "no-such-space", "text": TEXT}).status_code == 422


def test_in_the_demo_the_item_names_the_person_and_only_the_newest_team_items_stay(client, monkeypatch):
    ana_actor = auth.Actor(user_id="uid_ana", org_id=auth.DEMO_ORG_ID, name="Ana Reyes")
    monkeypatch.setattr(auth, "DEMO_ACTOR", ana_actor)
    monkeypatch.setattr(memory_router, "DEMO_TEAM_LIMIT", 2)
    ids = [
        client.post("/v1/memory", json={"space": SPACE, "text": f"Rule {n}."}).json()["id"] for n in (1, 2, 3)
    ]
    listed = client.get("/v1/memory").json()
    team = [m for m in listed if m["source"] == "Your team"]
    assert [m["id"] for m in team] == [ids[2], ids[1]]  # the oldest team item went
    assert all(m["proposedBy"] == "Ana Reyes" for m in team)
    assert len([m for m in listed if m["source"] != "Your team"]) == 5  # the fixtures stay


def test_in_the_demo_a_member_retracts_fixture_items_but_not_the_teams(client, monkeypatch):
    team = client.post("/v1/memory", json={"space": SPACE, "text": TEXT}).json()["id"]
    member = auth.Actor(user_id="user_demo", org_id=auth.DEMO_ORG_ID, role="member")
    monkeypatch.setattr(auth, "DEMO_ACTOR", member)
    res = client.post(f"/v1/memory/{team}:retract")
    assert res.status_code == 403 and res.json()["detail"] == MANAGERS_ONLY
    assert "retracted" not in next(m for m in client.get("/v1/memory").json() if m["id"] == team)
    assert client.post("/v1/memory/mem_212:retract").json()["retracted"] is True
