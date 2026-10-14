"""Marketplace listings, the connector catalog and their effects on the customer API. The suite runs in dev
mode, so the operator is an owner; the support role is exercised by patching the dependency."""

import pytest

from app.auth import DEV_OPS_ACTOR, OpsActor, get_ops_actor
from app.store import get_store

REASON = "Reviewed by the marketplace team"
BODY = {"reason": REASON}
NEW_PACK = {
    "name": "Daily Cash Summary",
    "slug": "daily-cash-summary",
    "publisher": "New Machines Labs",
    "category": "Finance operations",
    "outcome": "A one-page cash summary every morning.",
    "description": "Reads your payouts and bank notes and writes a short summary.",
    "riskClass": "low",
    "connectors": [
        {"app": "Google Sheets", "access": "read"},
        {"app": "Gmail", "access": "write (approval)"},
    ],
    "humanReview": "A person reads the summary before it is sent.",
    "reason": REASON,
}


def customer_slugs(client):
    return {p["slug"] for p in client.get("/v1/workflow-packs").json()}


def audit_for(client, target_type, target_id):
    return client.get("/v1/ops/audit", params={"targetType": target_type, "targetId": target_id}).json()


def pack_post(client, slug, verb, body=BODY):
    return client.post(f"/v1/ops/packs/{slug}:{verb}", json=body)


def connector_post(client, cid, verb, body=BODY):
    return client.post(f"/v1/ops/connectors/{cid}:{verb}", json=body)


@pytest.fixture
def support_client(client):
    client.app.dependency_overrides[get_ops_actor] = lambda: OpsActor("u", "support@newmachin.es", "support")
    yield client
    client.app.dependency_overrides.clear()


# Packs: reads and seed --------------------------------------------------------------------------------


def test_the_seed_has_seven_published_and_one_of_each_other_state(client):
    listings = client.get("/v1/ops/packs").json()
    counts = {
        s: sum(1 for entry in listings if entry["status"] == s) for s in {e["status"] for e in listings}
    }
    assert counts == {"published": 7, "in_review": 2, "draft": 1, "deprecated": 1}
    in_review = client.get("/v1/ops/packs", params={"status": "in_review"}).json()
    assert {p["publisher"] for p in in_review}.isdisjoint({"New Machines Labs"})
    assert all(p["submittedAt"] for p in in_review)


def test_a_bad_status_filter_is_422(client):
    assert client.get("/v1/ops/packs", params={"status": "live"}).status_code == 422


def test_pack_detail_has_the_customer_pack_and_history(client):
    detail = client.get("/v1/ops/packs/refund-triage").json()
    assert detail["pack"]["slug"] == "refund-triage"
    assert detail["pack"]["connectors"][0]["app"] == "Shopify"
    assert detail["connectors"] == ["Shopify", "Gmail"]
    assert detail["history"] and {"at", "by", "action", "note"} <= set(detail["history"][0])


def test_listings_carry_function_and_industries_from_the_pack_definition(client):
    listings = {p["slug"]: p for p in client.get("/v1/ops/packs").json()}
    recon = listings["order-payment-reconciliation"]
    assert recon["function"] == {"id": "finance-ops", "name": "Finance operations"}
    assert [i["name"] for i in recon["industries"]] == ["Retail & Commerce", "Manufacturing"]
    # A listing without a pack definition is unclassified.
    inventory = listings["weekly-inventory-report"]
    assert inventory.get("function") is None and inventory["industries"] == []
    assert listings["refund-triage"]["function"] == {"id": "customer-ops", "name": "Customer operations"}
    detail = client.get("/v1/ops/packs/order-payment-reconciliation").json()
    assert detail["function"]["id"] == "finance-ops"
    assert detail["pack"]["function"] == "finance-ops"
    assert detail["pack"]["industries"] == ["retail-commerce", "manufacturing"]


def test_an_unknown_pack_is_404_everywhere(client):
    assert client.get("/v1/ops/packs/nope").status_code == 404
    for verb in ("submit", "approve", "reject", "deprecate", "republish", "certify"):
        assert pack_post(client, "nope", verb).status_code == 404


# Packs: creation ---------------------------------------------------------------------------------------


