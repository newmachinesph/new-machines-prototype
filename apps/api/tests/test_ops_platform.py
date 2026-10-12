"""Workforce, runs, guardrails, billing, health, incidents and the overview. The suite runs in dev mode,
so the operator is an owner; the support role is exercised by patching the dependency."""

import pytest

from app.auth import OpsActor, get_ops_actor

REASON = "Checked with the team"
BODY = {"reason": REASON}


def audit_for(client, target_type, target_id):
    return client.get("/v1/ops/audit", params={"targetType": target_type, "targetId": target_id}).json()


def reviewer_post(client, rid, verb, body=BODY):
    return client.post(f"/v1/ops/reviewers/{rid}:{verb}", json=body)


def guardrail_post(client, key, body):
    return client.post(f"/v1/ops/guardrails/{key}:set", json=body)


@pytest.fixture
def support_client(client):
    client.app.dependency_overrides[get_ops_actor] = lambda: OpsActor("u", "support@newmachin.es", "support")
    yield client
    client.app.dependency_overrides.clear()


# Reviewers ---------------------------------------------------------------------------------------------


def test_the_reviewer_seed_has_ten_with_three_applicants_and_one_suspended(client):
    reviewers = client.get("/v1/ops/reviewers").json()
    assert len(reviewers) == 10
    statuses = [r["status"] for r in reviewers]
    assert statuses.count("applicant") == 3 and statuses.count("suspended") == 1
    assert {r["id"] for r in reviewers} >= {"rev_ph_017"}
    assert {"tasksDone30d", "earnings30d", "medianMinutes", "queue", "joinedAt"} <= set(reviewers[0])
    assert reviewers[0]["earnings30d"]["currency"] == "USD"


def test_reviewers_filter_by_status_and_reject_a_bad_one(client):
    applicants = client.get("/v1/ops/reviewers", params={"status": "applicant"}).json()
    assert len(applicants) == 3 and all(r["level"] == "trainee" for r in applicants)
    assert client.get("/v1/ops/reviewers", params={"status": "gone"}).status_code == 422


def test_approving_an_applicant_makes_them_an_active_trainee_and_is_audited(client):
    res = reviewer_post(client, "rev_ph_024", "approve")
    assert res.status_code == 200
    assert res.json()["status"] == "active" and res.json()["level"] == "trainee"
    entry = audit_for(client, "reviewer", "rev_ph_024")[0]
    assert entry["action"] == "reviewer.approve" and entry["reason"] == REASON
    assert (
        entry["actorEmail"] == "ops@newmachin.es"
        and entry["summary"] == "Status applicant → active (trainee)"
    )


def test_suspend_and_reinstate_round_trip(client):
    assert reviewer_post(client, "rev_ph_003", "suspend").json()["status"] == "suspended"
    assert reviewer_post(client, "rev_ph_003", "reinstate").json()["status"] == "active"
    actions = [e["action"] for e in audit_for(client, "reviewer", "rev_ph_003")]
    assert actions == ["reviewer.reinstate", "reviewer.suspend"]


def test_set_level_changes_an_active_reviewer(client):
    res = reviewer_post(client, "rev_ph_011", "setLevel", {"level": "senior", "reason": REASON})
    assert res.status_code == 200 and res.json()["level"] == "senior"
    assert audit_for(client, "reviewer", "rev_ph_011")[0]["summary"] == "Level qualified → senior"


