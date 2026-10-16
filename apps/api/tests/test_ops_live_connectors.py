"""Ops connectors in the live workspace: one entry per connector definition, with the settings Ops persisted,
the orgs connected to it and today's tool calls (UTC) read from the receipts."""

from datetime import datetime, timedelta, timezone

import pytest
from psycopg.types.json import Jsonb

from app import ops_live, settings
from tests.live_seed import DENY, NOW, TODAY, add_entry, add_org, add_run, connect

OPS = {"Authorization": "Bearer ops"}  # signs in as the ops admin of the `live_ops` fixture
REASON = "Testing live connectors"
# Every connector definition, by key: the ops list is these and nothing else (no settings row without one).
CONNECTORS = sorted(p.stem for p in (settings.defs_dir() / "connectors").glob("*.yaml"))
DEFAULTS = {"read": "permit", "write": "require_approval", "delete": "deny", "money": "deny"}
STRICT = {"read": "require_approval", "write": "deny", "delete": "deny", "money": "deny"}


@pytest.fixture
def usage(defs):
    """Two orgs. Shopify: connected by both, 4 permitted calls today with 1 failure (one of them recorded
    under another display name), plus a failed call at 23:59 yesterday, a call the policy denied and a
    non-call entry. Stripe: connected by acme only (bolt's row is disconnected), disabled by Ops, and its
    calls today were all denied. A settings row for a key without a definition."""
    db = defs
    add_org(db, "org_acme", "Acme")
    add_org(db, "org_bolt", "Bolt")
    connect(db, "org_acme", "shopify", "sandbox")
    connect(db, "org_bolt", "shopify", "connected")
    connect(db, "org_acme", "stripe", "connected")
    connect(db, "org_bolt", "stripe", "not_connected")
    add_run(db, "run_a", "org_acme", TODAY + timedelta(hours=1))
    add_run(db, "run_b", "org_bolt", TODAY + timedelta(hours=2))
    for seq in range(3):
        add_entry(db, "run_a", seq, TODAY + timedelta(hours=1, minutes=seq), "shopify", ok=True)
    add_entry(db, "run_a", 3, TODAY + timedelta(hours=4), "shopify", ok=False, verdict=DENY)
    for seq in range(4, 7):
        add_entry(db, "run_a", seq, TODAY + timedelta(hours=5), "stripe", ok=False, verdict=DENY)
    add_entry(db, "run_b", 0, TODAY, "shopify", ok=False, app="Shopify Plus")  # 00:00 is today
    add_entry(db, "run_b", 1, TODAY - timedelta(minutes=1), "shopify", ok=False)  # 23:59 yesterday
    add_entry(db, "run_b", 2, TODAY + timedelta(hours=3), "shopify", ok=False, kind="node.failed")
    db.execute(
        "INSERT INTO connector_settings (connector_key, status, defaults, updated_by) VALUES "
        "('stripe', 'disabled', %s, 'ops'), ('ghost', 'disabled', NULL, 'ops')",
        (Jsonb(STRICT),),
    )
    db.commit()
    return db


def test_each_definition_is_one_connector_with_its_settings_and_todays_usage(usage):
    entries = {e.id: e for e in ops_live.list_connectors(usage, NOW)}
    assert {"custom-business-app", "shopify", "stripe"} <= set(CONNECTORS)
    assert list(entries) == CONNECTORS  # never the ghost row

    shopify = entries["shopify"].model_dump(by_alias=True, exclude_none=True)
    assert shopify == {
        "id": "shopify",
        "app": "Shopify",
        "category": "Commerce",
        "provider": "Composio",
        "authType": "oauth_managed",
        "status": "enabled",
        "tenantsConnected": 2,
        "callsToday": 4,
        "errorRate": 0.25,
        "defaults": DEFAULTS,
        "scopes": ["orders.read", "store.write", "store.read"],  # each capability once, in tool order
    }
    stripe = entries["stripe"]
    assert (stripe.status, stripe.defaults.model_dump(), stripe.tenants_connected) == ("disabled", STRICT, 1)
    assert (stripe.calls_today, stripe.error_rate, stripe.category) == (0, 0.0, "Payments")
    assert stripe.scopes == ["payments.read", "invoices.read", "payments.write"]
    assert (entries["gmail"].category, entries["googlesheets"].category) == ("Communication", "Spreadsheets")
    assert all(e.last_health_check is None for e in entries.values())
    # A connector on the platform's MCP server is not a Composio OAuth app; nobody connects it, so no tenant.
    business = entries["custom-business-app"]
    assert (business.provider, business.auth_type, business.status) == ("MCP", "api_key", "enabled")
    assert (business.tenants_connected, business.calls_today, business.owner_org_id) == (0, 0, None)
    assert business.scopes == ["business.read", "business.write"]