def test_create_makes_a_draft_and_a_hidden_customer_pack(client):
    r = client.post("/v1/ops/packs", json=NEW_PACK)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft" and body["version"] == "0.1.0" and body["certified"] is False
    assert body["connectors"] == ["Google Sheets", "Gmail"]
    pack = body["pack"]
    assert pack["installed"] is False and pack["certified"] is False and pack["regions"] == ["global"]
    assert pack["agents"] == []
    assert pack["estimate"]["aiMin"] == {"amountMinor": 0, "currency": "USD"}
    assert pack["connectors"][1] == {"app": "Gmail", "access": "write (approval)"}
    assert [h["action"] for h in body["history"]] == ["create"]
    assert any(p.slug == "daily-cash-summary" for p in get_store().packs)
    assert "daily-cash-summary" not in customer_slugs(client)
    assert client.get("/v1/workflow-packs/daily-cash-summary").status_code == 404
    entry = audit_for(client, "pack", "daily-cash-summary")[0]
    assert entry["action"] == "pack.create" and entry["reason"] == REASON


def test_create_rejects_a_taken_slug(client):
    r = client.post("/v1/ops/packs", json={**NEW_PACK, "slug": "refund-triage"})
    assert r.status_code == 409 and r.json()["code"] == "SLUG_TAKEN"
    assert client.post("/v1/ops/packs", json=NEW_PACK).status_code == 201
    again = client.post("/v1/ops/packs", json=NEW_PACK)
    assert again.status_code == 409 and again.json()["code"] == "SLUG_TAKEN"
    assert len(audit_for(client, "pack", "daily-cash-summary")) == 1


@pytest.mark.parametrize("slug", ["Bad Slug", "UPPER", "-lead", "trail-", "dou--ble", "under_score", ""])
def test_create_validates_the_slug(client, slug):
    assert client.post("/v1/ops/packs", json={**NEW_PACK, "slug": slug}).status_code == 422


@pytest.mark.parametrize(
    "change",
    [
        {"riskClass": "extreme"},
        {"connectors": [{"app": "Gmail", "access": "admin"}]},
        {"connectors": [{"app": "Gmail", "access": "read", "mocked": True}]},
        {"connectors": [{"app": "Gmail", "access": "read", "extra": 1}]},
        {"connectors": [{"app": "", "access": "read"}]},
        {"reason": "   "},
        {"name": ""},
        {"surprise": 1},
    ],
)
def test_create_validates_the_body(client, change):
    assert client.post("/v1/ops/packs", json={**NEW_PACK, **change}).status_code == 422
    assert "daily-cash-summary" not in get_store().pack_listings


# Packs: the state machine ------------------------------------------------------------------------------


def test_the_review_flow_end_to_end(client):
    client.post("/v1/ops/packs", json=NEW_PACK)
    slug = "daily-cash-summary"
    r = pack_post(client, slug, "submit")
    assert r.status_code == 200 and r.json()["status"] == "in_review" and r.json()["submittedAt"]
    assert slug not in customer_slugs(client)
    r = pack_post(client, slug, "approve")
    assert r.json()["status"] == "published"
    assert slug in customer_slugs(client)
    assert client.get(f"/v1/workflow-packs/{slug}").status_code == 200
    r = pack_post(client, slug, "certify")
    assert r.json()["certified"] is True and r.json()["pack"]["certified"] is True
    assert client.get(f"/v1/workflow-packs/{slug}").json()["certified"] is True
    assert pack_post(client, slug, "deprecate").json()["status"] == "deprecated"
    assert pack_post(client, slug, "republish").json()["status"] == "published"
    actions = [h["action"] for h in client.get(f"/v1/ops/packs/{slug}").json()["history"]]
    assert actions == ["create", "submit", "approve", "certify", "deprecate", "republish"]
    audited = [e["action"] for e in audit_for(client, "pack", slug)]
    assert audited == [
        "pack.republish",
        "pack.deprecate",
        "pack.certify",
        "pack.approve",
        "pack.submit",
        "pack.create",
    ]


def test_every_transition_writes_before_and_after_in_the_audit_entry(client):
    pack_post(client, "customs-paperwork-prep", "approve", {"reason": "  Passport looks fine  "})
    entry = audit_for(client, "pack", "customs-paperwork-prep")[0]
    assert entry["action"] == "pack.approve"
    assert entry["reason"] == "Passport looks fine"
    assert entry["summary"] == "Status in_review → published"
    assert entry["actorEmail"] == DEV_OPS_ACTOR.email


