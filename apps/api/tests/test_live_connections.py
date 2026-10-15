"""Live workspace app connections, each with its own mode: sandbox data or the org's own account through
Composio (mocked in these tests: no network). NM_CONNECTOR_MODE does not decide for the live workspace."""

import pytest
from psycopg.types.json import Jsonb

from app import live_connections
from app.runtime import drivers
from tests.fake_composio import LINK_URL, composio  # noqa: F401  (composio is a fixture)
from tests.test_live_catalog import (  # noqa: F401  (live, starts, ana, ben are fixtures)
    INPUT,
    PACK,
    PACK_NAME,
    SHEET,
    _ready,
    _rows,
    ana,
    ben,
    live,
    starts,
)

REAL_SHEET = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"


def _row(db, org_id: str, app: str, status: str, mode: str, account: str | None = None, grants="[]") -> None:
    db.execute(
        "INSERT INTO connections (org_id, app, status, mode, grants, connected_by, account_id) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, 'uid_ana', %s) ON CONFLICT (org_id, app) DO UPDATE SET "
        "status = EXCLUDED.status, mode = EXCLUDED.mode, grants = EXCLUDED.grants, "
        "account_id = EXCLUDED.account_id",
        (org_id, app, status, mode, grants, account),
    )
    db.commit()


def _no_composio_check(monkeypatch) -> None:
    def refuse(self, toolkit):
        raise AssertionError("the live workspace must not ask Composio which mode to use")

    monkeypatch.setattr(drivers.ComposioDriver, "is_connected", refuse)


@pytest.mark.parametrize("mode", ["sandbox", "live", "auto"])
def test_the_connector_mode_does_not_decide_for_the_live_workspace(ana, starts, monkeypatch, mode):  # noqa: F811
    monkeypatch.setenv("NM_CONNECTOR_MODE", mode)
    _no_composio_check(monkeypatch)
    _ready(ana)  # sandbox connections, whatever the mode
    assert ana.start().status_code == 202


@pytest.mark.parametrize("status", ["pending", "needs_reauth", "not_connected"])
def test_an_unfinished_real_connection_keeps_the_gate_closed(ana, starts, db, status):  # noqa: F811
    _ready(ana)
    _row(db, ana.org_id, "stripe", status, "composio", "ca_1")
    res = ana.start()
    assert res.status_code == 409 and res.json()["code"] == "APPS_NOT_CONNECTED"
    assert res.json()["detail"] == f"Connect Stripe before starting a run of {PACK_NAME}."


def test_a_connected_real_account_opens_the_gate(ana, starts, db):  # noqa: F811
    _ready(ana)
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1")
    assert ana.start().status_code == 202


UNROUTABLE = [  # rows a run would reach nothing through (`routes.route_of`)
    ("connected", "composio", None),  # no account id
    ("sandbox", "composio", "ca_1"),  # status and mode disagree
    ("connected", "sandbox", None),
]


@pytest.mark.parametrize(("status", "mode", "account"), UNROUTABLE)
def test_a_row_that_would_not_route_keeps_the_gate_closed_and_asks_to_sign_in_again(
    ana,  # noqa: F811
    starts,  # noqa: F811
    db,
    status,
    mode,
    account,
):
    _ready(ana)
    _row(db, ana.org_id, "stripe", status, mode, account)  # the worker would reach nothing
    res = ana.start()
    assert res.status_code == 409 and res.json()["detail"].startswith("Connect Stripe before")
    stripe = next(c for c in ana.get("/v1/connections").json() if c["key"] == "stripe")
    assert (stripe["status"], stripe["mode"]) == ("needs_reauth", mode)
    pack = ana.get(f"/v1/workflow-packs/{PACK}").json()
    assert {c["app"]: c["mocked"] for c in pack["connectors"]}["Stripe"] is True


