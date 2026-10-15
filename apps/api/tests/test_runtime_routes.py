"""Live-workspace runs reach each app the way the org connected it, whatever NM_CONNECTOR_MODE says: its own
account through Composio, sandbox data, or nothing. The way each app was reached at the start (and the
Composio account) is pinned for the run, and a call needs the org's grant for the pack. Demo runs keep the
connector mode."""

import asyncio
from itertools import product

import psycopg
import pytest
from psycopg.types.json import Jsonb
from temporalio.exceptions import ApplicationError

from app import db as app_db
from app.defs.snapshot import build_snapshot
from app.runtime import drivers, gateway, projection, routes
from app.runtime.providers import FakeProvider
from app.worker import activities
from app.worker.activities import NodeCall
from tests.test_live_catalog import PACK, PACK_NAME, _ready, ana, live, starts  # noqa: F401  (fixtures)
from tests.test_runtime_core import _StubComposio
from tests.test_workflow import INPUT, _all_matched_script, _drive, _start, _tasks

ORG = "org_a"
CHARGES = "stripe.list_charges"
GRANT = {"install": PACK_NAME, "capability": "payments.read", "access": "read"}
OLD_STATUSES = "('connected','not_connected','sandbox','needs_reauth')"


def _org(db) -> None:
    db.execute("INSERT INTO orgs (id, name) VALUES (%s, 'A') ON CONFLICT DO NOTHING", (ORG,))
    db.commit()


def _connect(
    db, app: str, status: str, mode: str, account: str | None = None, grants: list | None = None
) -> None:
    db.execute(
        "INSERT INTO connections (org_id, app, status, mode, connected_by, account_id, grants) "
        "VALUES (%s, %s, %s, %s, 'uid_a', %s, %s) ON CONFLICT (org_id, app) DO UPDATE SET "
        "status = EXCLUDED.status, mode = EXCLUDED.mode, account_id = EXCLUDED.account_id, "
        "grants = EXCLUDED.grants",
        (ORG, app, status, mode, account, Jsonb(grants or [])),
    )
    db.commit()


# How each way of connecting Stripe looks as a connections row, and what a run pins for it.
STRIPE = {
    "sandbox": {"status": "sandbox", "mode": "sandbox", "account": None},
    "composio": {"status": "connected", "mode": "composio", "account": "ca_1"},
}


def _connect_stripe(db, how: str, grants: list | None = None, account: str | None = None) -> None:
    row = STRIPE[how]
    _connect(db, "stripe", row["status"], row["mode"], account or row["account"], grants)


def _pins(how: str) -> dict:
    """The snapshot fields a run that started with Stripe connected `how` pins."""
    accounts = {"stripe": STRIPE[how]["account"]} if STRIPE[how]["account"] else {}
    return {"routes": {"stripe": how}, "accounts": accounts}


def _live(snapshot: dict | None = None, pins: dict | None = None) -> dict:
    return {**(snapshot or {}), "routing": routes.ORG_ROUTING, "org_id": ORG, **(pins or {})}


def _refuse_driver(**kwargs):
    raise AssertionError("this call must not reach a driver")


def _stub_composio(monkeypatch) -> _StubComposio:
    stub = _StubComposio({"data": {"items": []}, "successful": True, "error": None})
    monkeypatch.setattr(gateway, "ComposioDriver", lambda **kw: drivers.ComposioDriver(client=stub, **kw))
    return stub


def _refuse_drivers(monkeypatch) -> None:
    monkeypatch.setattr(gateway, "ComposioDriver", _refuse_driver)
    monkeypatch.setattr(gateway, "SandboxDriver", _refuse_driver)


def test_migration_011_lets_a_connection_be_pending_with_its_account(db):
    try:
        db.execute(
            "ALTER TABLE connections DROP COLUMN account_id, DROP CONSTRAINT connections_status_check, "
            f"ADD CONSTRAINT connections_status_check CHECK (status IN {OLD_STATUSES})"
        )
        db.execute("DELETE FROM schema_migrations WHERE name = '011_live_connections.sql'")
        db.commit()
        assert app_db.migrate(db) == ["011_live_connections.sql"]
        _org(db)
        _connect(db, "gmail", "pending", "composio", "ca_1")
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "INSERT INTO connections (org_id, app, status, mode, connected_by) "
                "VALUES (%s, 'stripe', 'half', 'composio', 'uid_a')",
                (ORG,),
            )
    finally:  # whatever failed above, `nm_test` keeps 011 for the tests after this one
        db.rollback()
        app_db.migrate(db)