def test_reject_stores_the_reason_and_hides_the_pack(client):
    r = pack_post(client, "subscription-winback", "reject", {"reason": "Offers need a legal review first"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["reviewNotes"] == "Offers need a legal review first"
    assert "subscription-winback" not in customer_slugs(client)
    assert client.get("/v1/workflow-packs/subscription-winback").status_code == 404


def test_a_rejected_pack_can_be_resubmitted_and_approved(client):
    pack_post(client, "subscription-winback", "reject")
    assert pack_post(client, "subscription-winback", "submit").json()["status"] == "in_review"
    approved = pack_post(client, "subscription-winback", "approve").json()
    assert approved["status"] == "published" and "reviewNotes" not in approved


@pytest.mark.parametrize(
    ("slug", "verb"),
    [
        ("supplier-onboarding", "approve"),  # draft
        ("supplier-onboarding", "reject"),
        ("supplier-onboarding", "deprecate"),
        ("supplier-onboarding", "republish"),
        ("supplier-onboarding", "certify"),
        ("customs-paperwork-prep", "submit"),  # in review
        ("customs-paperwork-prep", "deprecate"),
        ("customs-paperwork-prep", "republish"),
        ("customs-paperwork-prep", "certify"),
        ("refund-triage", "submit"),  # published
        ("refund-triage", "approve"),
        ("refund-triage", "reject"),
        ("refund-triage", "republish"),
        ("refund-triage", "certify"),  # already certified
        ("chargeback-evidence", "submit"),
        ("legacy-order-export", "submit"),  # deprecated
        ("legacy-order-export", "approve"),
        ("legacy-order-export", "reject"),
        ("legacy-order-export", "deprecate"),
        ("legacy-order-export", "certify"),
    ],
)
def test_invalid_transitions_are_409_and_change_nothing(client, slug, verb):
    before = client.get(f"/v1/ops/packs/{slug}").json()
    audits = len(client.get("/v1/ops/audit", params={"limit": 500}).json())
    r = pack_post(client, slug, verb)
    assert r.status_code == 409 and r.json()["code"] == "INVALID_TRANSITION"
    assert client.get(f"/v1/ops/packs/{slug}").json() == before
    assert len(client.get("/v1/ops/audit", params={"limit": 500}).json()) == audits


def test_certify_works_on_an_uncertified_published_pack(client):
    r = pack_post(client, "chargeback-evidence", "certify")
    assert r.status_code == 200 and r.json()["certified"] is True
    assert client.get("/v1/workflow-packs/chargeback-evidence").json()["certified"] is True


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "x" * 501}, {"reason": "ok", "extra": 1}])
def test_transitions_validate_the_reason(client, body):
    assert pack_post(client, "customs-paperwork-prep", "approve", body).status_code == 422
    assert get_store().pack_listings["customs-paperwork-prep"].status == "in_review"


# Packs: the customer marketplace -----------------------------------------------------------------------


def test_the_customer_sees_the_seven_published_packs(client):
    assert customer_slugs(client) == {
        "order-payment-reconciliation",
        "overdue-invoice-follow-up",
        "refund-triage",
        "weekly-inventory-report",
        "shipping-exceptions",
        "chargeback-evidence",
        "catalog-localization-en-ja",
    }
    for hidden in ("customs-paperwork-prep", "supplier-onboarding", "legacy-order-export"):
        assert client.get(f"/v1/workflow-packs/{hidden}").status_code == 404


def test_approving_an_in_review_pack_shows_it_to_customers(client):
    assert "customs-paperwork-prep" not in customer_slugs(client)
    pack_post(client, "customs-paperwork-prep", "approve")
    assert len(customer_slugs(client)) == 8
    assert client.get("/v1/workflow-packs/customs-paperwork-prep").status_code == 200


def test_deprecating_an_uninstalled_pack_hides_it(client):
    assert client.get("/v1/workflow-packs/shipping-exceptions").json()["installed"] is False
    pack_post(client, "shipping-exceptions", "deprecate")
    assert "shipping-exceptions" not in customer_slugs(client)
    assert client.get("/v1/workflow-packs/shipping-exceptions").status_code == 404
    pack_post(client, "shipping-exceptions", "republish")
    assert "shipping-exceptions" in customer_slugs(client)


def test_a_deprecated_pack_stays_visible_while_installed(client):
    assert client.get("/v1/workflow-packs/refund-triage").json()["installed"] is True
    pack_post(client, "refund-triage", "deprecate")
    assert "refund-triage" in customer_slugs(client)
    assert client.get("/v1/workflow-packs/refund-triage").status_code == 200


