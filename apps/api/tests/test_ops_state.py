"""Persisted ops state in the live workspace: connector settings, the pause switch and the ops audit log.
The demo workspace keeps its fixtures, so each live write is also checked against the untouched store."""

import re
from typing import get_args

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient

from app import auth, ops_state, settings, temporal_client
from app import db as app_db
from app.defs import registry
from app.defs.loader import load_bundle
from app.main import create_app
from app.models.ops import AuditTargetType
from app.store import get_store, reset_store
from tests.test_db import _drop_schema
from tests.test_live_catalog import PROJECT, USERS, As, Starts, _ready

OPS_EMAIL = "olga.ops@newmachin.es"
OPS_CLAIMS = {
    "sub": "uid_olga",
    "email": OPS_EMAIL,
    "email_verified": True,
    "firebase": {"sign_in_provider": "google.com"},
}
OPS = {"Authorization": "Bearer ops"}
REASON = "Testing the live ops state"
STRIPE_DEFAULTS = {"read": "permit", "write": "require_approval", "delete": "deny", "money": "deny"}


def _verify(token, request, audience=None, clock_skew_in_seconds=0):
    claims = OPS_CLAIMS if token == "ops" else USERS[token]
    return {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, **claims}


@pytest.fixture
def starts(db, monkeypatch) -> Starts:
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("NM_CONNECTOR_MODE", "sandbox")
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setenv("OPS_ADMIN_EMAILS", OPS_EMAIL)
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", _verify)
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    recorder = Starts()
    monkeypatch.setattr(temporal_client, "start_run", recorder)
    return recorder


@pytest.fixture
def live(starts) -> TestClient:
    reset_store()
    return TestClient(create_app())


@pytest.fixture
def ana(live) -> As:
    return As(live, "ana")


def ops_post(api: TestClient, path: str, **body):
    return api.post(path, json={"reason": REASON, **body}, headers=OPS)


def _rows(db, query: str, *args) -> list[dict]:
    return db.execute(query, args).fetchall()


def _store_connector(connector_id: str):
    return get_store().connector_catalog[connector_id].model_copy(deep=True)


# --- /v1/ops/me -----------------------------------------------------------------------------------------


def test_ops_me_names_the_live_workspace(live):
    me = live.get("/v1/ops/me", headers=OPS)
    assert me.status_code == 200, me.text
    assert me.json() == {"userId": "uid_olga", "email": OPS_EMAIL, "role": "admin", "workspace": "live"}


def test_ops_me_names_the_demo_workspace(client):
    assert client.get("/v1/ops/me").json()["workspace"] == "demo"


# --- connector toggles ----------------------------------------------------------------------------------


def test_disabling_and_enabling_a_connector_persists_and_audits(live, db):
    gmail_fixture = _store_connector("gmail")
    res = ops_post(live, "/v1/ops/connectors/stripe:disable")
    assert res.status_code == 200, res.text
    entry = res.json()
    assert (entry["id"], entry["app"], entry["status"]) == ("stripe", "Stripe", "disabled")
    assert (entry["tenantsConnected"], entry["callsToday"], entry["errorRate"]) == (0, 0, 0)
    assert entry["defaults"] == STRIPE_DEFAULTS
    [row] = _rows(db, "SELECT connector_key, status, defaults, updated_by FROM connector_settings")
    assert row == {"connector_key": "stripe", "status": "disabled", "defaults": None, "updated_by": OPS_EMAIL}

    again = ops_post(live, "/v1/ops/connectors/stripe:disable")
    assert again.status_code == 409 and again.json()["code"] == "NO_CHANGE"
    assert again.json()["detail"] == "Stripe is already disabled."

    assert ops_post(live, "/v1/ops/connectors/stripe:enable").json()["status"] == "enabled"
    audit = _rows(db, "SELECT actor_email, action, target_type, target_id, reason FROM ops_audit ORDER BY id")
    assert audit == [
        {
            "actor_email": OPS_EMAIL,
            "action": a,
            "target_type": "connector",
            "target_id": "stripe",
            "reason": REASON,
        }
        for a in ("connector.disable", "connector.enable")
    ]
    assert _store_connector("gmail") == gmail_fixture  # the demo catalog is untouched


def test_a_connector_without_a_row_is_enabled(live, db):
    res = ops_post(live, "/v1/ops/connectors/gmail:enable")
    assert res.status_code == 409 and res.json()["code"] == "NO_CHANGE"
    assert res.json()["detail"] == "Gmail is already enabled."
    assert _rows(db, "SELECT 1 FROM connector_settings") == []
    assert _rows(db, "SELECT 1 FROM ops_audit") == []