def test_a_live_run_follows_each_apps_own_connection(db):
    _org(db)
    _connect(db, "stripe", "connected", "composio", "ca_1")
    _connect(db, "shopify", "sandbox", "sandbox")
    _connect(db, "gmail", "pending", "composio", "ca_2")
    _connect(db, "googlesheets", "needs_reauth", "composio", "ca_3")
    real = gateway.driver_of(_live(), "stripe", {"toolkit": "stripe"}, "sandbox")
    assert isinstance(real, drivers.ComposioDriver)
    assert real.user_id == "org:org_a" and real.account_id == "ca_1"
    assert isinstance(gateway.driver_of(_live(), "shopify", {}, "live"), drivers.SandboxDriver)
    for key in ("gmail", "googlesheets", "nothing"):
        assert isinstance(gateway.driver_of(_live(), key, {}, "sandbox"), drivers.UnconnectedDriver)


def test_a_composio_connection_without_its_account_reaches_nothing(db):
    _org(db)
    _connect(db, "stripe", "connected", "composio", None, [GRANT])
    assert routes.current_route(ORG, "stripe") == routes.NONE
    assert isinstance(gateway.driver_of(_live(), "stripe", {}, "live"), drivers.UnconnectedDriver)


STATUSES = ("connected", "sandbox", "pending", "needs_reauth", "not_connected")
MODES = ("composio", "sandbox")
ACCOUNTS = (None, "", "ca_1")


def test_routable_sql_agrees_with_route_of_on_every_row_shape(db):
    """`ROUTABLE_SQL` (the ops counts) selects exactly the rows `route_of` gives a route, over every status,
    mode and account id a connections row can hold."""
    _org(db)
    expected = set()
    for n, (status, mode, account) in enumerate(product(STATUSES, MODES, ACCOUNTS)):
        app = f"app_{n}"
        _connect(db, app, status, mode, account)
        if routes.route_of(ORG, {"status": status, "mode": mode, "account_id": account}).mode != "none":
            expected.add(app)
    rows = db.execute(f"SELECT c.app FROM connections c WHERE {routes.ROUTABLE_SQL.format(c='c')}").fetchall()
    assert {r["app"] for r in rows} == expected
    assert len(expected) == 4  # connected/composio with its account, and sandbox/sandbox whatever the account


def test_a_demo_run_keeps_the_connector_mode(db, monkeypatch):
    monkeypatch.setenv("DEMO_USER_UID", "uid_demo")
    assert isinstance(gateway.driver_of({"org_id": ORG}, "stripe", {}, "sandbox"), drivers.SandboxDriver)
    demo_live = gateway.driver_of({"org_id": ORG}, "stripe", {}, "live")
    assert isinstance(demo_live, drivers.ComposioDriver) and demo_live.user_id == "uid_demo"


def test_a_composio_call_runs_for_the_org_user_and_its_connected_account():
    stub = _StubComposio({"data": {"items": []}, "successful": True, "error": None})
    driver = drivers.ComposioDriver(client=stub, user_id="org:org_a", account_id="ca_1")
    driver.execute("stripe", {"id": "list_charges", "slug": "STRIPE_LIST_CHARGES"}, {"limit": 5})
    _, _, kwargs = stub.calls[0]
    assert kwargs["user_id"] == "org:org_a" and kwargs["connected_account_id"] == "ca_1"


def test_the_demo_composio_call_sends_no_account_id(monkeypatch):
    monkeypatch.setenv("DEMO_USER_UID", "uid_demo")
    stub = _StubComposio({"data": {}, "successful": True, "error": None})
    drivers.ComposioDriver(client=stub).execute("stripe", {"id": "x", "slug": "STRIPE_LIST_CHARGES"}, {})
    assert "connected_account_id" not in stub.calls[0][2]


def test_an_unconnected_app_fails_the_call_and_runs_nothing(defs):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()))
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref=CHARGES, args={}, approved=False, mode="sandbox"
    )
    assert decision.verdict == gateway.PERMIT
    assert result.ok is False and result.mocked is False
    assert result.error == "NotConnected: stripe is not connected"


