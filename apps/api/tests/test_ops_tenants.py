"""Tenants, the suspension lock and the audit log. The suite runs in dev mode, so the operator is an owner."""

import re

import pytest

from app.routers import ops_tenants
from app.store import get_store

REASON = "Customer asked by email"
NEW_TENANT = {
    "name": "Kobe Ceramics Co.",
    "short": "Kobe Ceramics",
    "plan": "Starter",
    "region": "asia-northeast1",
    "country": "JP",
    "ownerEmail": "owner@kobe.example",
    "monthlyCapMinor": 10000,
    "reason": REASON,
}


def newest_audit(client, **params):
    r = client.get("/v1/ops/audit", params=params)
    assert r.status_code == 200
    return r.json()[0]


# Reads -------------------------------------------------------------------------------------------------


def test_eight_seeded_tenants_cover_every_status(client):
    tenants = client.get("/v1/ops/tenants").json()
    assert len(tenants) == 8
    assert {t["status"] for t in tenants} == {"active", "trial", "suspended", "churned"}
    assert "at_risk" in {t["health"] for t in tenants}
    assert {t["country"] for t in tenants} >= {"JP", "PH", "SG", "US", "AU"}
    assert all(re.fullmatch(r"org_[a-z0-9]{4}", t["id"]) for t in tenants)


def test_the_demo_tenant_matches_the_customer_organization(client):
    hp = client.get("/v1/ops/tenants/org_hp01").json()
    assert hp["name"] == "Harbor & Pine Supply Co."
    assert hp["monthlyCap"] == {"amountMinor": 25000, "currency": "USD"}
    assert hp["monthSpent"] == {"amountMinor": 6194, "currency": "USD"}
    assert hp["plan"] == "Pro" and hp["status"] == "active"


def test_tenants_filter_by_status_and_search(client):
    suspended = client.get("/v1/ops/tenants", params={"status": "suspended"}).json()
    assert suspended and all(t["status"] == "suspended" for t in suspended)
    assert all("suspendedReason" in t for t in suspended)
    found = client.get("/v1/ops/tenants", params={"q": "harbor"}).json()
    assert [t["id"] for t in found] == ["org_hp01"]
    assert client.get("/v1/ops/tenants", params={"q": "ORG_HP01"}).json()[0]["id"] == "org_hp01"
    assert client.get("/v1/ops/tenants", params={"q": "nothing-matches"}).json() == []


def test_an_unknown_status_filter_is_422(client):
    r = client.get("/v1/ops/tenants", params={"status": "paused"})
    assert r.status_code == 422 and r.json()["code"] == "SCHEMA_INVALID"


def test_the_demo_tenant_detail_comes_from_the_live_store(client):
    d = client.get("/v1/ops/tenants/org_hp01").json()
    store = get_store()
    assert len(d["membersList"]) == len(store.members) == d["members"]
    assert d["installedPacks"] == [p.slug for p in store.packs if p.installed]
    assert d["packsInstalled"] == len(d["installedPacks"])
    assert d["connectorsList"] == [{"app": c.app, "status": c.status} for c in store.connections]
    runs = d["recentRuns"]
    assert runs and runs[0]["id"] == store.run_summaries[0].id
    assert all(r["tenantId"] == "org_hp01" and r["tenantName"] == d["name"] for r in runs)
    completed = next(r for r in runs if r["id"] == "run_1042")
    assert completed["cost"] == {"amountMinor": 940, "currency": "USD"}
    assert completed["durationSeconds"] == 38 * 60 - 7
    assert completed["pack"] == "order-payment-reconciliation"
    assert d["simulated"] is True
    assert len(d["usageByDay"]) == 14
    assert all(p["amountMinor"] >= 0 for p in d["usageByDay"])
    assert d["usageByDay"] == client.get("/v1/ops/tenants/org_hp01").json()["usageByDay"]


def test_a_live_change_shows_in_the_demo_tenant(client):
    client.post(
        "/v1/organizations/org_hp01/invitations",
        json={"email": "new@harborandpine.example", "role": "Member"},
    )
    d = client.get("/v1/ops/tenants/org_hp01").json()
    assert d["members"] == 3 and len(d["membersList"]) == 3
    listed = next(t for t in client.get("/v1/ops/tenants").json() if t["id"] == "org_hp01")
    assert listed["members"] == 3


def test_another_tenant_has_seeded_detail(client):
    d = client.get("/v1/ops/tenants/org_k7m2").json()
    assert d["membersList"] and d["installedPacks"] and d["connectorsList"]
    assert len(d["usageByDay"]) == 14 and d["simulated"] is True
    days = [p["day"] for p in d["usageByDay"]]
    assert days == sorted(days) and len(set(days)) == 14


