"""The live workspace (NM_WORKSPACE=live, NM_RUNTIME=temporal): per-user orgs from Postgres, members and
invitations, API tokens, usage and attention from real runs. Every org-scoped read is checked across orgs."""

import hashlib
import logging
import threading
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app import auth, workspace
from app.errors import ApiProblem
from app.main import create_app
from app.store import reset_store

PROJECT = "nm-demo-test"
USERS = {
    "ana": {"sub": "uid_ana", "email": "Ana@Example.com", "email_verified": True, "name": "Ana Reyes"},
    "ben": {"sub": "uid_ben", "email": "ben@example.com", "email_verified": True, "name": "Ben Ito"},
    "cy": {"sub": "uid_cy", "email": "cy@example.com", "email_verified": False, "name": "Cy"},
    "dee": {"sub": "uid_dee", "email": "dee@example.com", "email_verified": True, "name": "Dee"},
    "str": {"sub": "uid_str", "email": "str@example.com", "email_verified": "true", "name": "Str"},
    "anon": {"sub": "uid_anon"},
}


def _verify(token, request, audience=None, clock_skew_in_seconds=0):
    claims = USERS[token]
    return {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, **claims}


def as_(user: str) -> dict:
    return {"Authorization": f"Bearer {user}"}


@pytest.fixture
def live(db, monkeypatch) -> TestClient:
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", _verify)
    reset_store()
    return TestClient(create_app())


def me(api: TestClient, user: str) -> dict:
    r = api.get("/v1/me", headers=as_(user))
    assert r.status_code == 200, r.text
    return r.json()


def _rows(db, query: str, *args) -> list[dict]:
    db.commit()
    return db.execute(query, args).fetchall()


def _money(minor: int) -> dict:
    return {"amountMinor": minor, "currency": "USD"}


def add_run(
    db,
    org_id: str,
    run_id: str,
    *,
    status: str = "COMPLETED",
    spent: tuple[int, int, int] = (0, 0, 0),
    at: datetime | None = None,
    title: str = "Order and payment reconciliation",
) -> None:
    ai, tools, human = spent
    at = at or datetime.now(UTC)
    projection = {
        "id": run_id,
        "title": title,
        "status": status,
        "summary": f"{title} summary.",
        "spent": {"ai": _money(ai), "tools": _money(tools), "human": _money(human)},
    }
    db.execute(
        "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input, created_at, "
        "updated_at) VALUES (%s, %s, 'order-payment-reconciliation', %s, '{}', %s, '{}', %s, %s)",
        (run_id, org_id, status, Jsonb(projection), at, at),
    )
    db.commit()


def add_task(db, run_id: str, kind: str, status: str, title: str, at: datetime | None = None) -> None:
    db.execute(
        "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload, created_at) "
        "VALUES (%s, %s, 'n', %s, %s, %s, %s)",
        (f"{kind}_{run_id}_{status}", run_id, kind, status, Jsonb({"title": title}), at or datetime.now(UTC)),
    )
    db.commit()


# --- sign-in and provisioning --------------------------------------------------------------------------


def test_first_sign_in_provisions_an_org_with_the_user_as_owner(live, db):
    first = me(live, "ana")
    assert first["orgId"].startswith("org_") and first["orgId"] != "org_hp01"
    assert first == {
        "userId": "uid_ana",
        "email": "ana@example.com",
        "name": "Ana Reyes",
        "orgId": first["orgId"],
        "orgName": "Ana's workspace",
        "role": "owner",
        "workspace": "live",
        "invitations": [],
    }
    assert me(live, "ana") == first
    [org] = _rows(db, "SELECT id, name, plan, monthly_cap_minor, status FROM orgs")
    assert org == {
        "id": first["orgId"],
        "name": "Ana's workspace",
        "plan": "trial",
        "monthly_cap_minor": 2500,
        "status": "active",
    }
    [member] = _rows(db, "SELECT user_id, email, role, status FROM org_members")
    assert member == {"user_id": "uid_ana", "email": "ana@example.com", "role": "owner", "status": "active"}


def test_without_a_name_the_workspace_is_my_workspace(live):
    assert me(live, "anon")["orgName"] == "My workspace"
    assert "email" not in me(live, "anon")


def test_each_user_gets_their_own_org(live):
    assert me(live, "ana")["orgId"] != me(live, "ben")["orgId"]