@pytest.mark.parametrize(
    ("rid", "verb", "body", "code"),
    [
        ("rev_ph_003", "approve", BODY, "INVALID_TRANSITION"),
        ("rev_ph_024", "suspend", BODY, "INVALID_TRANSITION"),
        ("rev_ph_003", "reinstate", BODY, "INVALID_TRANSITION"),
        ("rev_sg_002", "reinstate", BODY, None),
        ("rev_sg_002", "suspend", BODY, "INVALID_TRANSITION"),
        ("rev_ph_024", "setLevel", {"level": "senior", "reason": REASON}, "INVALID_TRANSITION"),
        ("rev_sg_002", "setLevel", {"level": "senior", "reason": REASON}, "INVALID_TRANSITION"),
        ("rev_ph_011", "setLevel", {"level": "qualified", "reason": REASON}, "NO_CHANGE"),
    ],
)
def test_invalid_reviewer_moves_are_409_and_not_audited(client, rid, verb, body, code):
    before = len(client.get("/v1/ops/audit", params={"limit": 500}).json())
    res = reviewer_post(client, rid, verb, body)
    after = len(client.get("/v1/ops/audit", params={"limit": 500}).json())
    if code is None:
        assert res.status_code == 200 and after == before + 1
        return
    assert res.status_code == 409 and res.json()["code"] == code
    assert after == before


def test_reviewer_validation_and_404(client):
    assert reviewer_post(client, "nope", "approve").status_code == 404
    assert reviewer_post(client, "nope", "setLevel", {"level": "senior", "reason": REASON}).status_code == 404
    assert reviewer_post(client, "rev_ph_024", "approve", {"reason": "  "}).status_code == 422
    assert reviewer_post(client, "rev_ph_024", "approve", {}).status_code == 422
    assert (
        reviewer_post(client, "rev_ph_011", "setLevel", {"level": "god", "reason": REASON}).status_code == 422
    )
    assert reviewer_post(client, "rev_ph_011", "setLevel", {"reason": REASON}).status_code == 422
    assert audit_for(client, "reviewer", "rev_ph_024") == []


# Runs --------------------------------------------------------------------------------------------------


def test_runs_merge_the_demo_tenants_real_runs_with_the_seeded_ones(client):
    runs = client.get("/v1/ops/runs").json()
    tenants = {r["tenantId"] for r in runs}
    assert "org_hp01" in tenants and len(tenants) >= 6
    assert sum(r["tenantId"] != "org_hp01" for r in runs) == 14
    assert [r["startedAt"] for r in runs] == sorted((r["startedAt"] for r in runs), reverse=True)
    demo = next(r for r in runs if r["tenantId"] == "org_hp01")
    assert demo["tenantName"] == "Harbor & Pine Supply Co."
    assert demo["pack"] == "order-payment-reconciliation"
    assert demo["cost"]["currency"] == "USD"


def test_runs_filter_by_status_and_tenant(client):
    failed = client.get("/v1/ops/runs", params={"status": "FAILED"}).json()
    assert failed and all(r["status"] == "FAILED" for r in failed)
    mine = client.get("/v1/ops/runs", params={"tenant": "org_s9tq"}).json()
    assert len(mine) == 3 and all(r["tenantId"] == "org_s9tq" for r in mine)
    assert client.get("/v1/ops/runs", params={"tenant": "org_nope"}).json() == []
    assert client.get("/v1/ops/runs", params={"status": "DONE"}).status_code == 422


def test_waiting_runs_say_what_they_wait_on(client):
    waiting = [r for r in client.get("/v1/ops/runs").json() if r["status"] == "WAITING_FOR_HUMAN"]
    assert waiting and all(r["waitingOn"] == "human" for r in waiting)


def test_other_tenants_recent_runs_come_from_the_seed(client):
    detail = client.get("/v1/ops/tenants/org_k7m2").json()
    assert len(detail["recentRuns"]) == 3
    assert all(r["tenantId"] == "org_k7m2" for r in detail["recentRuns"])
    assert detail["recentRuns"][0]["startedAt"] >= detail["recentRuns"][-1]["startedAt"]
    assert client.get("/v1/ops/tenants/org_hp01").json()["recentRuns"][0]["tenantId"] == "org_hp01"


# Guardrails --------------------------------------------------------------------------------------------


def test_the_guardrail_seed(client):
    guardrails = client.get("/v1/ops/guardrails").json()
    kinds = [g["kind"] for g in guardrails]
    assert kinds.count("kill_switch") == 4 and kinds.count("flag") == 3 and kinds.count("limit") == 3
    by_key = {g["key"]: g for g in guardrails}
    assert by_key["platform_daily_ai_cap"]["value"] == 60000
    assert by_key["memory_auto_approve"]["enabled"] is False
    assert all(g["scope"] == "platform" for g in guardrails)