def test_an_unknown_tenant_is_404(client):
    r = client.get("/v1/ops/tenants/org_none")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


# Create ------------------------------------------------------------------------------------------------


def test_create_a_tenant(client):
    r = client.post("/v1/ops/tenants", json=NEW_TENANT)
    assert r.status_code == 201, r.text
    t = r.json()
    assert re.fullmatch(r"org_[a-z0-9]{4}", t["id"])
    assert t["status"] == "active" and "trialEndsAt" not in t
    assert t["monthlyCap"] == {"amountMinor": 10000, "currency": "USD"}
    assert t["monthSpent"]["amountMinor"] == 0
    assert client.get(f"/v1/ops/tenants/{t['id']}").status_code == 200
    entry = newest_audit(client)
    assert (entry["action"], entry["targetType"], entry["targetId"]) == ("tenant.create", "tenant", t["id"])
    assert entry["reason"] == REASON


def test_create_a_trial_tenant(client):
    t = client.post("/v1/ops/tenants", json={**NEW_TENANT, "trialDays": 14}).json()
    assert t["status"] == "trial" and t["trialEndsAt"] > t["createdAt"]


def test_a_new_tenant_id_retries_on_collision(client, monkeypatch):
    letters = iter("hp01zz99")
    monkeypatch.setattr(ops_tenants.secrets, "choice", lambda _: next(letters))
    assert client.post("/v1/ops/tenants", json=NEW_TENANT).json()["id"] == "org_zz99"


# Suspension --------------------------------------------------------------------------------------------


def test_suspending_the_demo_tenant_locks_customer_routes_but_not_ops(client):
    r = client.post("/v1/ops/tenants/org_hp01:suspend", json={"reason": "Chargeback investigation"})
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"
    assert r.json()["suspendedReason"] == "Chargeback investigation"

    for path in ("/v1/workflow-runs", "/v1/approvals", "/v1/organizations/org_hp01"):
        blocked = client.get(path)
        assert blocked.status_code == 403, path
        assert blocked.headers["content-type"].startswith("application/problem+json")
        assert blocked.json()["code"] == "TENANT_SUSPENDED"
    blocked = client.post("/v1/connections/Gmail:disconnect")
    assert blocked.status_code == 403 and blocked.json()["code"] == "TENANT_SUSPENDED"

    assert client.get("/v1/ops/tenants").status_code == 200
    assert client.get("/v1/ops/tenants/org_hp01").status_code == 200
    assert client.get("/healthz").status_code == 200

    r = client.post("/v1/ops/tenants/org_hp01:reactivate", json={"reason": "Resolved"})
    assert r.status_code == 200
    assert r.json()["status"] == "active" and "suspendedReason" not in r.json()
    assert client.get("/v1/workflow-runs").status_code == 200


def test_suspending_another_tenant_does_not_lock_the_demo_tenant(client):
    assert client.post("/v1/ops/tenants/org_k7m2:suspend", json={"reason": REASON}).status_code == 200
    assert client.get("/v1/workflow-runs").status_code == 200


def test_suspending_twice_is_409(client):
    r = client.post("/v1/ops/tenants/org_a3wc:suspend", json={"reason": REASON})
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_SUSPENDED"


def test_reactivating_a_tenant_that_is_not_suspended_is_409(client):
    r = client.post("/v1/ops/tenants/org_hp01:reactivate", json={"reason": REASON})
    assert r.status_code == 409 and r.json()["code"] == "NOT_SUSPENDED"


def test_a_reactivated_trial_tenant_returns_to_trial(client):
    trial = next(t for t in client.get("/v1/ops/tenants").json() if t["status"] == "trial")
    client.post(f"/v1/ops/tenants/{trial['id']}:suspend", json={"reason": REASON})
    r = client.post(f"/v1/ops/tenants/{trial['id']}:reactivate", json={"reason": REASON})
    assert r.json()["status"] == "trial"


def test_reactivation_restores_the_status_before_suspension(client):
    active = client.post("/v1/ops/tenants", json=NEW_TENANT).json()
    trial = client.post("/v1/ops/tenants", json={**NEW_TENANT, "trialDays": 7}).json()
    for tenant, expected in ((active, "active"), (trial, "trial")):
        client.post(f"/v1/ops/tenants/{tenant['id']}:suspend", json={"reason": REASON})
        r = client.post(f"/v1/ops/tenants/{tenant['id']}:reactivate", json={"reason": REASON})
        assert r.json()["status"] == expected
        assert not any("before" in key.lower() for key in r.json())  # internal, never on the wire