def test_marketplace_labels_follow_each_connection(ana, db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NM_CONNECTOR_MODE", "live")  # ignored by the live workspace
    _no_composio_check(monkeypatch)
    ana.hire()
    ana.connect("shopify")
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1")
    pack = ana.get(f"/v1/workflow-packs/{PACK}").json()
    assert {c["app"]: c["mocked"] for c in pack["connectors"]} == {
        "Shopify": True,
        "Stripe": False,
        "Google Sheets": True,
    }
    listed = next(p for p in ana.get("/v1/workflow-packs").json() if p["slug"] == PACK)
    assert {c["app"]: c["mocked"] for c in listed["connectors"]}["Stripe"] is False


def test_each_listed_connection_shows_its_own_mode(ana, db):  # noqa: F811
    ana.hire()
    ana.connect("shopify")
    _row(db, ana.org_id, "stripe", "pending", "composio", "ca_1")
    listed = {c["key"]: c for c in ana.get("/v1/connections").json()}
    shopify, stripe, sheets = listed["shopify"], listed["stripe"], listed["googlesheets"]
    assert (shopify["status"], shopify["mode"], shopify["provider"]) == ("sandbox", "sandbox", "Mock")
    assert (stripe["status"], stripe["mode"], stripe["provider"], stripe["account"]) == (
        "pending",
        "composio",
        "Composio",
        "",
    )
    assert sheets["status"] == "not_connected" and "mode" not in sheets


def test_a_pending_app_no_pack_uses_is_still_listed(ana, db):  # noqa: F811
    _row(db, ana.org_id, "gmail", "pending", "composio", "ca_1")
    assert [(c["key"], c["status"]) for c in ana.get("/v1/connections").json()] == [("gmail", "pending")]


# --- the sheet a run writes to on the org's own Google Sheets account ------------------------------------


def test_a_real_sheets_account_needs_a_real_sheet_id(ana, starts, db):  # noqa: F811
    _ready(ana)
    _row(db, ana.org_id, "googlesheets", "connected", "composio", "ca_1")
    for given in (INPUT, {**INPUT, "spreadsheet_id": SHEET}):  # left to its default, or the default given
        res = ana.start(input=given)
        assert res.status_code == 422 and res.json()["code"] == "INVALID_INPUT", res.text
        [issue] = res.json()["errors"]
        assert (issue["kind"], issue["key"], issue["path"]) == ("input", PACK, "spreadsheet_id")
        assert "sheet's URL" in issue["message"]
        assert res.json()["detail"] == f"The input is not valid. Spreadsheet ID: {issue['message']}"
    assert starts.calls == []
    assert ana.start(input={**INPUT, "spreadsheet_id": REAL_SHEET}).status_code == 202
    assert starts.calls[-1][2]["spreadsheet_id"] == REAL_SHEET


def test_the_sandbox_sheet_is_fine_for_sandbox_sheets_data(ana, starts, db):  # noqa: F811
    _ready(ana)
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1")  # another app's real account
    assert ana.start().status_code == 202
    assert starts.calls[-1][2]["spreadsheet_id"] == SHEET
    assert _rows(db, "SELECT count(*) AS n FROM runs")[0]["n"] == 1


# --- connecting the org's own account through a Composio sign-in link -----------------------------------


def _live_connect(user, app: str):
    return user.post(f"/v1/connections/{app}:connect", json={"mode": "live"})


def test_connecting_live_starts_a_sign_in_for_the_orgs_composio_user(ana, composio, db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NM_WEB_ORIGIN", "https://app.example.com/")
    ana.hire()
    res = _live_connect(ana, "Stripe")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["key"], body["status"], body["mode"], body["provider"]) == (
        "stripe",
        "pending",
        "composio",
        "Composio",
    )
    assert body["redirectUrl"] == LINK_URL and body["grants"] == []
    back = "https://app.example.com/app/connections?connected=stripe"
    assert composio.connected_accounts.linked == [(f"org:{ana.org_id}", "ac_new", back)]
    [row] = _rows(
        db, "SELECT status, mode, account_id, connected_by FROM connections WHERE org_id = %s", ana.org_id
    )
    assert row == {"status": "pending", "mode": "composio", "account_id": "ca_new", "connected_by": "uid_ana"}


def test_live_connect_falls_back_to_the_first_allowed_origin(ana, composio, monkeypatch):  # noqa: F811
    monkeypatch.delenv("NM_WEB_ORIGIN", raising=False)
    monkeypatch.setenv("ALLOWED_ORIGINS", " , / , https://web.example.com/ ,https://ops.example.com")
    _live_connect(ana, "stripe")
    back = "https://web.example.com/app/connections?connected=stripe"
    assert composio.connected_accounts.linked[0][2] == back


def test_live_connect_without_a_composio_key_is_a_409(ana, db, monkeypatch):  # noqa: F811
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    res = _live_connect(ana, "stripe")
    assert res.status_code == 409 and res.json()["code"] == "LIVE_CONNECT_UNAVAILABLE"
    detail = "Real accounts cannot be connected in this workspace yet. Use simulated data instead."
    assert res.json()["detail"] == detail
    assert _rows(db, "SELECT app FROM connections") == []


def test_live_connect_of_a_connector_without_a_toolkit_is_a_409(ana, composio, monkeypatch):  # noqa: F811
    real = live_connections.latest_bodies

    def without_toolkit(kind):
        bodies = real(kind)
        if kind != "connector":
            return bodies
        return {k: {f: v for f, v in b.items() if f != "toolkit"} for k, b in bodies.items()}

    monkeypatch.setattr(live_connections, "latest_bodies", without_toolkit)
    res = _live_connect(ana, "stripe")
    assert res.status_code == 409 and res.json()["code"] == "NO_LIVE_TOOLKIT"
    assert (
        res.json()["detail"]
        == "Stripe cannot be connected to a real account yet. Use simulated data instead."
    )
    assert composio.connected_accounts.linked == []


def test_a_composio_failure_is_a_503_and_stores_nothing(ana, composio, db):  # noqa: F811
    composio.connected_accounts.fail_link = RuntimeError("boom")
    res = _live_connect(ana, "stripe")
    assert res.status_code == 503 and res.json()["code"] == "CONNECTION_SERVICE_UNAVAILABLE"
    assert _rows(db, "SELECT app FROM connections") == []


def test_reconnecting_retires_the_account_the_row_held(ana, composio, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "needs_reauth", "composio", "ca_expired")
    assert _live_connect(ana, "stripe").json()["status"] == "pending"
    assert composio.connected_accounts.deleted == [("ca_expired", True)]
    [row] = _rows(db, "SELECT account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row["account_id"] == "ca_new"


def test_switching_to_simulated_data_retires_a_held_account(ana, composio, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "not_connected", "composio", "ca_left")
    assert ana.connect("stripe").json()["status"] == "sandbox"
    assert composio.connected_accounts.deleted == [("ca_left", True)]
    [row] = _rows(db, "SELECT mode, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"mode": "sandbox", "account_id": None}


def test_a_held_account_that_cannot_be_removed_is_a_503_and_nothing_changes(ana, composio, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "needs_reauth", "composio", "ca_expired")
    composio.connected_accounts.fail_delete = RuntimeError("down")
    res = _live_connect(ana, "stripe")
    assert res.status_code == 503 and res.json()["code"] == "CONNECTION_SERVICE_UNAVAILABLE"
    assert composio.connected_accounts.linked == []
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "needs_reauth", "account_id": "ca_expired"}


def test_the_held_account_is_removed_before_the_new_link_so_it_is_never_adopted(ana, composio, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "needs_reauth", "composio", "ca_expired")
    composio.connected_accounts.active = ["ca_expired"]  # Composio still calls it ACTIVE
    composio.connected_accounts.held = ["ca_expired"]
    res = _live_connect(ana, "stripe")
    assert res.status_code == 200 and res.json()["redirectUrl"] == LINK_URL
    assert composio.connected_accounts.deleted == [("ca_expired", True)]
    assert len(composio.connected_accounts.linked) == 1  # a new sign-in, not the old account adopted
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "pending", "account_id": "ca_new"}


def test_a_live_connect_sweeps_the_orgs_other_accounts_for_the_app(ana, composio, db):  # noqa: F811
    composio.connected_accounts.held = ["ca_lost"]  # left behind by a removal that failed earlier
    res = _live_connect(ana, "stripe")
    assert res.status_code == 200
    assert composio.connected_accounts.deleted == [("ca_lost", True)]
    assert composio.connected_accounts.held == ["ca_new"]
    assert composio.connected_accounts.queries[-1] == {
        "user_ids": [f"org:{ana.org_id}"],
        "toolkit_slugs": ["stripe"],
        "statuses": ["ACTIVE", "EXPIRED", "INACTIVE", "FAILED", "REVOKED"],
        "limit": 50,
    }
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "pending", "account_id": "ca_new"}


