"""Ops tenants in the live workspace: each tenant is an `orgs` row, its figures read from that org's rows
only, and suspend, reactivate and the spend cap act on the org itself and are audited."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app import auth, settings, temporal_client
from app.defs import registry
from app.defs.loader import load_bundle
from app.main import create_app
from app.store import reset_store
from tests.test_live_catalog import PACK, PROJECT, As, Starts, _ready
from tests.test_ops_state import OPS, OPS_EMAIL, REASON, _verify

DEFAULT_CAP = 2500
SPENT = 400


@pytest.fixture
def live(db, monkeypatch) -> TestClient:
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("NM_CONNECTOR_MODE", "sandbox")
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setenv("OPS_ADMIN_EMAILS", OPS_EMAIL)
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", _verify)
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    monkeypatch.setattr(temporal_client, "start_run", Starts())
    reset_store()
    return TestClient(create_app())


@pytest.fixture
def ana(live) -> As:
    return As(live, "ana")


@pytest.fixture
def ben(live) -> As:
    return As(live, "ben")


def _money(minor: int) -> dict:
    return {"amountMinor": minor, "currency": "USD"}


def _spent(ai: int) -> Jsonb:
    return Jsonb({"ai": _money(ai), "tools": _money(0), "human": _money(0)})


def _finish(db, run_id: str, status: str, ai: int) -> None:
    """Give a started run its end status and what it spent."""
    db.execute(
        "UPDATE runs SET status = %s, projection = projection || jsonb_build_object('status', %s::text, "
        "'spent', %s::jsonb) WHERE id = %s",
        (status, status, _spent(ai), run_id),
    )
    db.commit()


def _copy_run(db, run_id: str, new_id: str, status: str, ai: int, days_ago: int) -> None:
    """Another run of the same org, `days_ago` days old."""
    db.execute(
        "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input, created_at) "
        "SELECT %s, org_id, pack_slug, %s, snapshot, projection || jsonb_build_object('id', %s::text, "
        "'status', %s::text, 'spent', %s::jsonb), input, now() - make_interval(days => %s) "
        "FROM runs WHERE id = %s",
        (new_id, status, new_id, status, _spent(ai), days_ago, run_id),
    )
    db.commit()


def _started(user: As) -> str:
    _ready(user)
    res = user.start()
    assert res.status_code == 202, res.text
    return res.json()["id"]


def _human_task(db, run_id: str, status: str = "open") -> None:
    db.execute(
        "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload) "
        "VALUES (%s, %s, 'review', 'human', %s, '{}')",
        (f"task_{status}_{run_id}", run_id, status),
    )
    db.commit()


def _tenants(api: TestClient, **params) -> list[dict]:
    res = api.get("/v1/ops/tenants", params=params, headers=OPS)
    assert res.status_code == 200, res.text
    return res.json()


def _by_id(api: TestClient) -> dict[str, dict]:
    return {t["id"]: t for t in _tenants(api)}


def _tenant(api: TestClient, org_id: str) -> dict:
    res = api.get(f"/v1/ops/tenants/{org_id}", headers=OPS)
    assert res.status_code == 200, res.text
    return res.json()


def ops_post(api: TestClient, path: str, **body):
    return api.post(path, json={"reason": REASON, **body}, headers=OPS)


@pytest.fixture
def busy(ana, ben, db) -> str:
    """Ana's org: hired, three apps connected, a run today that spent SPENT, a failed run 40 days ago, an
    open human task and a pending invitation. Ben's org has nothing. Returns ana's run id."""
    run_id = _started(ana)
    _finish(db, run_id, "COMPLETED", SPENT)
    _copy_run(db, run_id, "run_old", "FAILED", 900, days_ago=40)
    _human_task(db, run_id)
    _human_task(db, run_id, status="done")
    invited = ana.post(
        f"/v1/organizations/{ana.org_id}/invitations", json={"email": "cy@example.com", "role": "Member"}
    )
    assert invited.status_code in (200, 201), invited.text
    return run_id


# --- list -----------------------------------------------------------------------------------------------


def test_each_org_is_a_tenant_with_its_own_figures(live, ana, ben, busy):
    tenants = _by_id(live)
    assert set(tenants) == {ana.org_id, ben.org_id}
    a = tenants[ana.org_id]
    expected = {
        "id": ana.org_id,
        "name": "Ana Reyes's workspace",
        "short": "AR",
        "plan": "Starter",
        "status": "active",
        "region": "asia-south1",
        "country": "--",
        "ownerEmail": "ana@example.com",
        "seats": 2,
        "members": 1,
        "monthlyCap": _money(DEFAULT_CAP),
        "monthSpent": _money(SPENT),
        "runs30d": 1,
        "successRate": 1.0,
        "openHumanTasks": 1,
        "packsInstalled": 1,
        "connectors": 3,
        "health": "healthy",
        "notes": "",
    }
    assert {k: a[k] for k in expected} == expected
    assert a.get("suspendedReason") is None
    # Nothing of ana's org counts towards ben's: every aggregate is scoped to its own org.
    b = tenants[ben.org_id]
    assert (b["name"], b["ownerEmail"], b["seats"], b["members"]) == (
        "Ben Ito's workspace",
        "ben@example.com",
        1,
        1,
    )
    assert (b["monthSpent"], b["runs30d"], b["successRate"]) == (_money(0), 0, 1.0)
    assert (b["openHumanTasks"], b["packsInstalled"], b["connectors"], b["health"]) == (0, 0, 0, "healthy")


def test_the_success_rate_counts_finished_runs_of_the_last_30_days(live, ana, busy, db):
    _copy_run(db, busy, "run_failed", "FAILED", 0, days_ago=2)
    a = _by_id(live)[ana.org_id]
    assert (a["runs30d"], a["successRate"], a["health"]) == (2, 0.5, "at_risk")


def test_spend_near_the_cap_puts_a_tenant_at_risk(live, ana, busy):
    assert (
        ops_post(live, f"/v1/ops/tenants/{ana.org_id}:setSpendCap", monthlyCapMinor=SPENT).status_code == 200
    )
    assert _by_id(live)[ana.org_id]["health"] == "at_risk"


def test_the_owner_falls_back_to_the_invited_owner_then_to_none(live, ana, db):
    db.execute("UPDATE org_members SET status = 'inactive' WHERE org_id = %s", (ana.org_id,))
    db.execute(
        "INSERT INTO org_members (org_id, email, role, status) VALUES (%s, 'new.owner@example.com', 'owner', "
        "'invited')",
        (ana.org_id,),
    )
    db.commit()
    a = _by_id(live)[ana.org_id]
    assert (a["ownerEmail"], a["seats"], a["members"]) == ("new.owner@example.com", 1, 0)
    db.execute("DELETE FROM org_members WHERE org_id = %s AND status = 'invited'", (ana.org_id,))
    db.commit()
    assert _by_id(live)[ana.org_id]["ownerEmail"] == ""


def test_a_known_plan_maps_onto_the_console_plan(live, ana, db):
    db.execute("UPDATE orgs SET plan = 'pro' WHERE id = %s", (ana.org_id,))
    db.commit()
    assert _by_id(live)[ana.org_id]["plan"] == "Pro"


def test_tenants_filter_by_status_and_query(live, ana, ben):
    assert ops_post(live, f"/v1/ops/tenants/{ben.org_id}:suspend").status_code == 200
    assert [t["id"] for t in _tenants(live, status="suspended")] == [ben.org_id]
    assert [t["id"] for t in _tenants(live, status="active")] == [ana.org_id]
    assert _tenants(live, status="churned") == []
    assert [t["id"] for t in _tenants(live, q="  REYES'S ")] == [ana.org_id]
    assert [t["id"] for t in _tenants(live, q="BEN@example")] == [ben.org_id]
    assert [t["id"] for t in _tenants(live, q=ana.org_id[-6:].upper())] == [ana.org_id]
    assert _tenants(live, q="%") == []  # the query is a plain substring, not a LIKE pattern
    assert _tenants(live, q="nobody") == []
    too_long = live.get("/v1/ops/tenants", params={"q": "x" * 101}, headers=OPS)
    assert too_long.status_code == 422


# --- detail ---------------------------------------------------------------------------------------------


def test_the_detail_lists_the_orgs_own_members_packs_connections_runs_and_spend(live, ana, ben, busy, db):
    _copy_run(db, busy, "run_recent", "COMPLETED", 150, days_ago=3)
    d = _tenant(live, ana.org_id)
    assert d["simulated"] is False
    assert [(m["email"], m["role"], m.get("pending")) for m in d["membersList"]] == [
        ("ana@example.com", "Owner", None),
        ("cy@example.com", "Member", True),
    ]
    assert d["installedPacks"] == [PACK]
    assert d["connectorsList"] == [
        {"app": "googlesheets", "status": "sandbox", "mode": "sandbox"},
        {"app": "shopify", "status": "sandbox", "mode": "sandbox"},
        {"app": "stripe", "status": "sandbox", "mode": "sandbox"},
    ]
    runs = d["recentRuns"]
    assert [r["id"] for r in runs] == [busy, "run_recent", "run_old"]
    assert all(r["real"] and r["tenantId"] == ana.org_id and r["tenantName"] == d["name"] for r in runs)
    assert runs[0]["cost"] == _money(SPENT)

    today = datetime.now(UTC).date()
    days = [(today - timedelta(days=n)).isoformat() for n in range(13, -1, -1)]
    usage = d["usageByDay"]
    assert [p["day"] for p in usage] == days
    spend = {p["day"]: p["amountMinor"] for p in usage if p["amountMinor"]}
    assert spend == {days[-1]: SPENT, days[-4]: 150}  # the run 40 days ago is outside the window

    other = _tenant(live, ben.org_id)
    assert other["simulated"] is False
    assert (other["installedPacks"], other["connectorsList"], other["recentRuns"]) == ([], [], [])
    assert [m["email"] for m in other["membersList"]] == ["ben@example.com"]
    assert all(p["amountMinor"] == 0 for p in other["usageByDay"])


def test_the_detail_says_which_connections_reach_a_real_account(live, ben, db):
    for app, status in (("gmail", "pending"), ("stripe", "connected")):
        db.execute(
            "INSERT INTO connections (org_id, app, status, mode, connected_by, account_id) "
            "VALUES (%s, %s, %s, 'composio', 'uid_ben', 'ca_1')",
            (ben.org_id, app, status),
        )
    db.commit()
    assert _tenant(live, ben.org_id)["connectorsList"] == [
        {"app": "gmail", "status": "pending", "mode": "composio"},
        {"app": "stripe", "status": "connected", "mode": "composio"},
    ]


def test_a_real_connection_without_its_account_needs_signing_in_again(live, ben, db):
    """A connected Composio row without its account id reaches nothing (`routes.route_of`), so the console
    shows it as the web does, needing sign-in, and does not count it as a connector."""
    db.execute(
        "INSERT INTO connections (org_id, app, status, mode, connected_by) "
        "VALUES (%s, 'stripe', 'connected', 'composio', 'uid_ben')",
        (ben.org_id,),
    )
    db.commit()
    assert _tenant(live, ben.org_id)["connectorsList"] == [
        {"app": "stripe", "status": "needs_reauth", "mode": "composio"}
    ]
    assert _by_id(live)[ben.org_id]["connectors"] == 0


def test_only_connections_a_run_could_reach_count_as_connectors(live, ben, db):
    for app, status, mode, account in (
        ("gmail", "connected", "composio", "ca_1"),  # reachable: the org's own account
        ("googlesheets", "sandbox", "sandbox", None),  # reachable: sandbox data
        ("shopify", "connected", "composio", None),  # no account: a run would reach nothing
        ("slack", "connected", "sandbox", None),  # status and mode disagree
        ("stripe", "pending", "composio", "ca_1"),  # still signing in
    ):
        db.execute(
            "INSERT INTO connections (org_id, app, status, mode, connected_by, account_id) "
            "VALUES (%s, %s, %s, %s, 'uid_ben', %s)",
            (ben.org_id, app, status, mode, account),
        )
    db.commit()
    assert _by_id(live)[ben.org_id]["connectors"] == 2
    assert _tenant(live, ben.org_id)["connectors"] == 2


def test_a_disconnected_row_has_no_mode(live, ben, db):
    """A row left behind by a disconnect still names the app, but how it was reached no longer applies."""
    db.execute(
        "INSERT INTO connections (org_id, app, status, mode, connected_by) "
        "VALUES (%s, 'gmail', 'not_connected', 'composio', 'uid_ben')",
        (ben.org_id,),
    )
    db.commit()
    assert _tenant(live, ben.org_id)["connectorsList"] == [{"app": "gmail", "status": "not_connected"}]


def test_an_unknown_tenant_is_not_found(live):
    res = live.get("/v1/ops/tenants/org_missing", headers=OPS)
    assert res.status_code == 404 and res.json()["code"] == "NOT_FOUND"
    for action in (":suspend", ":reactivate"):
        assert ops_post(live, f"/v1/ops/tenants/org_missing{action}").status_code == 404
    cap = ops_post(live, "/v1/ops/tenants/org_missing:setSpendCap", monthlyCapMinor=100)
    assert cap.status_code == 404


# --- actions --------------------------------------------------------------------------------------------


def test_suspending_locks_the_org_out_at_once_and_only_that_org(live, ana, ben, db):
    _ready(ana)  # hired and connected, so only the suspension stops a run
    res = ops_post(live, f"/v1/ops/tenants/{ana.org_id}:suspend")
    assert res.status_code == 200, res.text
    assert (res.json()["status"], res.json()["suspendedReason"]) == ("suspended", REASON)
    assert (
        db.execute("SELECT status FROM orgs WHERE id = %s", (ana.org_id,)).fetchone()["status"] == "suspended"
    )

    locked = ana.get("/v1/me")
    assert locked.status_code == 403 and locked.json()["code"] == "TENANT_SUSPENDED"
    assert ana.get(f"/v1/organizations/{ana.org_id}").status_code == 403
    start = ana.start()
    assert start.status_code == 403 and start.json()["code"] == "TENANT_SUSPENDED"
    runs = db.execute("SELECT count(*) AS n FROM runs WHERE org_id = %s", (ana.org_id,)).fetchone()
    assert runs["n"] == 0
    assert ben.get("/v1/me").status_code == 200  # org B is unaffected
    assert _by_id(live)[ben.org_id]["status"] == "active"

    again = ops_post(live, f"/v1/ops/tenants/{ana.org_id}:suspend")
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_SUSPENDED"


def test_reactivating_lets_the_org_back_in(live, ana, ben):
    not_suspended = ops_post(live, f"/v1/ops/tenants/{ana.org_id}:reactivate")
    assert not_suspended.status_code == 409 and not_suspended.json()["code"] == "NOT_SUSPENDED"
    assert ops_post(live, f"/v1/ops/tenants/{ana.org_id}:suspend").status_code == 200
    res = ops_post(live, f"/v1/ops/tenants/{ana.org_id}:reactivate")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "active" and res.json().get("suspendedReason") is None
    assert ana.get("/v1/me").status_code == 200


def test_a_new_spend_cap_is_what_the_customer_sees(live, ana, ben):
    res = ops_post(live, f"/v1/ops/tenants/{ana.org_id}:setSpendCap", monthlyCapMinor=5000)
    assert res.status_code == 200, res.text
    assert res.json()["monthlyCap"] == _money(5000)
    assert ana.get(f"/v1/organizations/{ana.org_id}").json()["monthlyCap"] == _money(5000)
    assert ben.get(f"/v1/organizations/{ben.org_id}").json()["monthlyCap"] == _money(DEFAULT_CAP)

    same = ops_post(live, f"/v1/ops/tenants/{ana.org_id}:setSpendCap", monthlyCapMinor=5000)
    assert same.status_code == 409 and same.json()["code"] == "NO_CHANGE"
    assert same.json()["detail"] == "The monthly cap is already $50.00."


def test_each_action_writes_one_audit_entry(live, ana, db):
    for path, body in (
        (":suspend", {}),
        (":reactivate", {}),
        (":setSpendCap", {"monthlyCapMinor": 5000}),
    ):
        assert ops_post(live, f"/v1/ops/tenants/{ana.org_id}{path}", **body).status_code == 200
    ops_post(live, f"/v1/ops/tenants/{ana.org_id}:reactivate")  # a 409 writes nothing

    entries = live.get("/v1/ops/audit", params={"targetType": "tenant"}, headers=OPS).json()
    assert [(e["action"], e["summary"]) for e in entries] == [
        ("tenant.set_spend_cap", "Monthly cap $25.00 → $50.00"),
        ("tenant.reactivate", "Status suspended → active"),
        ("tenant.suspend", "Status active → suspended"),
    ]
    assert {(e["targetId"], e["actorEmail"], e["actorRole"], e["reason"]) for e in entries} == {
        (ana.org_id, OPS_EMAIL, "admin", REASON)
    }
    db.commit()
    rows = db.execute("SELECT action, data FROM ops_audit ORDER BY id").fetchall()
    assert [(r["action"], r["data"]["before"], r["data"]["after"]) for r in rows] == [
        ("tenant.suspend", "active", "suspended"),
        ("tenant.reactivate", "suspended", "active"),
        ("tenant.set_spend_cap", DEFAULT_CAP, 5000),
    ]


def test_tenants_are_created_at_sign_up_and_plans_are_not_changed_live(live, ana, db):
    body = {
        "name": "Acme",
        "short": "AC",
        "plan": "Pro",
        "region": "asia-south1",
        "country": "IN",
        "ownerEmail": "owner@acme.example",
        "monthlyCapMinor": 1000,
        "reason": REASON,
    }
    created = live.post("/v1/ops/tenants", json=body, headers=OPS)
    assert created.status_code == 409 and created.json()["code"] == "NOT_AVAILABLE_LIVE"
    plan = ops_post(live, f"/v1/ops/tenants/{ana.org_id}:setPlan", plan="Pro")
    assert plan.status_code == 409 and plan.json()["code"] == "NOT_AVAILABLE_LIVE"
    db.commit()
    assert db.execute("SELECT count(*) AS n FROM orgs").fetchone()["n"] == 1
    assert db.execute("SELECT count(*) AS n FROM ops_audit").fetchone()["n"] == 0


def test_the_demo_workspace_keeps_its_simulated_fixtures(client):
    tenants = client.get("/v1/ops/tenants").json()
    assert len(tenants) > 2
    assert client.get(f"/v1/ops/tenants/{tenants[0]['id']}").json()["simulated"] is True