def test_toggling_a_kill_switch_records_who_and_audits(client):
    res = guardrail_post(client, "pause_all_runs", {"enabled": True, "reason": REASON})
    assert res.status_code == 200
    assert res.json()["enabled"] is True and res.json()["updatedBy"] == "ops@newmachin.es"
    entry = audit_for(client, "guardrail", "pause_all_runs")[0]
    assert entry["action"] == "guardrail.set" and entry["summary"] == "Enabled off → on"


def test_setting_a_limit_value(client):
    res = guardrail_post(client, "platform_daily_ai_cap", {"value": 80000, "reason": REASON})
    assert res.status_code == 200 and res.json()["value"] == 80000
    assert audit_for(client, "guardrail", "platform_daily_ai_cap")[0]["summary"] == "Limit $600.00 → $800.00"
    assert guardrail_post(client, "human_task_sla_minutes", {"value": 0, "reason": REASON}).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"reason": REASON},
        {"value": 10_000_001, "reason": REASON},
        {"value": -1, "reason": REASON},
        {"enabled": True, "reason": ""},
        {"enabled": True, "reason": REASON, "extra": 1},
    ],
)
def test_bad_guardrail_bodies_are_422(client, body):
    assert guardrail_post(client, "platform_daily_ai_cap", body).status_code == 422
    assert audit_for(client, "guardrail", "platform_daily_ai_cap")[0]["id"] == "aud_0003"


def test_a_value_on_a_switch_or_flag_is_422(client):
    assert guardrail_post(client, "pause_all_runs", {"value": 5, "reason": REASON}).status_code == 422
    assert guardrail_post(client, "decision_node_jev", {"value": 5, "reason": REASON}).status_code == 422
    assert audit_for(client, "guardrail", "pause_all_runs") == []


def test_unchanged_guardrail_settings_are_409(client):
    assert guardrail_post(client, "pause_all_runs", {"enabled": False, "reason": REASON}).status_code == 409
    res = guardrail_post(client, "platform_daily_ai_cap", {"value": 60000, "enabled": True, "reason": REASON})
    assert res.status_code == 409 and res.json()["code"] == "NO_CHANGE"
    assert audit_for(client, "guardrail", "pause_all_runs") == []


def test_unknown_guardrail_is_404(client):
    assert guardrail_post(client, "nope", {"enabled": True, "reason": REASON}).status_code == 404


# Billing -----------------------------------------------------------------------------------------------


def test_billing_is_simulated_and_references_seeded_ids(client):
    billing = client.get("/v1/ops/billing").json()
    assert billing["simulated"] is True
    assert billing["arr"]["amountMinor"] == billing["mrr"]["amountMinor"] * 12
    assert 0 < billing["grossMargin"] < 1
    tenants = {t["id"] for t in client.get("/v1/ops/tenants").json()}
    reviewers = {r["id"] for r in client.get("/v1/ops/reviewers").json()}
    assert billing["invoices"] and {i["tenantId"] for i in billing["invoices"]} <= tenants
    assert billing["payouts"] and {p["reviewerId"] for p in billing["payouts"]} <= reviewers
    assert {i["status"] for i in billing["invoices"]} <= {"paid", "open", "overdue", "void"}
    assert {p["status"] for p in billing["payouts"]} <= {"scheduled", "paid", "held"}
    assert client.get("/v1/ops/billing").json() == billing


# Health and incidents ----------------------------------------------------------------------------------


def declare(client, **over):
    body = {"title": "Cerbos decisions slow", "severity": "sev2", "services": ["cerbos"], "reason": REASON}
    return client.post("/v1/ops/incidents", json={**body, **over})


def service_state(client, key):
    return next(s for s in client.get("/v1/ops/health").json()["services"] if s["key"] == key)["status"]