def test_an_unfinished_sign_in_no_row_holds_survives_the_sweep(ana, composio, db):  # noqa: F811
    """Another connect's link, made before its row is stored: it holds no tokens (Composio expires it), so
    the sweep never asks for INITIATED or INITIALIZING accounts and cannot remove it."""
    composio.connected_accounts.held = ["ca_half", "ca_lost"]
    composio.connected_accounts.statuses["ca_half"] = "INITIATED"
    assert _live_connect(ana, "stripe").status_code == 200
    assert composio.connected_accounts.deleted == [("ca_lost", True)]
    assert composio.connected_accounts.held == ["ca_half", "ca_new"]


def test_the_sweep_keeps_the_account_the_row_holds_by_then(ana, composio, db, monkeypatch):  # noqa: F811
    """A second connect stored its own account between this one's upsert and its sweep: that account is the
    row's now, so the sweep keeps it (and the one just started), removing only what no row holds."""
    composio.connected_accounts.held = ["ca_lost"]
    real_lock, locks = live_connections._lock, []

    def lock(conn, org_id, key):
        locks.append(key)
        if len(locks) == 3:  # the sweep's lock: the read, the upsert, then this
            db.execute(
                "UPDATE connections SET account_id = 'ca_B' WHERE org_id = %s AND app = %s", (org_id, key)
            )
            db.commit()
            composio.connected_accounts.held.append("ca_B")
        real_lock(conn, org_id, key)

    monkeypatch.setattr(live_connections, "_lock", lock)
    assert _live_connect(ana, "stripe").status_code == 200
    assert len(locks) == 3
    assert composio.connected_accounts.deleted == [("ca_lost", True)]
    assert sorted(composio.connected_accounts.held) == ["ca_B", "ca_new"]


def test_the_sweep_keeps_an_account_another_connection_holds_on_the_toolkit(ana, composio, db):  # noqa: F811
    _row(db, ana.org_id, "shopify", "connected", "composio", "ca_shop")  # another connector, same toolkit
    composio.connected_accounts.held = ["ca_shop", "ca_lost"]
    assert _live_connect(ana, "stripe").status_code == 200
    assert composio.connected_accounts.deleted == [("ca_lost", True)]
    assert composio.connected_accounts.held == ["ca_shop", "ca_new"]
    rows = _rows(db, "SELECT app, account_id FROM connections WHERE org_id = %s ORDER BY app", ana.org_id)
    assert rows == [{"app": "shopify", "account_id": "ca_shop"}, {"app": "stripe", "account_id": "ca_new"}]


def test_a_sweep_that_fails_keeps_the_new_connection(ana, composio, db):  # noqa: F811
    composio.connected_accounts.held = ["ca_lost"]
    composio.connected_accounts.fail_list = RuntimeError("down")
    assert _live_connect(ana, "stripe").status_code == 200
    assert composio.connected_accounts.deleted == []
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "pending", "account_id": "ca_new"}


def test_a_retire_whose_bookkeeping_fails_does_not_fail_the_request(composio, monkeypatch):  # noqa: F811
    def broken():
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr(live_connections.db, "connect", broken)
    live_connections._retire("org_x", "stripe", "ca_gone")  # must not raise
    assert composio.connected_accounts.deleted == [("ca_gone", True)]