def test_a_disabled_connector_is_denied_before_any_route_is_read(defs, monkeypatch):
    _org(defs)
    snapshot = {**_live(build_snapshot(defs, PACK, ORG, {}, set())), "disabled": ["stripe"]}

    def no_route(org_id, key):
        raise AssertionError("a disabled connector must not reach a driver")

    monkeypatch.setattr(routes, "current_route", no_route)
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref=CHARGES, args={}, approved=False, mode="live"
    )
    assert decision.verdict == gateway.DENY and decision.reason_codes == ["CONNECTOR_DISABLED"]
    assert result is None


def test_the_simulated_forecast_follows_the_orgs_row(defs):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()))
    _connect(defs, "shopify", "sandbox", "sandbox")
    _connect(defs, "stripe", "connected", "composio", "ca_1")
    assert gateway.runs_simulated(snapshot, "shopify.list_orders", "live") is True
    assert gateway.runs_simulated(snapshot, CHARGES, "sandbox") is False


def test_a_live_start_pins_org_routing_and_each_apps_route(ana, starts, db):  # noqa: F811
    _ready(ana)
    db.execute(
        "UPDATE connections SET status = 'connected', mode = 'composio', account_id = 'ca_9' "
        "WHERE app = 'stripe'"
    )
    db.commit()
    assert ana.start().status_code == 202
    db.commit()
    [row] = db.execute(
        "SELECT snapshot->>'routing' AS routing, snapshot->'routes' AS pins, "
        "snapshot->'accounts' AS accounts FROM runs"
    ).fetchall()
    assert row["routing"] == "org"
    assert row["pins"] == {"shopify": "sandbox", "stripe": "composio", "googlesheets": "sandbox"}
    assert row["accounts"] == {"stripe": "ca_9"}


# --- the route pinned at the start ----------------------------------------------------------------------

SWAPS = [("sandbox", "composio"), ("composio", "sandbox")]


@pytest.mark.parametrize(("pinned", "now"), SWAPS)
def test_an_app_reconnected_another_way_fails_the_call_without_reaching_a_driver(
    defs, monkeypatch, pinned, now
):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), _pins(pinned))
    _connect_stripe(defs, now, [GRANT])
    _refuse_drivers(monkeypatch)
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref=CHARGES, args={}, approved=False, mode="sandbox"
    )
    assert decision.verdict == gateway.PERMIT
    assert result.ok is False and result.mocked is False and drivers.is_route_changed(result)
    assert result.error == "RouteChanged: Stripe's connection changed during this run"


def test_an_app_reconnected_to_another_account_fails_the_call_without_reaching_composio(defs, monkeypatch):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), _pins("composio"))
    _connect_stripe(defs, "composio", [GRANT], account="ca_2")
    _refuse_drivers(monkeypatch)
    _, result = gateway.call_tool(snapshot=snapshot, tool_ref=CHARGES, args={}, approved=False, mode="live")
    assert drivers.is_route_changed(result)


def test_a_snapshot_that_pins_only_the_mode_keeps_working(defs, monkeypatch):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), {"routes": {"stripe": "composio"}})
    _connect_stripe(defs, "composio", [GRANT], account="ca_2")
    stub = _stub_composio(monkeypatch)
    _, result = gateway.call_tool(snapshot=snapshot, tool_ref=CHARGES, args={}, approved=False, mode="live")
    assert result.ok is True and stub.calls[0][2]["connected_account_id"] == "ca_2"


def test_an_app_disconnected_during_the_run_stops_its_calls_at_once(defs):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), _pins("composio"))
    _connect(defs, "stripe", "not_connected", "composio", "ca_1")
    _, result = gateway.call_tool(snapshot=snapshot, tool_ref=CHARGES, args={}, approved=False, mode="live")
    assert result.error == "NotConnected: stripe is not connected"


# --- grants ---------------------------------------------------------------------------------------------


def test_a_granted_composio_call_runs_on_the_orgs_account(defs, monkeypatch):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), _pins("composio"))
    _connect_stripe(defs, "composio", [GRANT])
    stub = _stub_composio(monkeypatch)
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref=CHARGES, args={"limit": 5}, approved=False, mode="sandbox"
    )
    assert decision.verdict == gateway.PERMIT and result.ok is True and result.mocked is False
    assert stub.calls[0][2]["connected_account_id"] == "ca_1"


