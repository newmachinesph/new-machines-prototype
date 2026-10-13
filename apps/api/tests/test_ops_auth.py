"""Operator sign-in: dev mode is an owner; otherwise a verified Firebase email must be on an allow list."""

import pytest

from app import auth
from app.store import get_store

PROJECT = "nm-demo-test"
CLAIMS = {
    "iss": f"https://securetoken.google.com/{PROJECT}",
    "aud": PROJECT,
    "sub": "uid_ops",
    "email": "Ana.Admin@NewMachin.es",
    "email_verified": True,
    "firebase": {"sign_in_provider": "google.com"},
}
TOKEN = {"Authorization": "Bearer good-token"}
REASON = {"reason": "Testing the operator console"}

# Every ops mutation in this task, with a valid body, so only the role decides the outcome.
MUTATIONS = [
    (
        "/v1/ops/tenants",
        {
            "name": "Kobe Ceramics",
            "short": "Kobe Ceramics",
            "plan": "Starter",
            "region": "asia-northeast1",
            "country": "JP",
            "ownerEmail": "owner@kobe.example",
            "monthlyCapMinor": 10000,
            **REASON,
        },
    ),
    ("/v1/ops/tenants/org_k7m2:suspend", REASON),
    ("/v1/ops/tenants/org_a3wc:reactivate", REASON),
    ("/v1/ops/tenants/org_k7m2:setPlan", {"plan": "Pro", **REASON}),
    ("/v1/ops/tenants/org_k7m2:setSpendCap", {"monthlyCapMinor": 5000, **REASON}),
]


@pytest.fixture
def firebase_mode(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setenv("OPS_ADMIN_EMAILS", " ana.admin@newmachin.es , lead@newmachin.es")
    monkeypatch.setenv("OPS_SUPPORT_EMAILS", "sam.support@newmachin.es")


def stub_claims(monkeypatch, claims):
    """Replace Google's verifier so no test fetches signing keys over the network."""
    calls = []

    def verify(token, request, audience=None, clock_skew_in_seconds=0):
        calls.append(token)
        if isinstance(claims, Exception):
            raise claims
        return claims

    monkeypatch.setattr(auth.id_token, "verify_firebase_token", verify)
    return calls


def assert_ops_forbidden(r):
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "OPS_FORBIDDEN"


def test_dev_mode_is_an_owner_operator(client):
    r = client.get("/v1/ops/me")
    assert r.status_code == 200
    assert r.json() == {
        "userId": "ops_demo",
        "email": "ops@newmachin.es",
        "role": "owner",
        "workspace": "demo",
    }


@pytest.mark.usefixtures("firebase_mode")
def test_a_listed_admin_matches_case_insensitively(client, monkeypatch):
    stub_claims(monkeypatch, CLAIMS)
    r = client.get("/v1/ops/me", headers=TOKEN)
    assert r.status_code == 200
    assert r.json() == {
        "userId": "uid_ops",
        "email": "ana.admin@newmachin.es",
        "role": "admin",
        "workspace": "demo",
    }


@pytest.mark.usefixtures("firebase_mode")
def test_a_listed_support_email_is_support(client, monkeypatch):
    stub_claims(monkeypatch, {**CLAIMS, "email": "sam.support@newmachin.es"})
    r = client.get("/v1/ops/me", headers=TOKEN)
    assert r.status_code == 200 and r.json()["role"] == "support"


@pytest.mark.usefixtures("firebase_mode")
def test_an_email_on_both_lists_is_an_admin(client, monkeypatch):
    monkeypatch.setenv("OPS_SUPPORT_EMAILS", "ana.admin@newmachin.es")
    stub_claims(monkeypatch, CLAIMS)
    assert client.get("/v1/ops/me", headers=TOKEN).json()["role"] == "admin"


@pytest.mark.usefixtures("firebase_mode")
def test_an_unlisted_email_is_forbidden(client, monkeypatch):
    stub_claims(monkeypatch, {**CLAIMS, "email": "someone@customer.example"})
    assert_ops_forbidden(client.get("/v1/ops/me", headers=TOKEN))
    assert_ops_forbidden(client.get("/v1/ops/tenants", headers=TOKEN))


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize(
    "claims",
    [
        {**CLAIMS, "email_verified": False},
        {key: value for key, value in CLAIMS.items() if key != "email_verified"},
        {**CLAIMS, "email_verified": "true"},
        {key: value for key, value in CLAIMS.items() if key != "email"},
        {**CLAIMS, "email": ""},
    ],
    ids=["unverified", "no-verified-claim", "verified-as-string", "no-email", "empty-email"],
)
def test_an_unverified_or_missing_email_is_forbidden(client, monkeypatch, claims):
    stub_claims(monkeypatch, claims)
    assert_ops_forbidden(client.get("/v1/ops/me", headers=TOKEN))


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize("admins", ["", " , ", None])
def test_empty_lists_admit_nobody(client, monkeypatch, admins):
    if admins is None:
        monkeypatch.delenv("OPS_ADMIN_EMAILS")
    else:
        monkeypatch.setenv("OPS_ADMIN_EMAILS", admins)
    monkeypatch.delenv("OPS_SUPPORT_EMAILS")
    stub_claims(monkeypatch, CLAIMS)
    assert_ops_forbidden(client.get("/v1/ops/me", headers=TOKEN))


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}])
def test_a_missing_token_is_401_without_verifying(client, monkeypatch, headers):
    calls = stub_claims(monkeypatch, CLAIMS)
    r = client.get("/v1/ops/me", headers=headers)
    assert r.status_code == 401 and r.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert calls == []