def test_setting_defaults_compares_against_the_definition_then_the_row(live, db):
    same = ops_post(live, "/v1/ops/connectors/stripe:setDefaults", defaults=STRIPE_DEFAULTS)
    assert same.status_code == 409 and same.json()["code"] == "NO_CHANGE"
    assert same.json()["detail"] == "Stripe already has these defaults."

    stricter = {**STRIPE_DEFAULTS, "read": "require_approval"}
    res = ops_post(live, "/v1/ops/connectors/stripe:setDefaults", defaults=stricter)
    assert res.status_code == 200, res.text
    assert res.json()["defaults"] == stricter and res.json()["status"] == "enabled"
    [row] = _rows(db, "SELECT status, defaults FROM connector_settings WHERE connector_key = 'stripe'")
    assert row == {"status": "enabled", "defaults": stricter}
    assert ops_post(live, "/v1/ops/connectors/stripe:setDefaults", defaults=stricter).status_code == 409

    [audit] = _rows(db, "SELECT action, data FROM ops_audit")
    assert audit["action"] == "connector.set_defaults"
    assert audit["data"]["summary"] == "read permit → require_approval"
    assert get_store().connector_catalog["google-sheets"].defaults.read == "permit"


def test_an_unknown_live_connector_is_a_404(live):
    assert ops_post(live, "/v1/ops/connectors/google-sheets:disable").status_code == 404  # a fixture id
    res = ops_post(live, "/v1/ops/connectors/nope:setDefaults", defaults=STRIPE_DEFAULTS)
    assert res.status_code == 404


def test_adding_a_connector_or_a_health_check_is_not_available_live(live, db):
    add = ops_post(live, "/v1/ops/connectors", toolkitSlug="hubspot", status="enabled")
    assert add.status_code == 409 and add.json()["code"] == "NOT_AVAILABLE_LIVE"
    assert add.json()["detail"] == "In the live workspace, a connector is added by publishing its definition."
    check = live.post("/v1/ops/connectors/stripe:healthCheck", headers=OPS)
    assert check.status_code == 409 and check.json()["code"] == "NOT_AVAILABLE_LIVE"
    assert _rows(db, "SELECT 1 FROM ops_audit") == []


def test_a_support_operator_cannot_change_live_connectors(live, monkeypatch, db):
    monkeypatch.setenv("OPS_ADMIN_EMAILS", "")
    monkeypatch.setenv("OPS_SUPPORT_EMAILS", OPS_EMAIL)
    assert ops_post(live, "/v1/ops/connectors/stripe:disable").status_code == 403
    assert _rows(db, "SELECT 1 FROM connector_settings") == []


# --- pinning --------------------------------------------------------------------------------------------


def test_a_live_run_pins_the_persisted_connector_settings(ana, live, starts, db):
    stricter = {**STRIPE_DEFAULTS, "write": "deny"}
    assert ops_post(live, "/v1/ops/connectors/stripe:disable").status_code == 200
    assert ops_post(live, "/v1/ops/connectors/shopify:setDefaults", defaults=stricter).status_code == 200
    _ready(ana)
    res = ana.start()
    assert res.status_code == 202, res.text
    [row] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", res.json()["id"])
    snapshot = row["snapshot"]
    assert snapshot["disabled"] == ["stripe"]
    assert snapshot["overrides"] == {
        "googlesheets": STRIPE_DEFAULTS,  # no row: the definition's defaults
        "shopify": stricter,
        "stripe": STRIPE_DEFAULTS,
    }


def test_snapshot_policy_defaults_to_the_definitions_and_skips_unknown_keys(starts, db):
    overrides, disabled = ops_state.snapshot_policy(db, ["stripe", "nope"])
    assert (overrides, disabled) == ({"stripe": STRIPE_DEFAULTS}, [])


# --- the pause guardrail --------------------------------------------------------------------------------


def _pause(api: TestClient, enabled: bool):
    return ops_post(api, "/v1/ops/guardrails/pause_all_runs:set", enabled=enabled)


def _guardrail(api: TestClient, key: str) -> dict:
    return next(g for g in api.get("/v1/ops/guardrails", headers=OPS).json() if g["key"] == key)


def test_pausing_blocks_live_run_starts_until_unpaused(ana, live, starts, db):
    _ready(ana)
    default = _guardrail(live, "pause_all_runs")
    assert (default["enabled"], default["updatedBy"]) == (False, "system")  # the seeded default, no fixture

    paused = _pause(live, True)
    assert paused.status_code == 200, paused.text
    assert (paused.json()["enabled"], paused.json()["updatedBy"]) == (True, OPS_EMAIL)
    assert _guardrail(live, "pause_all_runs")["enabled"] is True
    assert get_store().guardrails["pause_all_runs"].enabled is False  # the demo fixture is untouched
    assert _pause(live, True).json()["code"] == "NO_CHANGE"

    blocked = ana.start()
    assert blocked.status_code == 409 and blocked.json()["code"] == "PLATFORM_PAUSED"
    assert starts.calls == []

    assert _pause(live, False).json()["enabled"] is False
    assert ana.start().status_code == 202
    assert len(starts.calls) == 1
    [row] = _rows(db, "SELECT value, updated_by FROM platform_settings WHERE key = 'pause_all_runs'")
    assert row == {"value": {"enabled": False}, "updated_by": OPS_EMAIL}