@pytest.mark.parametrize("how", ["composio", "sandbox"])
def test_a_revoked_grant_denies_the_call_before_any_driver(defs, monkeypatch, how):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), _pins(how))
    other = {**GRANT, "install": "Refund Triage"}  # another pack's grant does not cover this one
    _connect_stripe(defs, how, [other])
    _refuse_drivers(monkeypatch)
    assert gateway.approval_refusal(snapshot, CHARGES) == "GRANT_REVOKED"
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref=CHARGES, args={}, approved=True, mode="sandbox"
    )
    assert decision.verdict == gateway.DENY and decision.reason_codes == ["GRANT_REVOKED"]
    assert result is None


def test_a_granted_sandbox_call_serves_sandbox_data(defs):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), _pins("sandbox"))
    _connect_stripe(defs, "sandbox", [GRANT])
    assert gateway.approval_refusal(snapshot, CHARGES) is None
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref=CHARGES, args={}, approved=False, mode="live"
    )
    assert decision.verdict == gateway.PERMIT and result.ok is True and result.mocked is True


def test_a_revoked_grant_is_denied_before_the_call_asks_for_approval(defs):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), {"routes": {"googlesheets": "sandbox"}})
    _connect(defs, "googlesheets", "sandbox", "sandbox")
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref="googlesheets.append_rows", args={}, approved=False, mode="sandbox"
    )
    assert decision.verdict == gateway.DENY and decision.reason_codes == ["GRANT_REVOKED"]
    assert result is None


def test_a_demo_run_forecasts_no_refusal(defs):
    _org(defs)
    snapshot = build_snapshot(defs, PACK, ORG, {}, set())
    assert gateway.approval_refusal(snapshot, CHARGES) is None  # demo: no routing mark, no connection read


def test_the_refusal_forecast_names_why_the_call_could_not_run(defs):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), _pins("composio"))
    assert gateway.approval_refusal(snapshot, CHARGES) == "NOT_CONNECTED"
    _connect_stripe(defs, "composio", [GRANT], account="ca_2")
    assert gateway.approval_refusal(snapshot, CHARGES) == "ROUTE_CHANGED"
    _connect_stripe(defs, "composio", [])
    assert gateway.approval_refusal(snapshot, CHARGES) == "GRANT_REVOKED"
    _connect_stripe(defs, "composio", [GRANT])
    assert gateway.approval_refusal(snapshot, CHARGES) is None
    assert gateway.approval_refusal(snapshot, "stripe.nothing") is None  # unknown tools fail at the call


def test_a_call_and_its_forecast_give_one_reason_when_the_route_changed_and_the_grant_is_revoked(
    defs, monkeypatch
):
    _org(defs)
    snapshot = _live(build_snapshot(defs, PACK, ORG, {}, set()), _pins("sandbox"))
    _connect_stripe(defs, "composio", [])  # reconnected to a real account, without the pack's grant
    _refuse_drivers(monkeypatch)
    assert gateway.approval_refusal(snapshot, CHARGES) == "ROUTE_CHANGED"
    decision, result = gateway.call_tool(
        snapshot=snapshot, tool_ref=CHARGES, args={}, approved=False, mode="sandbox"
    )
    assert decision.verdict == gateway.PERMIT and drivers.is_route_changed(result)


# --- approvals of a call the grant no longer covers --------------------------------------------------------

SHEETS = {"install": PACK_NAME, "capability": "sheets.write", "access": "write (approval)"}
REPORT = {
    "input": {},
    "memory": [],
    "approvals": {},
    "nodes": {"report": {"output": {"summary": "3 matched"}}},
}


def _org_run(conn, pins: dict) -> tuple[str, dict]:
    """A live-workspace run of the recon pack for ORG, with `pins` in its snapshot."""
    snapshot = _live(build_snapshot(conn, PACK, ORG, {}, set()), pins)
    run_id = "run_org_a"
    initial = projection.initial_projection(run_id, snapshot, INPUT, "You", 2000)
    conn.execute(
        "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input) "
        "VALUES (%s, %s, %s, 'RUNNING', %s, %s, %s)",
        (run_id, ORG, PACK, Jsonb(snapshot), Jsonb(initial), Jsonb(INPUT)),
    )
    conn.commit()
    return run_id, snapshot