@pytest.mark.usefixtures("firebase_mode")
def test_a_rejected_token_is_401(client, monkeypatch):
    stub_claims(monkeypatch, ValueError("Token expired"))
    r = client.get("/v1/ops/me", headers=TOKEN)
    assert r.status_code == 401 and r.json()["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.usefixtures("firebase_mode")
def test_a_token_from_another_project_is_401_even_for_a_listed_email(client, monkeypatch):
    stub_claims(monkeypatch, {**CLAIMS, "iss": "https://securetoken.google.com/another-project"})
    assert client.get("/v1/ops/me", headers=TOKEN).status_code == 401


@pytest.mark.usefixtures("firebase_mode")
def test_support_can_read(client, monkeypatch):
    stub_claims(monkeypatch, {**CLAIMS, "email": "sam.support@newmachin.es"})
    for path in ("/v1/ops/tenants", "/v1/ops/tenants/org_hp01", "/v1/ops/audit", "/v1/ops/team"):
        assert client.get(path, headers=TOKEN).status_code == 200, path


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize(("path", "body"), MUTATIONS, ids=[p for p, _ in MUTATIONS])
def test_support_gets_403_on_every_mutation_and_nothing_changes(client, monkeypatch, path, body):
    stub_claims(monkeypatch, {**CLAIMS, "email": "sam.support@newmachin.es"})
    store = get_store()
    before_tenants = {k: v.model_copy() for k, v in store.tenants.items()}
    before_audit = len(store.audit_log)
    assert_ops_forbidden(client.post(path, json=body, headers=TOKEN))
    assert store.tenants == before_tenants
    assert len(store.audit_log) == before_audit


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize(("path", "body"), MUTATIONS, ids=[p for p, _ in MUTATIONS])
def test_an_admin_can_mutate_and_is_named_in_the_audit(client, monkeypatch, path, body):
    stub_claims(monkeypatch, CLAIMS)
    r = client.post(path, json=body, headers=TOKEN)
    assert r.status_code in (200, 201), r.text
    entry = get_store().audit_log[-1]
    assert (entry.actor_email, entry.actor_role) == ("ana.admin@newmachin.es", "admin")


@pytest.mark.usefixtures("firebase_mode")
def test_password_sign_in_is_accepted(client, monkeypatch):
    stub_claims(monkeypatch, {**CLAIMS, "firebase": {"sign_in_provider": "password"}})
    assert client.get("/v1/ops/me", headers=TOKEN).json()["role"] == "admin"


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize(
    "firebase",
    [
        {"sign_in_provider": "anonymous"},
        {"sign_in_provider": "custom"},
        {"sign_in_provider": "phone"},
        {},
        "x",
        None,
    ],
    ids=["anonymous", "custom", "phone", "no-provider", "not-a-dict", "missing"],
)
def test_other_sign_in_providers_are_forbidden(client, monkeypatch, firebase):
    claims = {**CLAIMS, "firebase": firebase}
    if firebase is None:
        del claims["firebase"]
    stub_claims(monkeypatch, claims)
    assert_ops_forbidden(client.get("/v1/ops/me", headers=TOKEN))


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v1/ops/tenants/org_k7m2:suspend", {"reason": ""}),
        ("/v1/ops/tenants/org_k7m2:setSpendCap", {"monthlyCapMinor": -5, "reason": " "}),
        ("/v1/ops/tenants", {"reason": ""}),
        ("/v1/ops/tenants/org_none:suspend", {"reason": "Testing"}),
        ("/v1/ops/tenants/org_none:setPlan", {"plan": "Pro", "reason": "Testing"}),
    ],
    ids=["empty-reason", "bad-cap", "bad-create", "unknown-tenant", "unknown-tenant-plan"],
)
def test_support_gets_403_before_validation_or_lookup(client, monkeypatch, path, body):
    stub_claims(monkeypatch, {**CLAIMS, "email": "sam.support@newmachin.es"})
    before = len(get_store().audit_log)
    assert_ops_forbidden(client.post(path, json=body, headers=TOKEN))
    assert len(get_store().audit_log) == before


@pytest.mark.usefixtures("firebase_mode")
def test_a_customer_token_still_works_on_customer_routes(client, monkeypatch):
    stub_claims(monkeypatch, {**CLAIMS, "email": "someone@customer.example"})
    assert client.get("/v1/approvals", headers=TOKEN).status_code == 200


def test_the_team_lists_four_operators(client):
    r = client.get("/v1/ops/team")
    assert r.status_code == 200
    team = r.json()
    assert len(team) == 4
    assert {m["role"] for m in team} <= {"owner", "admin", "support"}
    assert set(team[0]) >= {"email", "name", "role", "lastActiveAt", "mfa"}