def _pause_rows(db) -> list[dict]:
    return _rows(db, "SELECT key, value, updated_by FROM platform_settings")


def test_the_pause_has_no_value_and_needs_enabled(live, db):
    before = _pause_rows(db)
    assert ops_post(live, "/v1/ops/guardrails/pause_all_runs:set", value=3).status_code == 422
    assert _pause_rows(db) == before
    assert _rows(db, "SELECT 1 FROM ops_audit") == []


def test_no_fixture_value_reaches_the_live_pause_row(live, db):
    fixture = get_store().guardrails["pause_all_runs"]
    pause = _guardrail(live, "pause_all_runs")
    assert pause["updatedBy"] == "system" and pause["updatedBy"] != fixture.updated_by
    assert pause["updatedAt"] != fixture.updated_at
    [row] = _pause_rows(db)
    assert row == {"key": "pause_all_runs", "value": {"enabled": False}, "updated_by": "system"}


def test_migration_006_seeds_the_pause_switch_off(db):
    try:
        db.execute("DELETE FROM schema_migrations WHERE name = '006_ops_state.sql'")
        db.execute("DROP TABLE IF EXISTS connector_settings, platform_settings, ops_audit")
        # 006 indexes tables of 001
        db.execute("DROP INDEX IF EXISTS receipt_entries_tool_call_at, runs_created")
        assert app_db.migrate(db) == ["006_ops_state.sql"]
        assert _pause_rows(db) == [
            {"key": "pause_all_runs", "value": {"enabled": False}, "updated_by": "system"}
        ]
        assert ops_state.is_paused(db) is False
    finally:  # rebuild from scratch: 006 alone drops what later migrations changed (016 widens ops_audit)
        db.rollback()
        _drop_schema(db)
        app_db.migrate(db)


def test_migration_007_adds_tool_results_to_a_database_at_006(db):
    try:
        db.execute("DELETE FROM schema_migrations WHERE name = '007_tool_results.sql'")
        db.execute("DROP TABLE IF EXISTS tool_results")
        db.commit()
        applied = [r["name"] for r in _rows(db, "SELECT name FROM schema_migrations ORDER BY name")]
        # at 006: later migrations (008 on) may already be applied, 007 is not
        assert [n for n in applied if n < "007"][-1] == "006_ops_state.sql"
        assert "007_tool_results.sql" not in applied
        assert app_db.migrate(db) == ["007_tool_results.sql"]
        columns = _rows(
            db,
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'tool_results' ORDER BY ordinal_position",
        )
        assert [(c["column_name"], c["data_type"], c["is_nullable"]) for c in columns] == [
            ("run_id", "text", "NO"),
            ("event_key", "text", "NO"),
            ("result", "jsonb", "NO"),
            ("created_at", "timestamp with time zone", "YES"),
        ]
    finally:  # whatever failed above, `nm_test` keeps 007 for the tests after this one
        db.rollback()
        app_db.migrate(db)


def test_other_guardrails_stay_fixtures_live_and_cannot_be_changed(live, db):
    fixture = get_store().guardrails["block_money_moves"].model_copy()
    assert _guardrail(live, "block_money_moves") == fixture.model_dump(
        by_alias=True, mode="json", exclude_none=True
    )
    res = ops_post(live, "/v1/ops/guardrails/block_money_moves:set", enabled=True)
    assert res.status_code == 409 and res.json()["code"] == "NOT_AVAILABLE_LIVE"
    assert res.json()["detail"] == "In the live workspace, only the pause switch can be changed."
    assert get_store().guardrails["block_money_moves"].enabled is False
    assert ops_post(live, "/v1/ops/guardrails/nope:set", enabled=True).status_code == 404
    assert _rows(db, "SELECT 1 FROM ops_audit") == []


# --- the audit log --------------------------------------------------------------------------------------


def test_live_audit_reads_ops_audit_newest_first(live, db):
    assert live.get("/v1/ops/audit", headers=OPS).json() == []  # no fixture entries in the live workspace
    ops_post(live, "/v1/ops/connectors/stripe:disable")
    _pause(live, True)
    entries = live.get("/v1/ops/audit", headers=OPS).json()
    assert [(e["action"], e["targetId"]) for e in entries] == [
        ("guardrail.set", "pause_all_runs"),
        ("connector.disable", "stripe"),
    ]
    first = entries[0]
    assert first["actorEmail"] == OPS_EMAIL and first["actorRole"] == "admin"
    roles = _rows(db, "SELECT data->>'actor_role' AS role FROM ops_audit")
    assert roles == [{"role": "admin"}, {"role": "admin"}]  # stored, not the fallback
    assert (first["reason"], first["summary"]) == (REASON, "Enabled off → on")
    assert first["id"].startswith("aud_") and first["at"].endswith("Z")
    only = live.get("/v1/ops/audit", params={"targetType": "connector"}, headers=OPS).json()
    assert [e["targetId"] for e in only] == ["stripe"]
    assert len(live.get("/v1/ops/audit", params={"limit": 1}, headers=OPS).json()) == 1