def test_a_converted_trial_reactivates_as_active_not_trial(client):
    # An active tenant that still carries its old trial end date, as one that converted to a paid plan would.
    get_store().tenants["org_p4ld"].status = "active"
    client.post("/v1/ops/tenants/org_p4ld:suspend", json={"reason": REASON})
    r = client.post("/v1/ops/tenants/org_p4ld:reactivate", json={"reason": REASON})
    assert r.json()["status"] == "active"


def test_a_tenant_seeded_as_suspended_reactivates_as_active(client):
    r = client.post("/v1/ops/tenants/org_a3wc:reactivate", json={"reason": REASON})
    assert r.status_code == 200 and r.json()["status"] == "active"


def test_a_churned_tenant_cannot_be_suspended(client):
    before = len(get_store().audit_log)
    r = client.post("/v1/ops/tenants/org_u6rn:suspend", json={"reason": REASON})
    assert r.status_code == 409 and r.json()["code"] == "INVALID_TRANSITION"
    assert client.get("/v1/ops/tenants/org_u6rn").json()["status"] == "churned"
    assert len(get_store().audit_log) == before


# Plan and cap ------------------------------------------------------------------------------------------


def test_set_plan(client):
    r = client.post("/v1/ops/tenants/org_k7m2:setPlan", json={"plan": "Starter", "reason": REASON})
    assert r.status_code == 200 and r.json()["plan"] == "Starter"


def test_set_plan_and_cap_on_the_demo_tenant_reach_the_customer_organization(client):
    client.post("/v1/ops/tenants/org_hp01:setPlan", json={"plan": "Enterprise", "reason": REASON})
    r = client.post("/v1/ops/tenants/org_hp01:setSpendCap", json={"monthlyCapMinor": 40000, "reason": REASON})
    assert r.status_code == 200 and r.json()["monthlyCap"]["amountMinor"] == 40000
    org = client.get("/v1/organizations/org_hp01").json()
    assert org["plan"] == "Enterprise" and org["monthlyCap"]["amountMinor"] == 40000


@pytest.mark.parametrize(
    ("verb", "body"),
    [
        ("setPlan", {"plan": "Enterprise", "reason": REASON}),
        ("setSpendCap", {"monthlyCapMinor": 120000, "reason": REASON}),
    ],
)
def test_setting_the_current_value_is_409_and_not_audited(client, verb, body):
    before = len(get_store().audit_log)
    r = client.post(f"/v1/ops/tenants/org_k7m2:{verb}", json=body)
    assert r.status_code == 409 and r.json()["code"] == "NO_CHANGE"
    assert len(get_store().audit_log) == before


def test_setting_the_demo_tenants_current_cap_is_409(client):
    r = client.post("/v1/ops/tenants/org_hp01:setSpendCap", json={"monthlyCapMinor": 25000, "reason": REASON})
    assert r.status_code == 409 and r.json()["code"] == "NO_CHANGE"


@pytest.mark.parametrize("cap", [0, 10_000_000])
def test_spend_cap_bounds_are_inclusive(client, cap):
    r = client.post("/v1/ops/tenants/org_k7m2:setSpendCap", json={"monthlyCapMinor": cap, "reason": REASON})
    assert r.status_code == 200 and r.json()["monthlyCap"]["amountMinor"] == cap


# Validation and 404 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v1/ops/tenants/org_k7m2:suspend", {"reason": ""}),
        ("/v1/ops/tenants/org_k7m2:suspend", {"reason": "   "}),
        ("/v1/ops/tenants/org_k7m2:suspend", {"reason": "x" * 501}),
        ("/v1/ops/tenants/org_k7m2:suspend", {}),
        ("/v1/ops/tenants/org_k7m2:suspend", {"reason": REASON, "extra": 1}),
        ("/v1/ops/tenants/org_k7m2:setPlan", {"plan": "Gold", "reason": REASON}),
        ("/v1/ops/tenants/org_k7m2:setSpendCap", {"monthlyCapMinor": -1, "reason": REASON}),
        ("/v1/ops/tenants/org_k7m2:setSpendCap", {"monthlyCapMinor": 10_000_001, "reason": REASON}),
        ("/v1/ops/tenants", {**NEW_TENANT, "plan": "Gold"}),
        ("/v1/ops/tenants", {**NEW_TENANT, "reason": " "}),
        ("/v1/ops/tenants", {**NEW_TENANT, "monthlyCapMinor": 10_000_001}),
        ("/v1/ops/tenants", {**NEW_TENANT, "ownerEmail": "not-an-email"}),
        ("/v1/ops/tenants", {**NEW_TENANT, "name": " "}),
        ("/v1/ops/tenants", {**NEW_TENANT, "trialDays": 0}),
    ],
)
def test_invalid_bodies_are_422_and_change_nothing(client, path, body):
    before = len(get_store().audit_log)
    r = client.post(path, json=body)
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "SCHEMA_INVALID"
    assert len(get_store().audit_log) == before


