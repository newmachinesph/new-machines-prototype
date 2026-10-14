"""Sub-project B, part 2: an org's own reviewers, Reviewer invitations and the org's reviewer network switch
(live workspace). Every route is checked from another org."""

import pytest

from tests.test_live_catalog import As, _rows
from tests.workforce_seed import add_run, add_task, live_api, put

CLAIMED = {"claimed_at": "2026-10-14T09:00:00Z"}


@pytest.fixture
def api(db, monkeypatch):
    client, _ = live_api(db, monkeypatch)
    return client


@pytest.fixture
def ana(api) -> As:
    return As(api, "ana")


@pytest.fixture
def ben(api) -> As:
    return As(api, "ben")


def _base(user: As, org_id: str | None) -> str:
    return f"/v1/organizations/{org_id or user.org_id}"


def _reviewers(user: As, org_id: str | None = None):
    return user.get(f"{_base(user, org_id)}/reviewers")


def _add(user: As, email: str, org_id: str | None = None):
    return user.post(f"{_base(user, org_id)}/reviewers", json={"email": email})


def _remove(user: As, email: str, org_id: str | None = None):
    return user.post(f"{_base(user, org_id)}/reviewers:remove", json={"email": email})


def _network(user: As, allow: bool, org_id: str | None = None):
    return put(user, f"{_base(user, org_id)}/reviewer-network", json={"allow": allow})


def _listed(user: As) -> list[tuple[str, str, bool]]:
    return [(r["email"], r["role"], r["pending"]) for r in _reviewers(user).json()["reviewers"]]


def _join(api, inviter: As, user: str) -> As:
    """`user` signs in and accepts their invitation to the inviter's org."""
    member = As(api, user)
    joined = member.post(f"/v1/invitations/{inviter.org_id}:accept")
    assert joined.status_code == 200, joined.text
    return member


def _invite_member(inviter: As, email: str):
    res = inviter.post(
        f"/v1/organizations/{inviter.org_id}/invitations", json={"email": email, "role": "Member"}
    )
    assert res.status_code == 201, res.text
    return res


def test_the_owner_starts_as_the_only_reviewer_with_the_network_off(ana):
    res = _reviewers(ana)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "allowNetwork": False,
        "reviewers": [{"email": "ana@example.com", "name": "Ana Reyes", "role": "owner", "pending": False}],
    }


def test_a_reviewer_invitation_is_accepted_explicitly(ana, api):
    res = _add(ana, "Rita@Example.com")
    assert res.status_code == 201, res.text
    assert res.json() == {
        "email": "rita@example.com",
        "name": "rita@example.com",
        "role": "reviewer",
        "pending": True,
    }
    rita = As(api, "rita")  # signing in gives her an org of her own; the invitation waits
    assert rita.org_id != ana.org_id
    invitations = rita.get("/v1/me").json()["invitations"]
    assert [(i["orgId"], i["role"]) for i in invitations] == [(ana.org_id, "reviewer")]
    joined = rita.post(f"/v1/invitations/{ana.org_id}:accept").json()
    assert (joined["orgId"], joined["role"]) == (ana.org_id, "reviewer")
    assert _listed(ana) == [("ana@example.com", "owner", False), ("rita@example.com", "reviewer", False)]


def test_a_member_gains_and_loses_the_capability_and_stays_a_member(ana, api, db):
    _invite_member(ana, "mo@example.com")
    _join(api, ana, "mo")
    assert [e for e, _, _ in _listed(ana)] == ["ana@example.com"]  # a new Member is not a reviewer
    assert _add(ana, "mo@example.com").status_code == 201
    assert ("mo@example.com", "member", False) in _listed(ana)
    assert _add(ana, "mo@example.com").status_code == 409
    assert _remove(ana, "mo@example.com").status_code == 204
    rows = _rows(
        db,
        "SELECT role, status, reviewer FROM org_members WHERE org_id = %s AND email = %s",
        ana.org_id,
        "mo@example.com",
    )
    assert rows == [{"role": "member", "status": "active", "reviewer": False}]


def test_a_member_who_loses_the_capability_gives_back_their_claims_in_the_org(ana, ben, api, db):
    _invite_member(ana, "mo@example.com")
    _join(api, ana, "mo")
    assert _add(ana, "mo@example.com").status_code == 201
    add_run(db, ana.org_id, "run_a")
    add_run(db, ben.org_id, "run_b")
    add_task(db, "ht_a", "run_a", payload={**CLAIMED, "claimed_by": "uid_mo", "claimed_via": "team"})
    add_task(db, "ht_b", "run_b", payload={**CLAIMED, "claimed_by": "uid_mo", "claimed_via": "network"})
    assert _remove(ana, "mo@example.com").status_code == 204
    holders = {
        r["id"]: r["holder"] for r in _rows(db, "SELECT id, payload->>'claimed_by' AS holder FROM run_tasks")
    }
    assert holders == {"ht_a": None, "ht_b": "uid_mo"}  # only the org's own tasks are released
    rows = _rows(db, "SELECT status, reviewer FROM org_members WHERE email = 'mo@example.com'")
    assert rows == [{"status": "active", "reviewer": False}]