def test_dev_auth_in_live_mode_maps_the_dev_user_to_its_own_org(live, monkeypatch, db):
    monkeypatch.setenv("AUTH_MODE", "dev")
    who = me(live, "ignored")
    assert who["userId"] == "dev-user" and who["role"] == "owner"
    assert who["orgId"].startswith("org_") and who["orgId"] != "org_hp01"
    assert me(live, "ignored")["orgId"] == who["orgId"]
    assert len(_rows(db, "SELECT id FROM orgs")) == 1


def test_concurrent_first_requests_create_one_org(live, db):
    identity = workspace.Identity(user_id="uid_race", email="race@example.com", email_verified=True, name="R")
    start, found, errors = threading.Barrier(6), [], []

    def sign_in() -> None:
        start.wait()
        try:
            found.append(workspace.membership(identity).org_id)
        except Exception as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=sign_in) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert len(set(found)) == 1 and len(found) == 6
    assert len(_rows(db, "SELECT id FROM orgs")) == 1
    assert len(_rows(db, "SELECT user_id FROM org_members")) == 1


def test_concurrent_first_http_requests_create_one_org(live, db):
    start, codes = threading.Barrier(4), []

    def call() -> None:
        start.wait()
        codes.append(live.get("/v1/me", headers=as_("ben")).status_code)

    threads = [threading.Thread(target=call) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert codes == [200] * 4
    assert len(_rows(db, "SELECT id FROM orgs")) == 1


def test_a_suspended_org_is_locked_out(live, db):
    org = me(live, "ana")["orgId"]
    db.execute("UPDATE orgs SET status = 'suspended' WHERE id = %s", (org,))
    db.commit()
    r = live.get("/v1/me", headers=as_("ana"))
    assert r.status_code == 403 and r.json()["code"] == "TENANT_SUSPENDED"
    assert live.get(f"/v1/organizations/{org}", headers=as_("ana")).status_code == 403


def test_an_unreachable_database_is_a_503_not_a_sign_out(live, monkeypatch):
    def down(identity):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(workspace, "membership", down)
    r = live.get("/v1/me", headers=as_("ana"))
    assert r.status_code == 503 and r.json()["code"] == "WORKSPACE_UNAVAILABLE"


def test_live_without_the_runtime_logs_an_error_and_stays_in_demo(client, monkeypatch, caplog):
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.delenv("NM_RUNTIME", raising=False)
    with caplog.at_level(logging.ERROR):
        api = TestClient(create_app())
    assert any("NM_RUNTIME=temporal" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert api.get("/v1/me").json()["orgId"] == "org_hp01"


def test_on_cloud_run_live_without_the_runtime_fails_the_boot(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "nm-api")
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.delenv("NM_RUNTIME", raising=False)
    with pytest.raises(RuntimeError, match="NM_RUNTIME=temporal"):
        create_app()


def test_on_cloud_run_live_with_dev_sign_in_fails_the_boot(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "nm-api")
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("AUTH_MODE", "dev")
    with pytest.raises(RuntimeError, match="AUTH_MODE=dev"):
        create_app()


@pytest.mark.parametrize("value", ["Live", "prod"])
def test_an_unknown_workspace_mode_fails_the_boot(monkeypatch, value):
    monkeypatch.setenv("NM_WORKSPACE", value)
    with pytest.raises(RuntimeError, match="must be demo or live"):
        create_app()


def test_on_cloud_run_a_configured_live_workspace_or_the_demo_boots(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "nm-api")
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    create_app()
    monkeypatch.setenv("NM_WORKSPACE", "demo")
    monkeypatch.setenv("AUTH_MODE", "dev")
    create_app()


def test_demo_me_is_the_seeded_org(client):
    assert client.get("/v1/me").json() == {
        "userId": "user_demo",
        "orgId": "org_hp01",
        "orgName": "Harbor & Pine Supply Co.",
        "role": "owner",
        "workspace": "demo",
        "invitations": [],
    }


# --- invitations and members ---------------------------------------------------------------------------


def invite(api, user: str, org: str, email: str, role: str = "Member"):
    return api.post(
        f"/v1/organizations/{org}/invitations", json={"email": email, "role": role}, headers=as_(user)
    )


def accept(api, user: str, org: str):
    return api.post(f"/v1/invitations/{org}:accept", headers=as_(user))


def decline(api, user: str, org: str):
    return api.post(f"/v1/invitations/{org}:decline", headers=as_(user))


def _pending(api, user: str, org: str) -> list[str]:
    members = api.get(f"/v1/organizations/{org}/members", headers=as_(user)).json()
    return [m["email"] for m in members if m.get("pending")]


def _member_rows(db, email: str) -> list[tuple[str, str]]:
    rows = _rows(db, "SELECT org_id, status FROM org_members WHERE email = %s ORDER BY org_id", email)
    return [(r["org_id"], r["status"]) for r in rows]


def test_signing_in_with_an_invitation_provisions_an_own_org_and_lists_the_invitation(live, db):
    org = me(live, "ana")["orgId"]
    r = invite(live, "ana", org, "Ben@Example.com")
    assert r.status_code == 201, r.text
    assert r.json() == {
        "name": "ben@example.com",
        "email": "ben@example.com",
        "role": "Member",
        "via": "Invite link",
        "pending": True,
    }
    ben = me(live, "ben")
    assert ben["orgId"] != org and (ben["orgName"], ben["role"]) == ("Ben's workspace", "owner")
    [invitation] = ben["invitations"]
    assert {k: v for k, v in invitation.items() if k != "invitedAt"} == {
        "orgId": org,
        "orgName": "Ana's workspace",
        "role": "member",
    }
    assert invitation["invitedAt"].endswith("Z")
    assert len(_rows(db, "SELECT id FROM orgs")) == 2
    assert _pending(live, "ana", org) == ["ben@example.com"]
    assert me(live, "ana")["invitations"] == []


def test_a_later_sign_in_never_moves_a_user_with_an_empty_org(live, db):
    own = me(live, "ben")["orgId"]
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com")
    ben = me(live, "ben")
    assert ben["orgId"] == own and [i["orgId"] for i in ben["invitations"]] == [org]
    assert len(_rows(db, "SELECT id FROM orgs WHERE id = %s", own)) == 1


def test_accepting_moves_the_user_and_deletes_their_empty_org(live, db):
    own = me(live, "ben")["orgId"]
    live.post("/v1/tokens", json={"name": "T", "scopes": ["runs:read"]}, headers=as_("ben"))
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com")
    r = accept(live, "ben", org)
    assert r.status_code == 200, r.text
    ben = r.json()
    assert (ben["orgId"], ben["orgName"], ben["role"], ben["invitations"]) == (
        org,
        "Ana's workspace",
        "member",
        [],
    )
    assert me(live, "ben") == ben
    assert _rows(db, "SELECT id FROM orgs WHERE id = %s", own) == []
    assert _rows(db, "SELECT id FROM api_tokens") == []
    assert _member_rows(db, "ben@example.com") == [(org, "active")]
    members = live.get(f"/v1/organizations/{org}/members", headers=as_("ben")).json()
    assert [(m["name"], m["email"], m["role"], m.get("pending")) for m in members] == [
        ("Ana Reyes", "ana@example.com", "Owner", None),
        ("Ben Ito", "ben@example.com", "Member", None),
    ]


def test_accepting_keeps_an_org_with_work_and_the_user_becomes_inactive_there(live, db):
    own = me(live, "ben")["orgId"]
    add_run(db, own, "run_b1")
    live.post("/v1/tokens", json={"name": "T", "scopes": ["runs:read"]}, headers=as_("ben"))
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com", "Admin")
    ben = accept(live, "ben", org).json()
    assert (ben["orgId"], ben["role"]) == (org, "admin")
    assert len(_rows(db, "SELECT id FROM orgs WHERE id = %s", own)) == 1
    assert len(_rows(db, "SELECT id FROM runs WHERE org_id = %s", own)) == 1
    assert sorted(_member_rows(db, "ben@example.com")) == sorted([(own, "inactive"), (org, "active")])
    assert [r["revoked_at"] is not None for r in _rows(db, "SELECT revoked_at FROM api_tokens")] == [True]
    assert live.get(f"/v1/organizations/{own}", headers=as_("ben")).status_code == 403
    assert invite(live, "ben", org, "dee@example.com").status_code == 201


def test_accepting_keeps_an_org_with_other_members(live, db):
    own = me(live, "ben")["orgId"]
    invite(live, "ben", own, "dee@example.com")
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com")
    assert accept(live, "ben", org).json()["orgId"] == org
    assert len(_rows(db, "SELECT id FROM orgs WHERE id = %s", own)) == 1
    assert (own, "inactive") in _member_rows(db, "ben@example.com")


def test_a_former_member_can_be_invited_back(live, db):
    ana_org = me(live, "ana")["orgId"]
    dee_org = me(live, "dee")["orgId"]
    invite(live, "ana", ana_org, "ben@example.com")
    accept(live, "ben", ana_org)
    invite(live, "dee", dee_org, "ben@example.com")
    assert accept(live, "ben", dee_org).json()["orgId"] == dee_org
    assert [
        m["email"] for m in live.get(f"/v1/organizations/{ana_org}/members", headers=as_("ana")).json()
    ] == ["ana@example.com"]
    assert invite(live, "ana", ana_org, "ben@example.com").status_code == 201
    assert _pending(live, "ana", ana_org) == ["ben@example.com"]
    assert accept(live, "ben", ana_org).json()["orgId"] == ana_org
    assert sorted(_member_rows(db, "ben@example.com")) == sorted([(ana_org, "active"), (dee_org, "inactive")])


def test_declining_deletes_the_invitation(live, db):
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com")
    own = me(live, "ben")["orgId"]
    r = decline(live, "ben", org)
    assert r.status_code == 200, r.text
    assert (r.json()["orgId"], r.json()["invitations"]) == (own, [])
    assert me(live, "ben")["invitations"] == []
    assert _pending(live, "ana", org) == []
    assert decline(live, "ben", org).status_code == 404
    assert accept(live, "ben", org).status_code == 404
    assert invite(live, "ana", org, "ben@example.com").status_code == 201


def test_an_unverified_email_sees_no_invitations_and_cannot_answer_one(live):
    org = me(live, "ana")["orgId"]
    assert invite(live, "ana", org, "cy@example.com").status_code == 201
    cy = me(live, "cy")
    assert cy["orgId"] != org and cy["role"] == "owner" and cy["invitations"] == []
    for answer in (accept, decline):
        r = answer(live, "cy", org)
        assert r.status_code == 403 and r.json()["code"] == "EMAIL_UNVERIFIED"
    assert me(live, "cy")["orgId"] == cy["orgId"]
    assert _pending(live, "ana", org) == ["cy@example.com"]


def test_a_string_email_verified_claim_is_not_verified(live):
    assert workspace.identity_from_claims(USERS["str"]).email_verified is False
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "str@example.com")
    assert me(live, "str")["invitations"] == []
    assert accept(live, "str", org).status_code == 403
    assert me(live, "str")["orgId"] != org


def test_another_users_invitation_is_a_404(live, db):
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com")
    dee = me(live, "dee")
    for answer in (accept, decline):
        r = answer(live, "dee", org)
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    assert me(live, "dee")["orgId"] == dee["orgId"]
    assert _pending(live, "ana", org) == ["ben@example.com"]
    assert accept(live, "ben", "org_nope").status_code == 404


def test_an_invitation_from_a_suspended_org_is_hidden_and_cannot_be_accepted(live, db):
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com")
    db.execute("UPDATE orgs SET status = 'suspended' WHERE id = %s", (org,))
    db.commit()
    assert me(live, "ben")["invitations"] == []
    assert accept(live, "ben", org).status_code == 404


def test_invitations_are_listed_oldest_first(live, db):
    dee_org = me(live, "dee")["orgId"]
    ana_org = me(live, "ana")["orgId"]
    invite(live, "ana", ana_org, "ben@example.com")
    invite(live, "dee", dee_org, "ben@example.com")
    db.execute(
        "UPDATE org_members SET created_at = now() - interval '1 hour' WHERE org_id = %s AND email = %s",
        (dee_org, "ben@example.com"),
    )
    db.commit()
    assert [i["orgId"] for i in me(live, "ben")["invitations"]] == [dee_org, ana_org]


def _race(accepts: list[tuple[workspace.Identity, str]]) -> tuple[list[str], list[Exception]]:
    start, joined, errors = threading.Barrier(len(accepts)), [], []

    def run(identity: workspace.Identity, org: str) -> None:
        start.wait()
        try:
            joined.append(workspace.accept_invitation(identity, org).org_id)
        except Exception as exc:  # collected and asserted by the caller
            errors.append(exc)

    threads = [threading.Thread(target=run, args=a) for a in accepts]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return joined, errors


BEN = workspace.Identity(user_id="uid_ben", email="ben@example.com", email_verified=True, name="Ben Ito")


def test_concurrent_accepts_of_one_invitation_join_once(live, db):
    me(live, "ben")
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com")
    joined, errors = _race([(BEN, org)] * 4)
    assert joined == [org]
    assert len(errors) == 3 and all(isinstance(e, ApiProblem) and e.status == 404 for e in errors)
    assert _rows(db, "SELECT org_id FROM org_members WHERE user_id = 'uid_ben' AND status = 'active'") == [
        {"org_id": org}
    ]
    assert len(_rows(db, "SELECT id FROM orgs")) == 1


def test_concurrent_accepts_of_two_invitations_leave_one_active_membership(live, db):
    me(live, "ben")
    ana_org = me(live, "ana")["orgId"]
    dee_org = me(live, "dee")["orgId"]
    invite(live, "ana", ana_org, "ben@example.com")
    invite(live, "dee", dee_org, "ben@example.com")
    joined, errors = _race([(BEN, ana_org), (BEN, dee_org)] * 2)
    assert len(joined) == 2 and sorted(joined) == sorted([ana_org, dee_org])
    assert len(errors) == 2 and all(isinstance(e, ApiProblem) and e.status == 404 for e in errors)
    active = _rows(db, "SELECT org_id FROM org_members WHERE user_id = 'uid_ben' AND status = 'active'")
    assert len(active) == 1 and active[0]["org_id"] in (ana_org, dee_org)
    assert len(_rows(db, "SELECT id FROM orgs")) == 2


def test_demo_invitation_answers_are_404(client):
    for verb in ("accept", "decline"):
        r = client.post(f"/v1/invitations/org_hp01:{verb}")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_inviting_an_email_twice_or_a_member_is_a_conflict(live):
    org = me(live, "ana")["orgId"]
    assert invite(live, "ana", org, "dee@example.com", "Admin").status_code == 201
    again = invite(live, "ana", org, "DEE@example.com")
    assert again.status_code == 409 and again.json()["code"] == "CONFLICT"
    assert invite(live, "ana", org, "ana@example.com").status_code == 409


def test_a_member_cannot_invite(live):
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com")
    assert accept(live, "ben", org).status_code == 200
    r = invite(live, "ben", org, "dee@example.com")
    assert r.status_code == 403 and r.json()["code"] == "POLICY_DENIED"


def test_an_invited_admin_joins_as_admin_and_can_invite(live):
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com", "Admin")
    assert accept(live, "ben", org).json()["role"] == "admin"
    assert me(live, "ben")["role"] == "admin"
    assert invite(live, "ben", org, "dee@example.com").status_code == 201


# --- org, policies -------------------------------------------------------------------------------------


def test_org_reports_plan_cap_and_this_months_spend(live, db):
    org = me(live, "ana")["orgId"]
    other = me(live, "ben")["orgId"]
    now = datetime.now(UTC)
    last_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    add_run(db, org, "run_a1", spent=(120, 30, 400))
    add_run(db, org, "run_a2", status="RUNNING", spent=(5, 0, 0))
    add_run(db, org, "run_a0", spent=(999, 0, 0), at=last_month)
    add_run(db, other, "run_b1", spent=(700, 0, 0))
    body = live.get(f"/v1/organizations/{org}", headers=as_("ana")).json()
    assert body == {
        "id": org,
        "name": "Ana's workspace",
        "short": "Ana's workspace",
        "plan": "Trial",
        "monthlyCap": _money(2500),
        "monthSpent": _money(555),
        "region": "us-central1",
    }


def test_policies_are_the_built_in_defaults(live):
    org = me(live, "ana")["orgId"]
    policies = live.get(f"/v1/organizations/{org}/policies", headers=as_("ana")).json()
    refs = [p["ref"] for p in policies]
    assert refs == [p.ref for p in workspace.DEFAULT_POLICIES]
    assert "refunds@2" not in refs and all(p["summary"] and p["updated"] for p in policies)


# --- tokens --------------------------------------------------------------------------------------------


def test_a_token_secret_is_shown_once_and_only_its_hash_is_stored(live, db):
    me(live, "ana")
    r = live.post("/v1/tokens", json={"name": "CLI", "scopes": ["runs:read"]}, headers=as_("ana"))
    assert r.status_code == 201, r.text
    created = r.json()
    secret, token = created["secret"], created["token"]
    assert secret.startswith("nm_pat_") and len(secret) > 30
    assert token["name"] == "CLI" and token["scopes"] == ["runs:read"]
    assert token["prefix"] == secret[: len(token["prefix"])] and len(token["prefix"]) < len(secret) - 20
    assert token["lastUsed"] == "" and token["last4"] == secret[-4:]
    created_at = datetime.fromisoformat(token["createdAt"])
    assert datetime.fromisoformat(token["expiresAt"]) - created_at == timedelta(days=30)
    [row] = _rows(db, "SELECT id, user_id, prefix, last4, secret_hash, scopes, revoked_at FROM api_tokens")
    assert row["secret_hash"] == hashlib.sha256(secret.encode()).hexdigest() and row["last4"] == secret[-4:]
    assert (row["id"], row["user_id"], row["scopes"], row["revoked_at"]) == (
        token["id"],
        "uid_ana",
        ["runs:read"],
        None,
    )
    listed = live.get("/v1/tokens", headers=as_("ana"))
    assert [t["id"] for t in listed.json()] == [token["id"]]
    assert secret not in listed.text and "secret" not in listed.json()[0]


def test_revoking_a_token_removes_it(live, db):
    me(live, "ana")
    token = live.post("/v1/tokens", json={"name": "CLI", "scopes": ["runs:read"]}, headers=as_("ana")).json()
    tid = token["token"]["id"]
    assert live.delete(f"/v1/tokens/{tid}", headers=as_("ana")).status_code == 204
    assert live.get("/v1/tokens", headers=as_("ana")).json() == []
    [row] = _rows(db, "SELECT revoked_at FROM api_tokens")
    assert row["revoked_at"] is not None
    assert live.delete(f"/v1/tokens/{tid}", headers=as_("ana")).status_code == 404


def test_expired_tokens_are_not_listed(live, db):
    me(live, "ana")
    live.post("/v1/tokens", json={"name": "Old", "scopes": ["runs:read"]}, headers=as_("ana"))
    db.execute("UPDATE api_tokens SET expires_at = now() - interval '1 second'")
    db.commit()
    assert live.get("/v1/tokens", headers=as_("ana")).json() == []


def test_a_member_cannot_see_or_revoke_another_members_token(live, db):
    org = me(live, "ana")["orgId"]
    invite(live, "ana", org, "ben@example.com", "Admin")
    assert accept(live, "ben", org).json()["orgId"] == org
    token = live.post("/v1/tokens", json={"name": "A", "scopes": ["runs:read"]}, headers=as_("ana")).json()
    tid = token["token"]["id"]
    assert live.get("/v1/tokens", headers=as_("ben")).json() == []
    assert live.delete(f"/v1/tokens/{tid}", headers=as_("ben")).status_code == 404
    assert [t["id"] for t in live.get("/v1/tokens", headers=as_("ana")).json()] == [tid]


def test_tokens_are_private_to_their_owner_and_org(live, db):
    me(live, "ana")
    me(live, "ben")
    token = live.post("/v1/tokens", json={"name": "A", "scopes": ["runs:read"]}, headers=as_("ana")).json()
    tid = token["token"]["id"]
    assert live.get("/v1/tokens", headers=as_("ben")).json() == []
    assert live.delete(f"/v1/tokens/{tid}", headers=as_("ben")).status_code == 404
    assert [row["revoked_at"] for row in _rows(db, "SELECT revoked_at FROM api_tokens")] == [None]


# --- usage and attention -------------------------------------------------------------------------------


def test_usage_has_one_ledger_line_per_run_newest_first(live, db):
    org = me(live, "ana")["orgId"]
    other = me(live, "ben")["orgId"]
    now = datetime.now(UTC)
    add_run(db, org, "run_a1", spent=(120, 30, 400), at=now - timedelta(hours=2))
    add_run(db, org, "run_a2", status="RUNNING", spent=(5, 0, 0), at=now - timedelta(hours=1))
    add_run(db, other, "run_b1", spent=(700, 0, 0))
    usage = live.get(f"/v1/organizations/{org}/usage", headers=as_("ana")).json()
    assert usage["org"]["monthSpent"] == _money(555) and usage["org"]["monthlyCap"] == _money(2500)
    assert [t["runId"] for t in usage["ledger"]] == ["run_a2", "run_a1"]
    line = usage["ledger"][1]
    assert line["kind"] == "run" and line["status"] == "POSTED"
    assert line["description"] == "Order and payment reconciliation"
    assert line["amount"] == _money(550)
    assert line["spent"] == {"ai": _money(120), "tools": _money(30), "human": _money(400)}
    assert [(x["account"], x.get("debit")) for x in line["lines"]] == [
        ("AI usage", 120),
        ("Tool usage", 30),
        ("Human review", 400),
    ]
    assert usage["ledger"][0]["status"] == "PENDING"


def test_an_empty_workspace_has_no_usage_or_attention(live):
    org = me(live, "ana")["orgId"]
    usage = live.get(f"/v1/organizations/{org}/usage", headers=as_("ana")).json()
    assert usage["ledger"] == [] and usage["org"]["monthSpent"] == _money(0)
    assert live.get(f"/v1/organizations/{org}/attention", headers=as_("ana")).json() == []
    assert live.get(f"/v1/organizations/{org}/members", headers=as_("ana")).json() == [
        {"name": "Ana Reyes", "email": "ana@example.com", "role": "Owner", "via": "Signed in"}
    ]


def test_attention_comes_from_real_approvals_tasks_failures_and_spend(live, db):
    org = me(live, "ana")["orgId"]
    other = me(live, "ben")["orgId"]
    now = datetime.now(UTC)
    add_run(db, org, "run_a1", status="WAITING_FOR_EVENT", spent=(1500, 0, 500), at=now - timedelta(hours=3))
    add_task(db, "run_a1", "approval", "pending", "Write the report to the Sheet", now - timedelta(hours=2))
    add_task(db, "run_a1", "approval", "granted", "Already decided", now - timedelta(hours=2))
    add_task(db, "run_a1", "human", "open", "Resolve mismatches", now - timedelta(hours=1))
    add_run(db, org, "run_a2", status="FAILED", at=now - timedelta(days=1))
    add_run(db, org, "run_a3", status="FAILED", at=now - timedelta(days=8))
    add_run(db, other, "run_b1", status="FAILED")
    add_task(db, "run_b1", "approval", "pending", "Not yours")
    items = live.get(f"/v1/organizations/{org}/attention", headers=as_("ana")).json()
    by_href = {i["href"]: i for i in items}
    assert set(by_href) == {"/app/approvals", "/work", "/app/runs/run_a2", "/app/usage"}
    assert by_href["/app/approvals"]["detail"] == "Write the report to the Sheet"
    assert by_href["/app/approvals"]["actor"] == "buyer"
    assert by_href["/work"]["detail"] == "Resolve mismatches" and by_href["/work"]["actor"] == "human"
    assert by_href["/app/runs/run_a2"]["actor"] == "system"
    assert "80%" in by_href["/app/usage"]["title"]
    whens = [i["when"] for i in items]
    assert whens == sorted(whens, reverse=True)
    assert all("Not yours" not in i["detail"] for i in items)


def test_spend_under_80_percent_is_not_attention(live, db):
    org = me(live, "ana")["orgId"]
    add_run(db, org, "run_a1", spent=(1999, 0, 0))
    assert live.get(f"/v1/organizations/{org}/attention", headers=as_("ana")).json() == []


# --- isolation -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["", "/policies", "/members", "/usage", "/attention"])
def test_another_orgs_endpoints_are_refused(live, path):
    org = me(live, "ana")["orgId"]
    me(live, "ben")
    r = live.get(f"/v1/organizations/{org}{path}", headers=as_("ben"))
    assert r.status_code == 403 and r.json()["code"] == "TENANT_SCOPE_DENIED"


def test_another_org_cannot_invite_or_see_members(live, db):
    org = me(live, "ana")["orgId"]
    ben_org = me(live, "ben")["orgId"]
    r = invite(live, "ben", org, "eve@example.com")
    assert r.status_code == 403 and r.json()["code"] == "TENANT_SCOPE_DENIED"
    assert [
        m["email"] for m in live.get(f"/v1/organizations/{ben_org}/members", headers=as_("ben")).json()
    ] == ["ben@example.com"]
    assert _rows(db, "SELECT email FROM org_members WHERE email = 'eve@example.com'") == []