def test_a_hidden_pack_cannot_be_installed(client):
    pack_post(client, "shipping-exceptions", "deprecate")
    r = client.post(
        "/v1/organizations/org_hp01/agent-installations",
        json={"packSlug": "shipping-exceptions", "capMinor": 500, "reviewerPool": "team"},
    )
    assert r.status_code == 404
    assert get_store().pack_listings["shipping-exceptions"].status == "deprecated"


def test_suggestions_never_name_a_hidden_pack(client):
    text = {"text": "shipping parcel carrier late lost"}
    assert (
        client.post("/v1/workflow-packs:suggest", json=text).json()["pack"]["slug"] == "shipping-exceptions"
    )
    pack_post(client, "shipping-exceptions", "deprecate")
    assert "pack" not in client.post("/v1/workflow-packs:suggest", json=text).json()


def test_a_pack_with_no_listing_counts_as_published(client):
    del get_store().pack_listings["refund-triage"]
    assert "refund-triage" in customer_slugs(client)
    assert client.get("/v1/workflow-packs/refund-triage").status_code == 200


# Connectors: reads and seed ----------------------------------------------------------------------------


def test_the_connector_seed(client):
    entries = {c["id"]: c for c in client.get("/v1/ops/connectors").json()}
    assert len(entries) == 11
    assert entries["smarthr"]["status"] == "disabled" and entries["line-works"]["status"] == "beta"
    assert {
        entries[i]["app"] for i in ("google-sheets", "gmail", "google-drive", "slack", "shopify", "stripe")
    } == {
        "Google Sheets",
        "Gmail",
        "Google Drive",
        "Slack",
        "Shopify",
        "Stripe",
    }
    sheets = entries["google-sheets"]
    assert sheets["defaults"] == {
        "read": "permit",
        "write": "require_approval",
        "delete": "deny",
        "money": "deny",
    }
    assert {"at", "ok", "latencyMs"} <= set(sheets["lastHealthCheck"])
    assert {c["provider"] for c in entries.values()} <= {"Composio", "Native", "Mock"}


def test_available_toolkits_exclude_the_added_ones(client):
    available = client.get("/v1/ops/connectors/available").json()
    assert len(available) == 8
    assert {"notion", "hubspot", "xero", "quickbooks", "zendesk", "asana", "airtable", "microsoft-teams"} == {
        t["slug"] for t in available
    }
    assert set(available[0]) == {"slug", "name", "category", "authType"}
    client.post("/v1/ops/connectors", json={"toolkitSlug": "notion", "status": "beta", **BODY})
    assert "notion" not in {t["slug"] for t in client.get("/v1/ops/connectors/available").json()}


# Connectors: add ---------------------------------------------------------------------------------------


def test_add_a_connector_and_its_customer_effect(client):
    assert "Notion" not in {c["app"] for c in client.get("/v1/connections").json()}
    r = client.post("/v1/ops/connectors", json={"toolkitSlug": "notion", "status": "enabled", **BODY})
    assert r.status_code == 201
    entry = r.json()
    assert entry["id"] == "notion" and entry["app"] == "Notion" and entry["status"] == "enabled"
    assert entry["provider"] == "Composio" and entry["tenantsConnected"] == 0
    assert entry["defaults"] == {
        "read": "permit",
        "write": "require_approval",
        "delete": "deny",
        "money": "deny",
    }
    conn = next(c for c in client.get("/v1/connections").json() if c["app"] == "Notion")
    assert conn["status"] == "not_connected" and conn["account"] == "" and conn["grants"] == []
    assert conn["provider"] == "Composio"
    log = audit_for(client, "connector", "notion")[0]
    assert log["action"] == "connector.add" and log["reason"] == REASON


def test_a_beta_connector_is_also_offered_to_customers(client):
    client.post("/v1/ops/connectors", json={"toolkitSlug": "asana", "status": "beta", **BODY})
    assert "Asana" in {c["app"] for c in client.get("/v1/connections").json()}


def test_add_errors(client):
    unknown = client.post("/v1/ops/connectors", json={"toolkitSlug": "nope", "status": "enabled", **BODY})
    assert unknown.status_code == 404
    again = client.post("/v1/ops/connectors", json={"toolkitSlug": "slack", "status": "enabled", **BODY})
    assert again.status_code == 409
    for bad in (
        {"toolkitSlug": "notion", "status": "disabled", **BODY},
        {"toolkitSlug": "Not Kebab", "status": "enabled", **BODY},
        {"toolkitSlug": "notion", "status": "enabled", "reason": " "},
    ):
        assert client.post("/v1/ops/connectors", json=bad).status_code == 422
    assert audit_for(client, "connector", "notion") == []
    assert len(get_store().connector_catalog) == 11