def test_health_lists_ten_services_and_the_seeded_incidents(client):
    health = client.get("/v1/ops/health").json()
    assert health["simulated"] is True
    assert [s["key"] for s in health["services"]][:3] == ["api", "temporal_workers", "temporal_cloud"]
    assert len(health["services"]) == 10
    assert {"inc_0041", "inc_0042"} == {i["id"] for i in health["incidents"]}
    assert next(i for i in health["incidents"] if i["id"] == "inc_0041")["status"] == "resolved"
    assert service_state(client, "langfuse") == "degraded"


def test_declaring_an_incident_degrades_services_and_numbers_from_the_next_id(client):
    res = declare(client, services=["cerbos", "api", "cerbos"])
    assert res.status_code == 201
    incident = res.json()
    assert incident["id"] == "inc_0043" and incident["status"] == "investigating"
    assert incident["services"] == ["cerbos", "api"] and "resolvedAt" not in incident
    assert incident["updates"][0]["by"] == "ops@newmachin.es"
    assert service_state(client, "cerbos") == "degraded" and service_state(client, "api") == "degraded"
    assert declare(client).json()["id"] == "inc_0044"
    entry = audit_for(client, "incident", "inc_0043")[0]
    assert (
        entry["action"] == "incident.declare" and entry["summary"] == "Declared sev2: Cerbos decisions slow"
    )


@pytest.mark.parametrize(
    "over",
    [
        {"services": ["nope"]},
        {"services": []},
        {"severity": "sev9"},
        {"title": " "},
        {"reason": ""},
    ],
)
def test_bad_incident_declarations_are_422(client, over):
    assert declare(client, **over).status_code == 422
    assert len(client.get("/v1/ops/health").json()["incidents"]) == 2


def test_updating_an_incident_walks_the_status_flow(client):
    first = declare(client).json()["id"]
    url = f"/v1/ops/incidents/{first}:update"
    res = client.post(url, json={"status": "monitoring", "text": "Fix rolled out.", "reason": REASON})
    assert res.status_code == 200 and res.json()["status"] == "monitoring"
    assert res.json()["updates"][-1] == {
        **res.json()["updates"][-1],
        "by": "ops@newmachin.es",
        "text": "Fix rolled out.",
    }
    assert service_state(client, "cerbos") == "degraded"
    res = client.post(url, json={"status": "resolved", "text": "All clear.", "reason": REASON})
    assert res.json()["status"] == "resolved" and res.json()["resolvedAt"]
    assert service_state(client, "cerbos") == "operational"
    assert audit_for(client, "incident", first)[0]["summary"] == "Status monitoring → resolved"


def test_investigating_can_resolve_directly_and_cannot_go_back(client):
    iid = declare(client).json()["id"]
    url = f"/v1/ops/incidents/{iid}:update"
    mon = client.post(url, json={"status": "monitoring", "text": "x", "reason": REASON})
    assert mon.status_code == 200
    back = client.post(url, json={"status": "investigating", "text": "x", "reason": REASON})
    assert back.status_code == 409 and back.json()["code"] == "INVALID_TRANSITION"
    other = declare(client, services=["cloud_sql"]).json()["id"]
    direct = client.post(
        f"/v1/ops/incidents/{other}:update", json={"status": "resolved", "text": "x", "reason": REASON}
    )
    assert direct.status_code == 200 and service_state(client, "cloud_sql") == "operational"


def test_a_resolved_incident_cannot_be_updated(client):
    res = client.post(
        "/v1/ops/incidents/inc_0041:update", json={"status": "monitoring", "text": "x", "reason": REASON}
    )
    assert res.status_code == 409 and res.json()["code"] == "INCIDENT_RESOLVED"
    assert audit_for(client, "incident", "inc_0041")[0]["id"] == "aud_0007"


def test_a_service_stays_degraded_while_another_incident_still_names_it(client):
    a = declare(client).json()["id"]
    declare(client, title="Cerbos again")
    client.post(f"/v1/ops/incidents/{a}:update", json={"status": "resolved", "text": "x", "reason": REASON})
    assert service_state(client, "cerbos") == "degraded"