def test_a_connected_real_account_is_returned_as_it_is(ana, composio, db):  # noqa: F811
    grants = '[{"install": "Pack", "capability": "stripe.read", "access": "read"}]'
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1", grants=grants)
    res = _live_connect(ana, "stripe")
    assert res.status_code == 200, res.text
    assert (res.json()["status"], res.json()["mode"]) == ("connected", "composio")
    assert "redirectUrl" not in res.json() and len(res.json()["grants"]) == 1
    assert composio.connected_accounts.linked == [] and composio.connected_accounts.deleted == []
    [row] = _rows(db, "SELECT status, account_id, grants FROM connections WHERE org_id = %s", ana.org_id)
    assert (row["status"], row["account_id"], len(row["grants"])) == ("connected", "ca_1", 1)


def test_a_connected_row_without_its_account_can_be_connected_again(ana, composio, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "connected", "composio", None)  # listed as needs_reauth
    res = _live_connect(ana, "stripe")
    assert res.status_code == 200 and res.json()["status"] == "pending"
    assert len(composio.connected_accounts.linked) == 1 and composio.connected_accounts.deleted == []


def test_an_explicit_sandbox_body_connects_to_sandbox_data(ana):  # noqa: F811
    res = ana.post("/v1/connections/shopify:connect", json={"mode": "sandbox"})
    assert res.status_code == 200 and res.json()["status"] == "sandbox" and "redirectUrl" not in res.json()
    assert ana.post("/v1/connections/shopify:connect", json={"mode": "other"}).status_code == 422


# --- a revoked grant stays revoked --------------------------------------------------------------------------

REVOKED = {"install": PACK_NAME, "capability": "payments.read"}


def _revoke_stripe_read(user) -> None:
    query = {"app": "stripe", "install": PACK_NAME, "capability": "payments.read"}
    assert user.delete("/v1/grants", params=query).status_code == 204


