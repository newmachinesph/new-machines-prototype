"""A business adds its own memory: POST /v1/memory writes an org-scoped row in the live workspace (recalled
by the org's runs only, retractable by its owners and admins like any own item) and a fixture item in the
demo; GET /v1/memory/spaces lists where it can go; owners and admins only; at most 100 active team items."""

import pytest

from app import auth, live_work
from app.routers import memory as memory_router
from app.runtime import memory
from tests.test_live_catalog import _rows, ana, ben, live, starts  # noqa: F401  (fixtures)
from tests.test_live_connections_guards import _as_role

SPACE = "retail-commerce"
SPACE_NAME = "Retail & Commerce company knowledge"
TEXT = "Never refund an opened item without a person's approval."
QUERY = "refund opened item"
MANAGERS_ONLY = "Only owners and admins can retract a memory added by your team."


def _recalled(db, org_id: str | None) -> set[str]:
    return {i["id"] for i in memory.recall(db, SPACE, QUERY, limit=50, org_id=org_id)}


def _team_items(db) -> int:
    return _rows(db, "SELECT count(*) AS n FROM memory_items WHERE source = 'team'")[0]["n"]


def _status(db, item_id: str) -> str:
    return _rows(db, "SELECT status FROM memory_items WHERE id = %s", item_id)[0]["status"]


def _add(user, text: str = TEXT, space: str = SPACE):
    return user.post("/v1/memory", json={"space": space, "text": text})


def test_an_owner_adds_a_memory_that_only_the_orgs_runs_recall(ana, ben, db):  # noqa: F811
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


def test_an_admin_adds_a_memory_and_the_org_retracts_it(ana, db):  # noqa: F811
    _as_role(db, ana, "admin")
    added = _add(ana)
    assert added.status_code == 201, added.text
    item_id = added.json()["id"]
    assert item_id in _recalled(db, ana.org_id)
    res = ana.post(f"/v1/memory/{item_id}:retract")
    assert res.status_code == 200 and res.json()["retracted"] is True
    assert item_id not in _recalled(db, ana.org_id)


def test_a_member_retracts_a_runs_item_but_not_the_teams(ana, ben, db):  # noqa: F811
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
def test_a_member_or_reviewer_cannot_add_a_memory(ana, db, role):  # noqa: F811
    _as_role(db, ana, role)
    res = _add(ana)
    assert res.status_code == 403, res.text
    assert res.json()["code"] == "POLICY_DENIED"
    assert _team_items(db) == 0


def test_active_team_items_are_capped_per_org(ana, ben, db, monkeypatch):  # noqa: F811
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
def test_an_unknown_space_or_bad_text_is_422_and_writes_nothing(ana, db, body):  # noqa: F811
    res = ana.post("/v1/memory", json=body)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "SCHEMA_INVALID"
    assert _team_items(db) == 0


@pytest.mark.parametrize("text", ["\x00", "a\x00b", "a\x1bb", "a\x7fb", "a\rb", "a\x0bb", "a\x08b"])
def test_control_characters_are_422_not_500(ana, db, text):  # noqa: F811
    res = _add(ana, text)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "SCHEMA_INVALID"
    assert _team_items(db) == 0


def test_text_of_the_full_length_with_newlines_and_tabs_is_accepted(ana, db):  # noqa: F811
    res = _add(ana, "Line one.\n\tLine two." + "x" * 1980)  # 20 characters, then 1980: the limit exactly
    assert res.status_code == 201, res.text
    assert len(res.json()["text"]) == 2000
    assert _team_items(db) == 1


def test_the_spaces_an_org_adds_to_are_the_ones_it_reads(ana):  # noqa: F811
    spaces = ana.get("/v1/memory/spaces").json()
    assert {"id": SPACE, "name": SPACE_NAME} in spaces
    assert {s["id"] for s in spaces} == set(live_work.readable_spaces(ana.org_id))


def test_a_space_another_org_reads_is_not_offered_and_is_422(ana, ben, db, monkeypatch):  # noqa: F811
    bodies = live_work.latest_bodies("memory_space")
    theirs = {**bodies, "ben-notes": {"name": "Ben's notes", "readers": [ben.org_id]}}
    monkeypatch.setattr(live_work, "latest_bodies", lambda kind, org_id=None: theirs)
    assert "ben-notes" not in {s["id"] for s in ana.get("/v1/memory/spaces").json()}
    assert {"id": "ben-notes", "name": "Ben's notes"} in ben.get("/v1/memory/spaces").json()
    res = _add(ana, space="ben-notes")
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "SCHEMA_INVALID"
    assert _team_items(db) == 0
    assert _add(ben, space="ben-notes").status_code == 201


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