def test_tenants_connected_counts_only_connections_a_run_could_reach(usage):
    """A row the start gate would refuse (`routes.route_of`: a Composio row without its account, a status
    that does not match its mode) is not a connected tenant, whatever its status column says."""
    add_org(usage, "org_cane", "Cane")
    usage.execute(
        "INSERT INTO connections (org_id, app, status, mode, connected_by, account_id) VALUES "
        "('org_cane', 'shopify', 'connected', 'composio', 'u', NULL), "
        "('org_cane', 'stripe', 'connected', 'sandbox', 'u', NULL)"
    )
    usage.commit()
    entries = {e.id: e for e in ops_live.list_connectors(usage, NOW)}
    assert (entries["shopify"].tenants_connected, entries["stripe"].tenants_connected) == (2, 1)


def test_the_day_runs_from_midnight_to_midnight_utc(usage):
    # At NOW the call at 00:00 counts and the one at 23:59 yesterday does not (4 calls, 1 failed). A day
    # earlier, the day is the 11th: only the 23:59 call, and none of the 12th's.
    yesterday = ops_live.connector(usage, "shopify", NOW - timedelta(days=1))
    assert (yesterday.calls_today, yesterday.error_rate) == (1, 1.0)
    assert ops_live.connector(usage, "shopify", NOW + timedelta(days=1)).calls_today == 0
    # The day is the UTC one: 01:00 on the 13th in UTC+9 is 16:00 on the 12th in UTC.
    tokyo = datetime(2026, 10, 13, 1, 0, tzinfo=timezone(timedelta(hours=9)))
    assert ops_live.connector(usage, "shopify", tokyo).calls_today == 4


def test_a_connector_without_a_definition_is_none(usage):
    assert ops_live.connector(usage, "ghost", NOW) is None
    assert ops_live.connector(usage, "nope", NOW) is None


def test_a_naive_now_is_refused(usage):
    with pytest.raises(ValueError):
        ops_live.list_connectors(usage, NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        ops_live.connector(usage, "shopify", NOW.replace(tzinfo=None))


# --- through the API ------------------------------------------------------------------------------------


def test_the_live_list_and_actions_return_the_real_entry(live_ops, defs):
    add_org(defs, "org_acme", "Acme")
    connect(defs, "org_acme", "stripe", "connected")
    defs.commit()
    listed = live_ops.get("/v1/ops/connectors", headers=OPS)
    assert listed.status_code == 200, listed.text
    assert [c["id"] for c in listed.json()] == CONNECTORS
    assert all("lastHealthCheck" not in c for c in listed.json())
    by_id = {c["id"]: c for c in listed.json()}
    assert (by_id["custom-business-app"]["provider"], by_id["custom-business-app"]["authType"]) == (
        "MCP",
        "api_key",
    )
    assert (by_id["stripe"]["provider"], by_id["stripe"]["authType"]) == ("Composio", "oauth_managed")

    res = live_ops.post("/v1/ops/connectors/stripe:disable", json={"reason": REASON}, headers=OPS)
    assert res.status_code == 200, res.text
    assert (res.json()["status"], res.json()["tenantsConnected"]) == ("disabled", 1)
    assert "lastHealthCheck" not in res.json()
    res = live_ops.post(
        "/v1/ops/connectors/stripe:setDefaults", json={"defaults": STRICT, "reason": REASON}, headers=OPS
    )
    assert (res.json()["defaults"], res.json()["tenantsConnected"]) == (STRICT, 1)


def test_the_demo_connectors_keep_their_health_checks(client):
    assert all("lastHealthCheck" in c for c in client.get("/v1/ops/connectors").json())