def test_connecting_sandbox_again_does_not_restore_a_revoked_grant(ana, db):  # noqa: F811
    ana.hire()
    assert ana.connect("stripe").json()["grants"] != []
    _revoke_stripe_read(ana)
    assert ana.connect("stripe").json()["grants"] == []
    [row] = _rows(db, "SELECT grants, revoked_grants FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"grants": [], "revoked_grants": [REVOKED]}


def test_a_revocation_survives_switching_to_a_real_account(ana, composio, db):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    _revoke_stripe_read(ana)
    assert _live_connect(ana, "stripe").json()["grants"] == []
    [row] = _rows(db, "SELECT status, grants, revoked_grants FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "pending", "grants": [], "revoked_grants": [REVOKED]}
    connectors, contracts = (
        live_connections.latest_bodies("connector"),
        live_connections.latest_bodies("contract", ana.org_id),
    )
    bodies = live_connections._pack_bodies(ana.org_id)
    # what Task 10's sync grants once the account is ACTIVE: the pack's grants minus the revoked one
    assert live_connections.grants_for(db, connectors, bodies, contracts, ana.org_id, "stripe") == []
    assert live_connections.grants_for(db, connectors, bodies, contracts, ana.org_id, "shopify") != []


def test_revoking_the_same_grant_twice_records_it_once(ana, db):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    _revoke_stripe_read(ana)
    ana.connect("shopify")  # another app's row is untouched
    [stripe] = _rows(
        db, "SELECT revoked_grants FROM connections WHERE org_id = %s AND app = 'stripe'", ana.org_id
    )
    [shopify] = _rows(
        db, "SELECT revoked_grants FROM connections WHERE org_id = %s AND app = 'shopify'", ana.org_id
    )
    assert stripe["revoked_grants"] == [REVOKED] and shopify["revoked_grants"] == []


# --- finishing a real connection: sync checks the account after the person comes back -----------------------

STRIPE_GRANT = [{"install": PACK_NAME, "capability": "payments.read", "access": "read"}]


def _sync(user, app: str = "stripe"):
    return user.post(f"/v1/connections/{app}:sync")


def test_an_active_account_connects_with_the_packs_grants_and_opens_the_gate(ana, starts, composio, db):  # noqa: F811
    _ready(ana)
    _live_connect(ana, "stripe")
    composio.connected_accounts.statuses["ca_new"] = "ACTIVE"
    synced = _sync(ana).json()
    assert (synced["status"], synced["mode"], synced["grants"]) == ("connected", "composio", STRIPE_GRANT)
    assert composio.connected_accounts.got == ["ca_new"]
    assert ana.start().status_code == 202


def test_a_sign_in_in_progress_stays_pending(ana, composio):  # noqa: F811
    _live_connect(ana, "stripe")  # the fake's new link is INITIATED
    assert _sync(ana).json()["status"] == "pending"
    composio.connected_accounts.statuses["ca_new"] = "INITIALIZING"
    assert _sync(ana).json()["status"] == "pending"


@pytest.mark.parametrize("status", ["FAILED", "EXPIRED", "INACTIVE", "REVOKED", "GONE"])
def test_a_sign_in_that_did_not_finish_is_not_connected_and_its_account_removed(ana, composio, db, status):  # noqa: F811
    """The person never disconnected, so the answer and the list carry no notice: the account that may hold
    tokens is removed at Composio and forgotten; one Composio no longer has is forgotten at once."""
    ana.hire()  # so the app is listed while not connected
    _live_connect(ana, "stripe")
    if status == "GONE":  # Composio has no such account any more: the fake answers 404
        composio.connected_accounts.forget("ca_new")
    else:
        composio.connected_accounts.statuses["ca_new"] = status
    synced = _sync(ana).json()
    assert synced["status"] == "not_connected" and synced["grants"] == [] and "notice" not in synced
    assert "notice" not in _stripe(ana)
    assert composio.connected_accounts.deleted == ([] if status == "GONE" else [("ca_new", True)])
    [row] = _rows(db, "SELECT status, grants, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "not_connected", "grants": [], "account_id": None}


def test_a_failed_sign_in_whose_removal_fails_keeps_the_account_with_a_notice(ana, composio, db):  # noqa: F811
    ana.hire()
    _live_connect(ana, "stripe")
    composio.connected_accounts.statuses["ca_new"] = "FAILED"
    composio.connected_accounts.fail_delete = RuntimeError("down")
    synced = _sync(ana).json()
    assert (synced["status"], synced["notice"]) == ("not_connected", "sign_in_not_removed")
    assert _stripe(ana)["notice"] == "sign_in_not_removed"  # truthful now: the account is still there
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {
        "status": "not_connected",
        "account_id": "ca_new",
    }  # the next connect or disconnect retries
    composio.connected_accounts.fail_delete = None
    assert "notice" not in _disconnect(ana).json()
    assert composio.connected_accounts.deleted == [("ca_new", True)]


def test_a_connected_account_that_expired_needs_sign_in_again_and_keeps_its_grants(ana, composio, db):  # noqa: F811
    grants = '[{"install": "X", "capability": "payments.read", "access": "read"}]'
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1", grants=grants)
    composio.connected_accounts.statuses["ca_1"] = "EXPIRED"
    synced = _sync(ana).json()
    assert synced["status"] == "needs_reauth" and len(synced["grants"]) == 1
    composio.connected_accounts.statuses["ca_1"] = "ACTIVE"
    again = _sync(ana).json()
    assert again["status"] == "connected" and len(again["grants"]) == 1


def test_syncing_a_connected_account_never_restores_a_revoked_grant(ana, composio, db):  # noqa: F811
    ana.hire()
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1")  # grants [] after a revoke
    composio.connected_accounts.statuses["ca_1"] = "ACTIVE"
    assert _sync(ana).json()["grants"] == []


def test_a_sync_that_connects_does_not_restore_a_revoked_grant(ana, composio, db):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    _revoke_stripe_read(ana)
    _live_connect(ana, "stripe")
    composio.connected_accounts.statuses["ca_new"] = "ACTIVE"
    synced = _sync(ana).json()
    assert (synced["status"], synced["grants"]) == ("connected", [])
    [row] = _rows(db, "SELECT grants, revoked_grants FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"grants": [], "revoked_grants": [REVOKED]}


def test_sandbox_and_unconnected_rows_are_returned_without_asking_composio(ana, composio, db):  # noqa: F811
    ana.hire()
    ana.connect("shopify")
    _row(db, ana.org_id, "googlesheets", "not_connected", "composio", "ca_left")
    assert _sync(ana, "shopify").json()["status"] == "sandbox"
    assert _sync(ana, "stripe").json()["status"] == "not_connected"
    assert _sync(ana, "googlesheets").json()["status"] == "not_connected"
    assert composio.connected_accounts.got == []


def test_sync_when_composio_is_down_is_a_503(ana, composio, db):  # noqa: F811
    _live_connect(ana, "stripe")
    composio.connected_accounts.fail_get = RuntimeError("down")
    res = _sync(ana)
    assert res.status_code == 503 and res.json()["code"] == "CONNECTION_SERVICE_UNAVAILABLE"
    [row] = _rows(db, "SELECT status FROM connections WHERE org_id = %s", ana.org_id)
    assert row["status"] == "pending"


def test_another_org_cannot_sync_an_orgs_connection(ana, ben, composio, db):  # noqa: F811
    _live_connect(ana, "stripe")
    composio.connected_accounts.statuses["ca_new"] = "ACTIVE"
    assert _sync(ben).json()["status"] == "not_connected"
    [row] = _rows(db, "SELECT status FROM connections WHERE org_id = %s", ana.org_id)
    assert row["status"] == "pending"


def test_a_sync_never_overwrites_a_newer_connect(ana, composio, db, monkeypatch):  # noqa: F811
    """A second connect stored its own link while this sync waited for Composio: the row is that connect's
    now (another account), so the answer about the old account changes nothing."""
    _live_connect(ana, "stripe")

    def active_but_relinked(account_id):
        _row(db, ana.org_id, "stripe", "pending", "composio", "ca_B")
        return "ACTIVE"

    monkeypatch.setattr(live_connections.composio_accounts, "status", active_but_relinked)
    synced = _sync(ana).json()
    assert (synced["status"], synced["grants"]) == ("pending", [])
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "pending", "account_id": "ca_B"}


def test_a_sync_that_lost_to_another_never_removes_the_account_the_row_routes_through(  # noqa: F811
    ana,  # noqa: F811
    composio,  # noqa: F811
    db,
    monkeypatch,
):
    """Two syncs of the same pending row (the callback page in two tabs): the other saw ACTIVE and connected
    the row while this one waited for FAILED. This one's update matches nothing, so it must not remove the
    account the connected row now routes through."""
    _live_connect(ana, "stripe")

    def failed_but_connected_meanwhile(account_id):
        _row(db, ana.org_id, "stripe", "connected", "composio", "ca_new")
        return "FAILED"

    monkeypatch.setattr(live_connections.composio_accounts, "status", failed_but_connected_meanwhile)
    assert _sync(ana).json()["status"] == "connected"
    assert composio.connected_accounts.deleted == []
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "connected", "account_id": "ca_new"}


def test_a_sync_never_connects_a_row_switched_to_simulated_data_meanwhile(ana, composio, db, monkeypatch):  # noqa: F811
    """The person switched the app to simulated data while this sync waited for Composio; the row still
    holds the account until its retirement is bookkept. It stays a sandbox row."""
    _live_connect(ana, "stripe")

    def active_but_sandbox(account_id):
        _row(db, ana.org_id, "stripe", "sandbox", "sandbox", "ca_new")
        return "ACTIVE"

    monkeypatch.setattr(live_connections.composio_accounts, "status", active_but_sandbox)
    synced = _sync(ana).json()
    assert (synced["status"], synced["mode"]) == ("sandbox", "sandbox")
    [row] = _rows(db, "SELECT status, mode FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "sandbox", "mode": "sandbox"}


def test_the_demo_workspace_has_nothing_to_sync(client):
    res = client.post("/v1/connections/Gmail:sync")
    assert res.status_code == 409 and res.json()["code"] == "CONFLICT"


def test_a_sync_never_connects_a_row_disconnected_meanwhile(ana, composio, db, monkeypatch):  # noqa: F811
    """The person disconnected the app while this sync waited for Composio: the row's status changed under
    the same account and mode, so the update (matched on the status read too) changes nothing."""
    _live_connect(ana, "stripe")

    def active_but_disconnected(account_id):
        db.execute(
            "UPDATE connections SET status = 'not_connected', grants = '[]'::jsonb WHERE org_id = %s",
            (ana.org_id,),
        )
        db.commit()
        return "ACTIVE"

    monkeypatch.setattr(live_connections.composio_accounts, "status", active_but_disconnected)
    synced = _sync(ana).json()
    assert (synced["status"], synced["grants"]) == ("not_connected", [])
    [row] = _rows(
        db, "SELECT status, grants, mode, account_id FROM connections WHERE org_id = %s", ana.org_id
    )
    assert row == {"status": "not_connected", "grants": [], "mode": "composio", "account_id": "ca_new"}


def test_sync_without_a_composio_key_is_a_409(ana, db, monkeypatch):  # noqa: F811
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    _row(db, ana.org_id, "stripe", "pending", "composio", "ca_1")
    res = _sync(ana)
    assert res.status_code == 409 and res.json()["code"] == "LIVE_CONNECT_UNAVAILABLE"
    [row] = _rows(db, "SELECT status FROM connections WHERE org_id = %s", ana.org_id)
    assert row["status"] == "pending"


def _take_the_lock(db, org_id: str, key: str) -> None:
    """Take the (org, app) lock on the test's own connection, failing fast (not hanging) when the request
    still holds it on a pooled connection while it waits for Composio."""
    db.commit()
    db.execute("SET LOCAL lock_timeout = '2s'")
    live_connections._lock(db, org_id, key)
    db.commit()  # releases it


def test_sync_releases_the_lock_while_composio_answers(ana, composio, db, monkeypatch):  # noqa: F811
    _live_connect(ana, "stripe")

    def active_once_free(account_id):
        _take_the_lock(db, ana.org_id, "stripe")  # would time out if sync held the lock here
        return "ACTIVE"

    monkeypatch.setattr(live_connections.composio_accounts, "status", active_once_free)
    assert _sync(ana).json()["status"] == "connected"


# --- disconnecting: the row changes first, then the org's own account is removed at Composio ---------------


def _disconnect(user, app: str = "stripe"):
    return user.post(f"/v1/connections/{app}:disconnect")


def test_disconnecting_a_real_account_removes_it_at_composio(ana, composio, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1")
    gone = _disconnect(ana).json()
    assert gone["status"] == "not_connected" and gone["grants"] == [] and "notice" not in gone
    assert composio.connected_accounts.deleted == [("ca_1", True)]
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "not_connected", "account_id": None}


def test_a_removal_that_fails_is_reported_and_retried(ana, composio, db):  # noqa: F811
    ana.hire()  # so the app is listed while disconnected
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1")
    composio.connected_accounts.fail_delete = RuntimeError("down")
    gone = _disconnect(ana).json()
    assert gone["status"] == "not_connected" and gone["notice"] == "sign_in_not_removed"
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "not_connected", "account_id": "ca_1"}  # runs already cannot use it
    assert _stripe(ana)["notice"] == "sign_in_not_removed"  # the notice survives a reload
    composio.connected_accounts.fail_delete = None
    assert "notice" not in _disconnect(ana).json()
    assert composio.connected_accounts.deleted == [("ca_1", True)]
    assert "notice" not in _stripe(ana)


def test_without_a_key_the_disconnect_still_happens_with_a_notice(ana, db, monkeypatch):  # noqa: F811
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    _row(db, ana.org_id, "stripe", "pending", "composio", "ca_1")
    gone = _disconnect(ana).json()
    assert gone["status"] == "not_connected" and gone["notice"] == "sign_in_not_removed"
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "not_connected", "account_id": "ca_1"}  # kept for the retry


def test_disconnecting_simulated_data_never_calls_composio(ana, composio):  # noqa: F811
    ana.connect("shopify")
    assert _disconnect(ana, "shopify").json()["status"] == "not_connected"
    assert composio.connected_accounts.deleted == []


def test_disconnecting_retries_an_account_a_sandbox_row_still_holds(ana, composio, db):  # noqa: F811
    """A switch to simulated data whose retirement failed left the account on the row: a disconnect retries
    it, whatever the row's mode."""
    _row(db, ana.org_id, "stripe", "sandbox", "sandbox", "ca_left")
    assert "notice" not in _disconnect(ana).json()
    assert composio.connected_accounts.deleted == [("ca_left", True)]
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "not_connected", "account_id": None}