# Connectors: enable, disable, defaults, health ---------------------------------------------------------


def test_disable_and_re_enable_affect_the_customer_connections(client):
    before = next(c for c in client.get("/v1/connections").json() if c["app"] == "Gmail")
    assert before["status"] == "connected" and before["grants"]
    r = connector_post(client, "gmail", "disable")
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    after = next(c for c in client.get("/v1/connections").json() if c["app"] == "Gmail")
    assert after["status"] == "not_connected" and after["grants"] == []
    assert audit_for(client, "connector", "gmail")[0]["summary"] == "Status enabled → disabled"
    r = connector_post(client, "gmail", "enable")
    assert r.json()["status"] == "enabled"
    again = next(c for c in client.get("/v1/connections").json() if c["app"] == "Gmail")
    assert again["status"] == "not_connected"  # the customer reconnects it themselves
    assert [c["app"] for c in client.get("/v1/connections").json()].count("Gmail") == 1
    assert audit_for(client, "connector", "gmail")[0]["summary"] == "Status disabled → enabled"


def test_enabling_a_disabled_connector_adds_its_connection(client):
    assert "SmartHR" not in {c["app"] for c in client.get("/v1/connections").json()}
    assert connector_post(client, "smarthr", "enable").json()["status"] == "enabled"
    smart = next(c for c in client.get("/v1/connections").json() if c["app"] == "SmartHR")
    assert smart["status"] == "not_connected" and smart["oauthScopes"] == ["employee:read"]


def test_a_beta_connector_can_be_enabled_or_disabled(client):
    assert connector_post(client, "line-works", "enable").json()["status"] == "enabled"
    assert connector_post(client, "line-works", "disable").json()["status"] == "disabled"


def test_no_change_transitions_are_409_and_not_audited(client):
    audits = len(client.get("/v1/ops/audit", params={"limit": 500}).json())
    for cid, verb in (("gmail", "enable"), ("smarthr", "disable")):
        r = connector_post(client, cid, verb)
        assert r.status_code == 409 and r.json()["code"] == "NO_CHANGE"
    assert len(client.get("/v1/ops/audit", params={"limit": 500}).json()) == audits


def test_set_defaults(client):
    new = {"read": "permit", "write": "deny", "delete": "deny", "money": "require_approval"}
    r = connector_post(client, "stripe", "setDefaults", {"defaults": new, "reason": REASON})
    assert r.status_code == 200 and r.json()["defaults"] == new
    entry = audit_for(client, "connector", "stripe")[0]
    assert entry["action"] == "connector.set_defaults"
    assert entry["summary"] == "write require_approval → deny"
    same = connector_post(client, "stripe", "setDefaults", {"defaults": new, "reason": REASON})
    assert same.status_code == 409 and same.json()["code"] == "NO_CHANGE"


@pytest.mark.parametrize(
    "body",
    [
        {"reason": REASON},
        {"defaults": {"read": "permit", "write": "deny", "delete": "deny"}, "reason": REASON},
        {"defaults": {"read": "allow", "write": "deny", "delete": "deny", "money": "deny"}, "reason": REASON},
    ],
)
def test_set_defaults_validates(client, body):
    assert connector_post(client, "stripe", "setDefaults", body).status_code == 422


def test_connector_actions_on_an_unknown_id_are_404(client):
    defaults = {"read": "permit", "write": "deny", "delete": "deny", "money": "deny"}
    assert connector_post(client, "nope", "enable").status_code == 404
    assert connector_post(client, "nope", "disable").status_code == 404
    assert (
        connector_post(client, "nope", "setDefaults", {"defaults": defaults, "reason": REASON}).status_code
        == 404
    )
    assert client.post("/v1/ops/connectors/nope:healthCheck").status_code == 404


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "x" * 501}])
def test_connector_actions_validate_the_reason(client, body):
    assert connector_post(client, "gmail", "disable", body).status_code == 422
    assert get_store().connector_catalog["gmail"].status == "enabled"