def test_incident_update_validation_and_404(client):
    url = "/v1/ops/incidents/inc_0042:update"
    assert (
        client.post(
            "/v1/ops/incidents/nope:update", json={"status": "resolved", "text": "x", "reason": REASON}
        ).status_code
        == 404
    )
    assert client.post(url, json={"status": "fixed", "text": "x", "reason": REASON}).status_code == 422
    assert client.post(url, json={"status": "resolved", "text": "", "reason": REASON}).status_code == 422
    assert client.post(url, json={"status": "resolved", "text": "x"}).status_code == 422


# Overview ----------------------------------------------------------------------------------------------


def overview(client):
    return client.get("/v1/ops/overview").json()


def kinds(client):
    return [a["kind"] for a in overview(client)["attention"]]


def test_overview_kpis_come_from_the_store(client):
    kpis = overview(client)["kpis"]
    assert (kpis["activeTenants"], kpis["trialTenants"]) == (5, 1)
    assert kpis["openHumanTasks"] == 3 and kpis["pendingApprovals"] == 1
    assert kpis["platformDailyCap"] == {"amountMinor": 60000, "currency": "USD"}
    assert kpis["incidentsOpen"] == 1


def test_overview_simulated_series_are_deterministic_and_labelled(client):
    first, second = overview(client), overview(client)
    assert first["runsByHour"] == second["runsByHour"] and len(first["runsByHour"]) == 24
    assert [h["hour"] for h in first["runsByHour"]] == list(range(24))
    assert first["kpis"]["runsToday"] == sum(
        h["completed"] + h["failed"] + h["waiting"] for h in first["runsByHour"]
    )
    assert set(first["simulatedFields"]) >= {
        "kpis.runsToday",
        "kpis.runSuccessRate7d",
        "kpis.aiSpendToday",
        "runsByHour",
    }
    assert first["kpis"]["aiSpendToday"]["amountMinor"] < first["kpis"]["platformDailyCap"]["amountMinor"]


def test_overview_attention_is_derived_and_ordered(client):
    items = overview(client)["attention"]
    by_kind = {k: [a for a in items if a["kind"] == k] for k in set(kinds(client))}
    assert len(by_kind["pack_review"]) == 2 and len(by_kind["reviewer_application"]) == 3
    assert len(by_kind["incident"]) == 1 and by_kind["incident"][0]["href"] == "/health"
    assert {a["href"] for a in by_kind["connector_error"]} == {"/connectors?c=smarthr"}
    assert all(a["href"].startswith("/marketplace/") for a in by_kind["pack_review"])
    assert all(a["href"] == "/workforce?tab=applicants" for a in by_kind["reviewer_application"])
    cap = by_kind["tenant_cap"]
    assert len(cap) == 1 and cap[0]["href"] == "/tenants/org_s9tq" and cap[0]["severity"] == "warn"
    assert {a["href"] for a in by_kind["tenant_at_risk"]} == {"/tenants/org_s9tq", "/tenants/org_u6rn"}
    rank = {"critical": 0, "warn": 1, "info": 2}
    assert [rank[a["severity"]] for a in items] == sorted(rank[a["severity"]] for a in items)
    for severity in rank:
        times = [a["at"] for a in items if a["severity"] == severity]
        assert times == sorted(times, reverse=True)


def test_approving_the_last_in_review_pack_removes_its_attention_item(client):
    for slug in ("customs-paperwork-prep", "subscription-winback"):
        assert kinds(client).count("pack_review") == (2 if slug.startswith("customs") else 1)
        assert client.post(f"/v1/ops/packs/{slug}:approve", json=BODY).status_code == 200
    assert "pack_review" not in kinds(client)