def _receipt(conn, run_id: str) -> list[dict]:
    conn.commit()
    return conn.execute(
        "SELECT type, node_id, data FROM receipt_entries WHERE run_id = %s ORDER BY seq", (run_id,)
    ).fetchall()


def test_no_one_is_asked_to_approve_a_call_whose_grant_is_revoked(defs):
    _org(defs)
    _connect(defs, "googlesheets", "sandbox", "sandbox")  # connected, but no grant for the pack
    run_id, snapshot = _org_run(defs, {"routes": {"googlesheets": "sandbox"}})
    call = NodeCall(run_id, snapshot, "approve_write", REPORT, attempt=1, step=7)
    opened = activities.PackActivities().open_task(call)
    assert opened["route"] == "denied" and "GRANT_REVOKED" in opened["output"]["explanation"]
    assert _tasks(defs, run_id) == []
    failed = [e for e in _receipt(defs, run_id) if e["type"] == "node.failed"]
    assert failed[0]["node_id"] == "approve_write" and "GRANT_REVOKED" in failed[0]["data"]["error"]
    assert failed[0]["data"]["reason_codes"] == ["GRANT_REVOKED"]


@pytest.mark.parametrize(
    ("row", "code", "says"),
    [
        (None, "NOT_CONNECTED", "Google Sheets is not connected"),
        (("connected", "composio", "ca_1"), "ROUTE_CHANGED", "Google Sheets connection changed"),
        (("pending", "composio", "ca_1"), "NOT_CONNECTED", "Google Sheets is not connected"),
    ],
)
def test_no_one_is_asked_to_approve_a_call_that_could_not_run(defs, row, code, says):
    _org(defs)
    if row is not None:
        _connect(defs, "googlesheets", *row, grants=[SHEETS])
    run_id, snapshot = _org_run(defs, {"routes": {"googlesheets": "sandbox"}})  # started on sandbox data
    call = NodeCall(run_id, snapshot, "approve_write", REPORT, attempt=1, step=7)
    opened = activities.PackActivities().open_task(call)
    assert opened["route"] == "denied" and says in opened["output"]["explanation"]
    assert code in opened["output"]["explanation"]
    assert _tasks(defs, run_id) == []
    [failed] = [e for e in _receipt(defs, run_id) if e["type"] == "node.failed"]
    assert failed["data"]["reason_codes"] == [code] and failed["data"]["route"] == "denied"


def test_a_retried_refusal_keeps_what_the_receipt_says_after_the_grant_is_restored(defs):
    _org(defs)
    _connect(defs, "googlesheets", "sandbox", "sandbox")  # no grant: the approval is refused
    run_id, snapshot = _org_run(defs, {"routes": {"googlesheets": "sandbox"}})
    call = NodeCall(run_id, snapshot, "approve_write", REPORT, attempt=1, step=7)
    first = activities.PackActivities().open_task(call)
    _connect(defs, "googlesheets", "sandbox", "sandbox", grants=[SHEETS])  # restored before the retry
    again = activities.PackActivities().open_task(call)
    assert again == first and again["route"] == "denied"
    assert _tasks(defs, run_id) == []
    assert [e["type"] for e in _receipt(defs, run_id)] == ["node.started", "node.failed"]


def test_a_retried_approval_keeps_the_task_it_opened_after_the_grant_is_revoked(defs):
    _org(defs)
    _connect(defs, "googlesheets", "sandbox", "sandbox", grants=[SHEETS])
    run_id, snapshot = _org_run(defs, {"routes": {"googlesheets": "sandbox"}})
    call = NodeCall(run_id, snapshot, "approve_write", REPORT, attempt=1, step=7)
    first = activities.PackActivities().open_task(call)
    _connect(defs, "googlesheets", "sandbox", "sandbox")  # revoked before the retry
    again = activities.PackActivities().open_task(call)
    assert again == first and "route" not in again
    assert [t["kind"] for t in _tasks(defs, run_id)] == ["approval"]
    assert "node.failed" not in [e["type"] for e in _receipt(defs, run_id)]


def test_an_approval_for_a_granted_call_opens_as_before(defs):
    _org(defs)
    _connect(defs, "googlesheets", "sandbox", "sandbox", grants=[SHEETS])
    run_id, snapshot = _org_run(defs, {"routes": {"googlesheets": "sandbox"}})
    call = NodeCall(run_id, snapshot, "approve_write", REPORT, attempt=1, step=7)
    opened = activities.PackActivities().open_task(call)
    assert "route" not in opened and opened["kind"] == "approval"
    assert [t["kind"] for t in _tasks(defs, run_id)] == ["approval"]