def test_health_check_is_deterministic_and_audited(client):
    r = client.post("/v1/ops/connectors/gmail:healthCheck")
    assert r.status_code == 200
    check = r.json()["lastHealthCheck"]
    assert check["ok"] is True and check["latencyMs"] == 180 + len("gmail") * 7
    assert check["at"].endswith("Z") or "+" in check["at"]
    entry = audit_for(client, "connector", "gmail")[0]
    assert entry["action"] == "connector.health_check" and entry["reason"] == "Manual health check"
    assert client.get("/v1/ops/connectors").json()[1]["lastHealthCheck"] == check


def test_health_check_fails_for_a_disabled_connector(client):
    check = client.post("/v1/ops/connectors/smarthr:healthCheck").json()["lastHealthCheck"]
    assert check["ok"] is False and check["note"] == "Connector is disabled"


# Roles -------------------------------------------------------------------------------------------------


def test_support_reads_but_cannot_mutate(support_client):
    client = support_client
    assert client.get("/v1/ops/packs").status_code == 200
    assert client.get("/v1/ops/packs/refund-triage").status_code == 200
    assert client.get("/v1/ops/connectors").status_code == 200
    assert client.get("/v1/ops/connectors/available").status_code == 200
    audits = len(client.get("/v1/ops/audit", params={"limit": 500}).json())
    calls = [
        ("/v1/ops/packs", NEW_PACK),
        ("/v1/ops/packs/nope:approve", {}),  # 403 comes before validation and lookup
        ("/v1/ops/packs/customs-paperwork-prep:approve", BODY),
        ("/v1/ops/packs/customs-paperwork-prep:reject", BODY),
        ("/v1/ops/packs/supplier-onboarding:submit", BODY),
        ("/v1/ops/packs/refund-triage:deprecate", BODY),
        ("/v1/ops/packs/legacy-order-export:republish", BODY),
        ("/v1/ops/packs/chargeback-evidence:certify", BODY),
        ("/v1/ops/connectors", {"toolkitSlug": "notion", "status": "enabled", **BODY}),
        ("/v1/ops/connectors/gmail:enable", BODY),
        ("/v1/ops/connectors/gmail:disable", BODY),
        ("/v1/ops/connectors/gmail:setDefaults", {"defaults": {}, "reason": ""}),
        ("/v1/ops/connectors/gmail:healthCheck", None),
    ]
    for path, body in calls:
        r = client.post(path, json=body) if body is not None else client.post(path)
        assert r.status_code == 403, path
        assert r.json()["code"] == "OPS_FORBIDDEN", path
    assert len(client.get("/v1/ops/audit", params={"limit": 500}).json()) == audits
    assert get_store().pack_listings["customs-paperwork-prep"].status == "in_review"
    assert get_store().connector_catalog["gmail"].status == "enabled"


def test_an_admin_is_recorded_as_the_actor(client):
    client.app.dependency_overrides[get_ops_actor] = lambda: OpsActor(
        "u2", "hana.okada@newmachin.es", "admin"
    )
    pack_post(client, "customs-paperwork-prep", "approve")
    entry = audit_for(client, "pack", "customs-paperwork-prep")[0]
    assert (entry["actorEmail"], entry["actorRole"]) == ("hana.okada@newmachin.es", "admin")
    history = client.get("/v1/ops/packs/customs-paperwork-prep").json()["history"]
    assert history[-1]["by"] == "hana.okada@newmachin.es"
    client.app.dependency_overrides.clear()


def test_defaults_reject_unknown_keys(client):
    new = {"read": "permit", "write": "deny", "delete": "deny", "money": "deny", "extra": "permit"}
    assert (
        connector_post(client, "stripe", "setDefaults", {"defaults": new, "reason": REASON}).status_code
        == 422
    )


def test_every_pack_listing_has_a_customer_pack(client):
    from app.store import get_store

    store = get_store()
    customer = {p.slug for p in store.packs}
    assert set(store.pack_listings) <= customer


def test_a_101_character_id_is_a_422(client):
    long = "x" * 101
    assert client.get(f"/v1/ops/packs/{long}").status_code == 422
    assert client.get(f"/v1/ops/tenants/{long}").status_code == 422
    assert pack_post(client, long, "submit").status_code == 422
    assert connector_post(client, long, "enable").status_code == 422
    assert client.post(f"/v1/ops/reviewers/{long}:approve", json=BODY).status_code == 422
    assert client.post(f"/v1/ops/guardrails/{long}:set", json={"enabled": True, **BODY}).status_code == 422
    assert client.post(f"/v1/ops/incidents/{long}:update", json=BODY).status_code == 422