def test_disconnecting_releases_the_lock_while_composio_removes_the_account(  # noqa: F811
    ana,  # noqa: F811
    composio,  # noqa: F811
    db,
    monkeypatch,
):
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1")

    def remove_once_free(account_id):
        _take_the_lock(db, ana.org_id, "stripe")  # would time out if disconnect held the lock here
        composio.connected_accounts.delete(account_id, revoke_on_delete=True)

    monkeypatch.setattr(live_connections.composio_accounts, "remove", remove_once_free)
    assert "notice" not in _disconnect(ana).json()
    [row] = _rows(db, "SELECT account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row["account_id"] is None


def test_a_disconnect_never_forgets_an_account_a_newer_connect_stored(ana, composio, db, monkeypatch):  # noqa: F811
    """A live connect stored its own link while this disconnect waited for Composio: the row holds another
    account now, which stays."""
    _row(db, ana.org_id, "stripe", "connected", "composio", "ca_1")

    def remove_but_relinked(account_id):
        _row(db, ana.org_id, "stripe", "pending", "composio", "ca_B")
        composio.connected_accounts.delete(account_id, revoke_on_delete=True)

    monkeypatch.setattr(live_connections.composio_accounts, "remove", remove_but_relinked)
    assert _disconnect(ana).json()["status"] == "not_connected"
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "pending", "account_id": "ca_B"}