def test_a_former_reviewer_invited_again_as_a_member_is_not_a_reviewer(ana, ben, api, db):
    _invite_member(ana, "mo@example.com")
    _join(api, ana, "mo")
    assert _add(ana, "mo@example.com").status_code == 201
    _invite_member(ben, "mo@example.com")
    _join(api, ben, "mo")  # Mo leaves Ana's org, which keeps his row as a former member
    _invite_member(ana, "mo@example.com")
    _join(api, ana, "mo")
    assert [e for e, _, _ in _listed(ana)] == ["ana@example.com"]
    rows = _rows(
        db,
        "SELECT role, status, reviewer FROM org_members WHERE org_id = %s AND email = 'mo@example.com'",
        ana.org_id,
    )
    assert rows == [{"role": "member", "status": "active", "reviewer": False}]


def test_removing_a_reviewer_member_ends_their_membership_and_returns_their_claims(ana, api, db):
    _add(ana, "rita@example.com")
    rita = _join(api, ana, "rita")
    assert rita.post("/v1/tokens", json={"name": "Mine", "scopes": ["runs:read"]}).status_code == 201
    add_run(db, ana.org_id, "run_a")
    add_task(db, "ht_a", "run_a", payload={**CLAIMED, "claimed_by": "uid_rita", "claimed_via": "team"})
    assert _remove(ana, "rita@example.com").status_code == 204
    rows = _rows(
        db,
        "SELECT status, reviewer FROM org_members WHERE org_id = %s AND email = 'rita@example.com'",
        ana.org_id,
    )
    assert rows == [{"status": "inactive", "reviewer": False}]
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]
    assert _rows(db, "SELECT revoked_at IS NOT NULL AS revoked FROM api_tokens") == [{"revoked": True}]
    me = rita.get("/v1/me").json()  # her next request lands in a new org of her own
    assert me["orgId"] != ana.org_id and me["role"] == "owner"


def test_removing_a_pending_reviewer_withdraws_the_invitation(ana, db):
    _add(ana, "rita@example.com")
    assert _remove(ana, "rita@example.com").status_code == 204
    assert _rows(db, "SELECT count(*) AS n FROM org_members WHERE email = 'rita@example.com'") == [{"n": 0}]
    assert _remove(ana, "rita@example.com").status_code == 404


def test_only_owners_and_admins_change_reviewers(ana, api):
    _add(ana, "rita@example.com")
    rita = _join(api, ana, "rita")
    assert _reviewers(rita, ana.org_id).status_code == 200  # any member may read the list
    refused = (
        _add(rita, "x@example.com", ana.org_id),
        _remove(rita, "ana@example.com", ana.org_id),
        _network(rita, True, ana.org_id),
    )
    for res in refused:
        assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED"


def test_another_org_can_neither_read_nor_change_an_orgs_reviewers(ana, ben, db):
    _add(ana, "rita@example.com")
    refused = (
        _reviewers(ben, ana.org_id),
        _add(ben, "x@example.com", ana.org_id),
        _remove(ben, "ana@example.com", ana.org_id),
        _network(ben, True, ana.org_id),
    )
    for res in refused:
        assert res.status_code == 403 and res.json()["code"] == "TENANT_SCOPE_DENIED"
    assert _listed(ben) == [("ben@example.com", "owner", False)]
    assert _rows(db, "SELECT allow_network FROM orgs WHERE id = %s", ana.org_id) == [{"allow_network": False}]
    # One email in two orgs is two separate reviewers.
    assert _add(ben, "rita@example.com").status_code == 201
    assert _remove(ben, "rita@example.com").status_code == 204
    assert ("rita@example.com", "reviewer", True) in _listed(ana)


def test_the_switch_is_the_orgs_and_off_returns_only_its_network_claims(ana, ben, db):
    add_run(db, ana.org_id, "run_a")
    add_run(db, ben.org_id, "run_b")
    network = {**CLAIMED, "claimed_by": "uid_nina", "claimed_via": "network", "pay": 150}
    add_task(db, "ht_net", "run_a", payload=network)
    add_task(db, "ht_team", "run_a", payload={**CLAIMED, "claimed_by": "uid_ana", "claimed_via": "team"})
    add_task(db, "ht_b", "run_b", payload=network)
    on = _network(ana, True)
    assert on.status_code == 200, on.text
    assert on.json()["allowNetwork"] is True
    assert _network(ben, True).status_code == 200
    assert _network(ana, False).json()["allowNetwork"] is False
    holders = {
        r["id"]: r["holder"] for r in _rows(db, "SELECT id, payload->>'claimed_by' AS holder FROM run_tasks")
    }
    assert holders == {"ht_net": None, "ht_team": "uid_ana", "ht_b": "uid_nina"}
    assert _rows(db, "SELECT payload ->> 'pay' AS pay FROM run_tasks WHERE id = 'ht_net'") == [{"pay": None}]
    assert _reviewers(ben).json()["allowNetwork"] is True


def test_the_demo_workspace_has_no_reviewer_management(client):
    assert client.get("/v1/organizations/org_hp01/reviewers").status_code == 404
    assert (
        client.post("/v1/organizations/org_hp01/reviewers", json={"email": "x@example.com"}).status_code
        == 404
    )