def test_a_reason_is_trimmed(client):
    client.post("/v1/ops/tenants/org_k7m2:suspend", json={"reason": "  Unpaid invoice  "})
    assert newest_audit(client)["reason"] == "Unpaid invoice"


@pytest.mark.parametrize(
    ("verb", "body"),
    [
        ("suspend", {"reason": REASON}),
        ("reactivate", {"reason": REASON}),
        ("setPlan", {"plan": "Pro", "reason": REASON}),
        ("setSpendCap", {"monthlyCapMinor": 100, "reason": REASON}),
    ],
)
def test_actions_on_an_unknown_tenant_are_404(client, verb, body):
    r = client.post(f"/v1/ops/tenants/org_none:{verb}", json=body)
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


# Audit -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body", "action", "target"),
    [
        ("/v1/ops/tenants/org_k7m2:suspend", {"reason": REASON}, "tenant.suspend", "org_k7m2"),
        ("/v1/ops/tenants/org_a3wc:reactivate", {"reason": REASON}, "tenant.reactivate", "org_a3wc"),
        (
            "/v1/ops/tenants/org_k7m2:setPlan",
            {"plan": "Pro", "reason": REASON},
            "tenant.set_plan",
            "org_k7m2",
        ),
        (
            "/v1/ops/tenants/org_k7m2:setSpendCap",
            {"monthlyCapMinor": 1234, "reason": REASON},
            "tenant.set_spend_cap",
            "org_k7m2",
        ),
    ],
)
def test_every_mutation_writes_an_audit_entry(client, path, body, action, target):
    before = len(client.get("/v1/ops/audit", params={"limit": 500}).json())
    assert client.post(path, json=body).status_code == 200
    entries = client.get("/v1/ops/audit", params={"limit": 500}).json()
    assert len(entries) == before + 1
    entry = entries[0]
    assert entry["action"] == action
    assert (entry["targetType"], entry["targetId"]) == ("tenant", target)
    assert entry["reason"] == REASON
    assert (entry["actorEmail"], entry["actorRole"]) == ("ops@newmachin.es", "owner")
    assert entry["summary"] and entry["id"] and entry["at"]


def test_a_rejected_mutation_writes_no_audit_entry(client):
    before = len(get_store().audit_log)
    client.post("/v1/ops/tenants/org_a3wc:suspend", json={"reason": REASON})
    assert len(get_store().audit_log) == before


def test_audit_is_seeded_newest_first(client):
    entries = client.get("/v1/ops/audit").json()
    assert 10 <= len(entries) <= 100
    stamps = [e["at"] for e in entries]
    assert stamps == sorted(stamps, reverse=True)
    assert len({e["id"] for e in entries}) == len(entries)


def test_audit_filters_and_limits(client):
    client.post("/v1/ops/tenants/org_k7m2:suspend", json={"reason": REASON})
    client.post("/v1/ops/tenants/org_k7m2:reactivate", json={"reason": REASON})
    mine = client.get("/v1/ops/audit", params={"targetType": "tenant", "targetId": "org_k7m2"}).json()
    assert [e["action"] for e in mine[:2]] == ["tenant.reactivate", "tenant.suspend"]
    assert all(e["targetId"] == "org_k7m2" for e in mine)
    assert len(client.get("/v1/ops/audit", params={"limit": 2}).json()) == 2


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"targetType": "planet"}])
def test_audit_rejects_bad_queries(client, params):
    assert client.get("/v1/ops/audit", params=params).status_code == 422


def test_audit_must_run_inside_the_store_lock(client):
    from app.auth import DEV_OPS_ACTOR

    with pytest.raises(RuntimeError, match="locked_store"):
        get_store().audit(DEV_OPS_ACTOR, "tenant.note", "tenant", "org_hp01", REASON, "Note")


def test_a_churned_tenant_cannot_change_plan_or_spend_cap(client):
    before = len(get_store().audit_log)
    plan = client.post("/v1/ops/tenants/org_u6rn:setPlan", json={"plan": "Starter", "reason": REASON})
    cap = client.post(
        "/v1/ops/tenants/org_u6rn:setSpendCap", json={"monthlyCapMinor": 12345, "reason": REASON}
    )
    for r in (plan, cap):
        assert r.status_code == 409 and r.json()["code"] == "INVALID_TRANSITION"
    assert len(get_store().audit_log) == before