# --- allowing a revoked grant again ----------------------------------------------------------------------

GRANT_QUERY = {"app": "stripe", "install": PACK_NAME, "capability": "payments.read"}


def _allow_again(user, **query):
    return user.post("/v1/grants", params={**GRANT_QUERY, **query})


def test_allowing_a_revoked_grant_again_restores_it(ana, db):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    _revoke_stripe_read(ana)
    res = _allow_again(ana, app="Stripe")  # by app name too
    assert res.status_code == 200, res.text
    assert (res.json()["key"], res.json()["status"]) == ("stripe", "sandbox")
    assert res.json()["grants"] == STRIPE_GRANT
    [row] = _rows(db, "SELECT grants, revoked_grants FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"grants": STRIPE_GRANT, "revoked_grants": []}
    assert ana.connect("stripe").json()["grants"] == STRIPE_GRANT  # and recomputing keeps it


def test_allowing_again_only_forgets_the_revocation_when_no_added_pack_uses_the_capability(ana, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "sandbox", "sandbox")
    db.execute(
        "UPDATE connections SET revoked_grants = %s WHERE org_id = %s",
        (Jsonb([{"install": PACK_NAME, "capability": "payments.read"}]), ana.org_id),
    )
    db.commit()
    res = _allow_again(ana)
    assert res.status_code == 200 and res.json()["grants"] == []
    [row] = _rows(db, "SELECT grants, revoked_grants FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"grants": [], "revoked_grants": []}


def test_allowing_again_fails_closed_when_the_packs_contract_cannot_be_found(ana, db, monkeypatch):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    _revoke_stripe_read(ana)
    real = live_connections._definitions

    def without_contracts(conn, org_id):
        packs, _ = real(conn, org_id)
        return packs, {}

    monkeypatch.setattr(live_connections, "_definitions", without_contracts)
    assert _allow_again(ana).json()["grants"] == []
    [row] = _rows(db, "SELECT grants, revoked_grants FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"grants": [], "revoked_grants": []}


def test_allowing_again_a_grant_that_was_not_revoked_is_a_404(ana, ben, db):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    assert _allow_again(ana).status_code == 404  # held, never revoked
    _revoke_stripe_read(ana)
    assert _allow_again(ben).status_code == 404  # another org's connection looks like a missing one
    assert _allow_again(ana, app="nope").status_code == 404
    assert _allow_again(ana).status_code == 200
    assert _allow_again(ana).status_code == 404  # allowed again already
    [row] = _rows(db, "SELECT grants, revoked_grants FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"grants": STRIPE_GRANT, "revoked_grants": []}


def test_allowing_again_on_a_pending_real_account_leaves_the_grant_to_the_sync(ana, composio, db):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    _revoke_stripe_read(ana)
    _live_connect(ana, "stripe")
    res = _allow_again(ana)
    assert res.status_code == 200 and (res.json()["status"], res.json()["grants"]) == ("pending", [])
    composio.connected_accounts.statuses["ca_new"] = "ACTIVE"
    assert _sync(ana).json()["grants"] == STRIPE_GRANT


def test_the_demo_workspace_cannot_allow_a_grant_again(client):
    res = client.post("/v1/grants", params=GRANT_QUERY)
    assert res.status_code == 409 and res.json()["code"] == "CONFLICT"


# --- a connection lists what a person revoked, so the web can offer to allow it again ---------------------


def _stripe(user) -> dict:
    return next(c for c in user.get("/v1/connections").json() if c["key"] == "stripe")


def test_a_revoked_grant_leaves_the_grants_and_is_listed_as_revoked(ana, composio, db):  # noqa: F811
    ana.hire()
    assert (ana.connect("stripe").json()["grants"], _stripe(ana)["revoked"]) == (STRIPE_GRANT, [])
    _revoke_stripe_read(ana)
    stripe = _stripe(ana)
    assert (stripe["grants"], stripe["revoked"]) == ([], [REVOKED])
    assert _disconnect(ana).json()["revoked"] == [REVOKED]  # remembered while disconnected
    assert ana.connect("stripe").json()["revoked"] == [REVOKED]  # and across connects
    assert _live_connect(ana, "stripe").json()["revoked"] == [REVOKED]
    composio.connected_accounts.statuses["ca_new"] = "ACTIVE"
    assert _sync(ana).json()["revoked"] == [REVOKED]


def test_allowing_a_grant_again_takes_it_off_the_revoked_list(ana, db):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    _revoke_stripe_read(ana)
    allowed = _allow_again(ana).json()
    assert (allowed["grants"], allowed["revoked"]) == (STRIPE_GRANT, [])
    assert (_stripe(ana)["grants"], _stripe(ana)["revoked"]) == (STRIPE_GRANT, [])


def test_allowing_again_a_capability_no_pack_uses_only_shortens_the_revoked_list(ana, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "sandbox", "sandbox")
    other = {"install": "Other pack", "capability": "payments.write"}
    db.execute(
        "UPDATE connections SET revoked_grants = %s WHERE org_id = %s",
        (Jsonb([REVOKED, other]), ana.org_id),
    )
    db.commit()
    allowed = _allow_again(ana).json()
    assert (allowed["grants"], allowed["revoked"]) == ([], [other])


def test_a_malformed_revoked_entry_is_skipped_not_listed(ana, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "sandbox", "sandbox")
    db.execute(
        "UPDATE connections SET revoked_grants = %s WHERE org_id = %s",
        (Jsonb([{"install": "x"}, "junk", REVOKED]), ana.org_id),
    )
    db.commit()
    assert _stripe(ana)["revoked"] == [REVOKED]


def test_the_demo_workspace_lists_no_revoked_grants(client):
    assert all(c["revoked"] == [] for c in client.get("/v1/connections").json())


# --- grant changes serialise with connects and with each other --------------------------------------------


def _needs_reauth(db, org_id: str) -> None:
    db.execute(
        "UPDATE connections SET status = 'needs_reauth', mode = 'composio', account_id = 'ca_1' "
        "WHERE org_id = %s AND app = 'stripe'",
        (org_id,),
    )
    db.commit()


def test_revoking_and_allowing_again_take_the_rows_lock(ana, monkeypatch):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    real_lock, locks = live_connections._lock, []

    def lock(conn, org_id, key):
        locks.append(key)
        real_lock(conn, org_id, key)

    monkeypatch.setattr(live_connections, "_lock", lock)
    _revoke_stripe_read(ana)
    assert locks == ["stripe"]
    assert _allow_again(ana).status_code == 200
    assert locks == ["stripe", "stripe"]


def test_allowing_again_on_a_row_that_needs_sign_in_again_restores_the_grant(ana, db):  # noqa: F811
    ana.hire()
    ana.connect("stripe")
    _revoke_stripe_read(ana)
    _needs_reauth(db, ana.org_id)
    allowed = _allow_again(ana).json()
    assert (allowed["status"], allowed["grants"], allowed["revoked"]) == ("needs_reauth", STRIPE_GRANT, [])


def test_a_pack_added_while_an_app_needs_sign_in_again_grants_it(ana, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "needs_reauth", "composio", "ca_1")
    assert ana.hire().status_code == 201
    assert (_stripe(ana)["status"], _stripe(ana)["grants"]) == ("needs_reauth", STRIPE_GRANT)


def test_granting_a_pack_locks_its_connections_in_key_order():
    """Two packs granted at once lock the same rows in the same order, so neither waits on the other, and
    each app's (org, app) lock (the one a connect or re-grant holds) is taken before its row."""

    class Conn:
        def __init__(self) -> None:
            self.locks: list[tuple[str, str]] = []

        def execute(self, sql, params=()):
            if "pg_advisory_xact_lock" in sql:
                self.locks.append(("app", params[0]))
            if "FOR UPDATE" in sql:
                self.locks.append(("row", params[1]))
            return self

        def fetchone(self):
            return None

    conn = Conn()
    pack = {"name": "P", "connectors": ["stripe", "gmail", "shopify"]}
    live_connections.grant_pack(conn, {}, "org_x", pack, {})
    assert conn.locks == [
        ("app", "org_x:gmail"),
        ("row", "gmail"),
        ("app", "org_x:shopify"),
        ("row", "shopify"),
        ("app", "org_x:stripe"),
        ("row", "stripe"),
    ]