def test_a_run_whose_write_grant_was_revoked_fails_without_waiting_for_approval(defs, monkeypatch):
    monkeypatch.setenv("NM_MODEL_ENV", "test")
    monkeypatch.setenv("NM_CONNECTOR_MODE", "sandbox")
    _org(defs)
    reads = [
        ("shopify", {**GRANT, "capability": "orders.read"}),
        ("stripe", GRANT),
    ]
    for app, grant in reads:
        _connect(defs, app, "sandbox", "sandbox", grants=[grant])
    _connect(defs, "googlesheets", "sandbox", "sandbox")  # its write grant was revoked
    pins = {"routes": {"shopify": "sandbox", "stripe": "sandbox", "googlesheets": "sandbox"}, "accounts": {}}
    run_id, snapshot = _org_run(defs, pins)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        return await handle.result()

    provider = FakeProvider(script=_all_matched_script())
    assert asyncio.run(_drive(provider, scenario)) == "FAILED"
    assert _tasks(defs, run_id) == []
    [ended] = [e for e in _receipt(defs, run_id) if e["type"] == "run.failed"]
    assert "GRANT_REVOKED" in ended["data"]["reason"]


# --- a retried read reads again by the pinned route ------------------------------------------------------


def _first_read(defs, monkeypatch, how: str) -> NodeCall:
    """A read of Stripe charges with Stripe connected `how`, whose tool.call entry committed; its activity is
    about to retry."""
    monkeypatch.setenv("NM_CONNECTOR_MODE", "sandbox")
    _org(defs)
    _connect_stripe(defs, how, [GRANT])
    if how == "composio":
        _stub_composio(monkeypatch)
    run_id, snapshot = _org_run(defs, _pins(how))
    call = NodeCall(run_id, snapshot, "payments", {}, attempt=1, step=3)
    first = activities._tool_call(call, CHARGES, {"limit": 5}, "tc_payments_1", False)
    assert first.failed is None and first.write is None
    activities._commit(call, [first.event], first.write)
    return call


@pytest.mark.parametrize(("pinned", "now"), SWAPS)
def test_a_retried_read_after_a_reconnect_fails_with_route_changed(defs, monkeypatch, pinned, now):
    call = _first_read(defs, monkeypatch, pinned)
    _connect_stripe(defs, now, [GRANT])
    _refuse_drivers(monkeypatch)
    with pytest.raises(ApplicationError) as err:
        activities._tool_call(call, CHARGES, {"limit": 5}, "tc_payments_1", False)
    assert err.value.type == "RouteChanged" and err.value.non_retryable
    assert "Stripe's connection changed during this run" in str(err.value)


def test_a_retried_read_after_a_switch_to_another_account_fails_with_route_changed(defs, monkeypatch):
    call = _first_read(defs, monkeypatch, "composio")  # composio:ca_1
    _connect_stripe(defs, "composio", [GRANT], account="ca_2")
    _refuse_drivers(monkeypatch)
    with pytest.raises(ApplicationError) as err:
        activities._tool_call(call, CHARGES, {"limit": 5}, "tc_payments_1", False)
    assert err.value.type == "RouteChanged" and err.value.non_retryable
    assert "Stripe's connection changed during this run" in str(err.value)


def test_a_retried_read_whose_grant_was_revoked_fails_for_good(defs, monkeypatch):
    call = _first_read(defs, monkeypatch, "sandbox")
    _connect_stripe(defs, "sandbox", [])
    with pytest.raises(ApplicationError) as err:
        activities._tool_call(call, CHARGES, {"limit": 5}, "tc_payments_1", False)
    assert err.value.non_retryable and "GRANT_REVOKED" in str(err.value)


def test_a_retried_read_that_fails_says_why(defs, monkeypatch):
    call = _first_read(defs, monkeypatch, "sandbox")
    _connect(defs, "stripe", "not_connected", "sandbox")
    with pytest.raises(ApplicationError) as err:
        activities._tool_call(call, CHARGES, {"limit": 5}, "tc_payments_1", False)
    assert err.value.type == "ReadAgain" and not err.value.non_retryable
    assert "NotConnected: stripe is not connected" in str(err.value)