def test_demo_audit_still_reads_the_fixtures(client):
    assert client.get("/v1/ops/audit").json() != []


def test_audit_stores_the_role_and_a_row_without_a_known_one_reads_as_admin(live, db):
    ops_state.audit(
        db,
        "owner@newmachin.es",
        "tenant.suspend",
        "tenant",
        "org_1",
        "r",
        {"summary": "s"},
        actor_role="owner",
    )
    ops_state.audit(db, "x@newmachin.es", "tenant.reactivate", "tenant", "org_1", "r", {"actor_role": "boss"})
    db.commit()
    [old_row] = _rows(db, "SELECT data FROM ops_audit WHERE action = 'tenant.suspend'")
    assert old_row["data"] == {"summary": "s", ops_state.ACTOR_ROLE_KEY: "owner"}
    entries = live.get("/v1/ops/audit", headers=OPS).json()
    assert [(e["action"], e["actorRole"]) for e in entries] == [
        ("tenant.reactivate", "admin"),
        ("tenant.suspend", "owner"),
    ]


def test_ops_audit_refuses_an_unknown_target_type(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        ops_state.audit(db, "x@newmachin.es", "thing.do", "thing", "t1", "r")  # type: ignore[arg-type]
    db.rollback()


def _check_values(db, table: str, column: str) -> set[str]:
    """The values a `CHECK (column IN (...))` constraint on `table` allows, read back from Postgres."""
    defs = _rows(
        db,
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
        "WHERE conrelid = %s::regclass AND contype = 'c'",
        table,
    )
    [found] = [d["def"] for d in defs if f"({column} =" in d["def"] or f"{column})::text =" in d["def"]]
    return set(re.findall(r"'([^']*)'::text", found))


def test_every_audit_target_type_is_allowed_by_the_ops_audit_check(db):
    """The `AuditTargetType` Literal and the CHECK on `ops_audit.target_type` list the same values: a type
    the Literal adds alone would pass the type checker and fail at INSERT, and the reverse is dead."""
    for target_type in get_args(AuditTargetType):
        ops_state.audit(db, "x@newmachin.es", "check.target", target_type, "t1", "r")
    db.rollback()
    assert _check_values(db, "ops_audit", "target_type") == set(get_args(AuditTargetType))


# --- definition publish and memory writes in the live workspace ----------------------------------------


def _audited(api: TestClient, db, action: str, target_id: str) -> None:
    [row] = _rows(
        db, "SELECT actor_email, target_type, reason, data FROM ops_audit WHERE action = %s", action
    )
    assert (row["actor_email"], row["reason"]) == (OPS_EMAIL, REASON)
    assert row["data"][ops_state.ACTOR_ROLE_KEY] == "admin" and row["data"]["summary"]
    entries = api.get("/v1/ops/audit", params={"targetType": row["target_type"]}, headers=OPS).json()
    assert (action, target_id) in [(e["action"], e["targetId"]) for e in entries]


def test_a_live_definition_publish_is_in_the_ops_audit(live, db):
    audit_before = list(get_store().audit_log)
    text = live.get("/v1/ops/definitions/memory_space/retail-commerce", headers=OPS).json()["yaml"]
    data = yaml.safe_load(text)
    data["name"] = f"{data['name']} (edited)"
    res = ops_post(
        live, "/v1/ops/definitions/memory_space/retail-commerce:publish", yaml=yaml.safe_dump(data)
    )
    assert res.status_code == 201, res.text
    _audited(live, db, "definition.publish", "memory_space/retail-commerce")
    assert get_store().audit_log == audit_before  # not in the demo store


def test_live_memory_add_and_delete_are_in_the_ops_audit(live, db):
    audit_before = list(get_store().audit_log)
    added = ops_post(
        live, "/v1/ops/memory/spaces/retail-commerce/items", text="Refunds over $500 need a lead."
    )
    assert added.status_code == 201, added.text
    item_id = added.json()["id"]
    _audited(live, db, "memory.add", item_id)
    deleted = ops_post(live, f"/v1/ops/memory/items/{item_id}:delete")
    assert deleted.status_code == 204, deleted.text
    _audited(live, db, "memory.delete", item_id)
    assert get_store().audit_log == audit_before