def test_attention_follows_reviewers_incidents_and_caps(client):
    reviewer_post(client, "rev_ph_024", "approve")
    assert kinds(client).count("reviewer_application") == 2
    client.post(
        "/v1/ops/incidents/inc_0042:update", json={"status": "resolved", "text": "x", "reason": REASON}
    )
    assert "incident" not in kinds(client) and overview(client)["kpis"]["incidentsOpen"] == 0
    declared = declare(client, severity="sev1").json()
    top = overview(client)["attention"][0]
    assert top["severity"] == "critical" and top["title"].startswith(declared["id"])
    client.post("/v1/ops/tenants/org_s9tq:setSpendCap", json={"monthlyCapMinor": 100000, "reason": REASON})
    assert "tenant_cap" not in kinds(client)
    client.post("/v1/ops/connectors/smarthr:enable", json=BODY)
    assert overview(client)["kpis"]["activeTenants"] == 5


def test_overview_recent_audit_is_the_eight_newest(client):
    guardrail_post(client, "pause_all_runs", {"enabled": True, "reason": "Latest change"})
    recent = overview(client)["recentAudit"]
    assert len(recent) == 8 and recent[0]["reason"] == "Latest change"
    assert [e["at"] for e in recent] == sorted((e["at"] for e in recent), reverse=True)


# Support is read-only; every mutation audits -----------------------------------------------------------

MUTATIONS = [
    ("/v1/ops/reviewers/rev_ph_024:approve", BODY),
    ("/v1/ops/reviewers/rev_ph_003:suspend", BODY),
    ("/v1/ops/reviewers/rev_sg_002:reinstate", BODY),
    ("/v1/ops/reviewers/rev_ph_011:setLevel", {"level": "senior", "reason": REASON}),
    ("/v1/ops/guardrails/pause_all_runs:set", {"enabled": True, "reason": REASON}),
    (
        "/v1/ops/incidents",
        {"title": "Slow", "severity": "sev3", "services": ["api"], "reason": REASON},
    ),
    ("/v1/ops/incidents/inc_0042:update", {"status": "resolved", "text": "x", "reason": REASON}),
]
READS = [
    "/v1/ops/reviewers",
    "/v1/ops/runs",
    "/v1/ops/guardrails",
    "/v1/ops/billing",
    "/v1/ops/health",
    "/v1/ops/overview",
]


@pytest.mark.parametrize(("path", "body"), MUTATIONS)
def test_support_gets_403_on_every_mutation_and_nothing_is_audited(support_client, path, body):
    before = len(support_client.get("/v1/ops/audit", params={"limit": 500}).json())
    res = support_client.post(path, json=body)
    assert res.status_code == 403 and res.json()["code"] == "OPS_FORBIDDEN"
    assert support_client.post(path, json={}).status_code == 403
    assert len(support_client.get("/v1/ops/audit", params={"limit": 500}).json()) == before


@pytest.mark.parametrize("path", READS)
def test_support_can_read(support_client, path):
    assert support_client.get(path).status_code == 200


@pytest.mark.parametrize(("path", "body"), MUTATIONS)
def test_every_mutation_writes_exactly_one_audit_entry(client, path, body):
    before = len(client.get("/v1/ops/audit", params={"limit": 500}).json())
    assert client.post(path, json=body).status_code in (200, 201)
    entries = client.get("/v1/ops/audit", params={"limit": 500}).json()
    assert len(entries) == before + 1 and entries[0]["reason"] == REASON
    assert entries[0]["actorEmail"] == "ops@newmachin.es"


RUN_BODY = {"packSlug": "order-payment-reconciliation", "input": "Orders Oct 11", "budgetMinor": 5000}


def test_pause_all_runs_blocks_new_runs_until_disabled(client):
    assert guardrail_post(client, "pause_all_runs", {"enabled": True, **BODY}).status_code == 200
    r = client.post("/v1/workflow-runs", json=RUN_BODY, headers={"Idempotency-Key": "p1"})
    assert r.status_code == 409 and r.json()["code"] == "PLATFORM_PAUSED"
    assert guardrail_post(client, "pause_all_runs", {"enabled": False, **BODY}).status_code == 200
    r = client.post("/v1/workflow-runs", json=RUN_BODY, headers={"Idempotency-Key": "p2"})
    assert r.status_code == 202
