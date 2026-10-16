"""Tools of an org's own MCP server at run time: policy, grants, approval and argument checks come first, then
McpDriver calls the server. A sandbox test answers from the tool's sample and never calls it, and a pinned
run keeps its connector version after a refresh."""

import pytest
from psycopg.types.json import Jsonb

from app.custom_mcp import client as drivers_client
from app.custom_mcp import safety as drivers_safety
from app.defs import registry
from app.runtime import drivers, gateway, routes
from tests.fake_mcp import READ_ONLY, TOKEN, URL, fake_mcp  # noqa: F401
from tests.mcp_seed import connector_body
from tests.test_live_catalog import As, ana, ben, live, starts  # noqa: F401

INSTALL = "CRM pack"
CAPABILITIES = ["acme-crm.read", "acme-crm.write"]


def _base(user: As) -> str:
    return f"/v1/organizations/{user.org_id}/mcp-servers"


def _add(user: As) -> dict:
    res = user.post(_base(user), json={"name": "Acme CRM", "url": URL, "token": TOKEN})
    assert res.status_code == 201, res.text
    return res.json()


def _grant(db, org_id: str, key: str) -> None:
    """The grants an added pack named INSTALL would hold. A refresh or switch re-grants from the org's added
    packs, which these tests have none of, so call this again after one."""
    grants = [{"install": INSTALL, "capability": c} for c in CAPABILITIES]
    db.execute(
        "UPDATE connections SET grants = %s WHERE org_id = %s AND app = %s", (Jsonb(grants), org_id, key)
    )
    db.commit()


def _snapshot(db, org_id: str, key: str, version: int | None = None) -> dict:
    db.commit()
    v = (
        registry.get_version(db, "connector", key, version)
        if version
        else registry.latest(db, "connector", key)
    )
    return {
        "org_id": org_id,
        "routing": routes.ORG_ROUTING,
        **routes.pinned_routes(db, org_id, [key]),
        "defs": {
            "connector": {key: {"body": v.body}},
            "contract": {"crm": {"body": {"authorization": {"tool_capabilities": CAPABILITIES}}}},
            "pack": {"crm-pack": {"body": {"name": INSTALL}}},
        },
        "overrides": {},
        "disabled": [],
    }


def _call(snapshot: dict, ref: str, args: dict, approved: bool = False):
    return gateway.call_tool(snapshot=snapshot, tool_ref=ref, args=args, approved=approved, mode="sandbox")


def _lookup_invoice(invoice_id: str) -> str:
    return f"invoice {invoice_id}"


def test_a_sandbox_test_answers_from_the_tool_sample():
    body = connector_body()
    driver = drivers.driver_for(body, "sandbox")
    result = driver.execute("org-x--acme-crm", body["tools"][0], {"customer_id": "c_1"})
    assert (result.ok, result.mocked, result.data) == (True, True, body["tools"][0]["sample"])
    plain = driver.execute("org-x--acme-crm", body["tools"][1], {})
    assert (plain.ok, plain.mocked, plain.data) == (True, True, {"sandbox": True})


def test_an_unrouted_run_never_calls_the_server():
    assert isinstance(drivers.driver_for(connector_body(), "live"), drivers.UnconnectedDriver)
    assert isinstance(drivers.driver_for(connector_body(), "auto"), drivers.SandboxDriver)


def test_an_mcp_route_picks_the_mcp_driver():
    route = routes.Route("mcp", account_id="mcp_0123456789ab")
    driver = gateway._route_driver({}, "org-x--acme-crm", connector_body(), route)
    assert isinstance(driver, drivers.McpDriver) and driver.server_id == "mcp_0123456789ab"


def test_a_read_tool_runs_on_the_server(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)
    snapshot = _snapshot(db, ana.org_id, key)
    decision, result = _call(snapshot, f"{key}.get_customer", {"customer_id": "c_1"})
    assert decision.verdict == gateway.PERMIT
    assert (result.ok, result.mocked) == (True, False)
    assert result.data == {"id": "c_1", "name": "Ada Lovelace", "email": "ada@example.com"}
    assert gateway.runs_simulated(snapshot, f"{key}.get_customer", "sandbox") is False


def test_a_write_tool_waits_for_approval_then_runs(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)
    snapshot = _snapshot(db, ana.org_id, key)
    args = {"customer_id": "c_1", "note": "VIP"}
    decision, result = _call(snapshot, f"{key}.update_customer_note", args)
    assert (decision.verdict, result) == (gateway.REQUIRE_APPROVAL, None)
    decision, result = _call(snapshot, f"{key}.update_customer_note", args, approved=True)
    assert decision.verdict == gateway.PERMIT and result.ok
    assert result.data == {"result": "noted c_1: VIP"}


def test_without_a_grant_nothing_runs(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    decision, result = _call(_snapshot(db, ana.org_id, key), f"{key}.get_customer", {"customer_id": "c_1"})
    assert (decision.reason_codes, result) == ([gateway.GRANT_REVOKED], None)


def test_arguments_are_checked_before_the_server_sees_them(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)
    before = len(fake_mcp.paths)
    _, result = _call(
        _snapshot(db, ana.org_id, key), f"{key}.get_customer", {"customer_id": "c_1", "extra": 1}
    )
    assert not result.ok and result.error.startswith("invalid arguments")
    assert len(fake_mcp.paths) == before


def test_a_blocked_tool_is_never_offered(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)
    decision, result = _call(_snapshot(db, ana.org_id, key), f"{key}.delete_customer", {"customer_id": "c_1"})
    assert (decision.reason_codes, result) == (["UNKNOWN_TOOL"], None)


def test_a_tool_switched_off_after_the_run_pinned_it_is_refused(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    _grant(db, ana.org_id, key)
    snapshot = _snapshot(db, ana.org_id, key)
    assert ana.post(f"{_base(ana)}/{server['id']}/tools/get_customer:off").status_code == 200
    _grant(db, ana.org_id, key)
    before = len(fake_mcp.paths)
    _, result = _call(snapshot, f"{key}.get_customer", {"customer_id": "c_1"})
    assert not result.ok and result.error.startswith("ToolOff:")
    assert len(fake_mcp.paths) == before  # reach is read fresh on every call: no request went out


def test_a_tool_error_is_a_failed_call(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)
    _, result = _call(_snapshot(db, ana.org_id, key), f"{key}.get_broken_report", {})
    assert not result.ok and result.error.startswith("ToolError:")
    assert "report service is down" in result.error


def test_a_removed_server_runs_nothing(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    _grant(db, ana.org_id, key)
    snapshot = _snapshot(db, ana.org_id, key)
    assert ana.delete(f"{_base(ana)}/{server['id']}").status_code == 204
    _, result = _call(snapshot, f"{key}.get_customer", {"customer_id": "c_1"})
    assert not result.ok and result.error.startswith("NotConnected:")


def test_a_server_that_stops_answering_is_marked_failing(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)
    fake_mcp.tokens = set()  # the server now refuses the token
    _, result = _call(_snapshot(db, ana.org_id, key), f"{key}.get_customer", {"customer_id": "c_1"})
    assert not result.ok and result.error.startswith("McpUnreachable:")
    listed = ana.get(_base(ana)).json()[0]
    assert (listed["status"], listed["lastError"]) == ("failing", "unreachable")


def test_a_pinned_run_keeps_its_version_after_a_refresh(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    _grant(db, ana.org_id, key)
    pinned = _snapshot(db, ana.org_id, key)
    fake_mcp.server.add_tool(
        _lookup_invoice, name="lookup_invoice", description="Look up an invoice.", annotations=READ_ONLY
    )
    assert ana.post(f"{_base(ana)}/{server['id']}:refresh").status_code == 200
    _grant(db, ana.org_id, key)
    db.commit()
    assert sorted(v.version for v in registry.versions(db, "connector", key)) == [1, 2]
    _, result = _call(pinned, f"{key}.get_customer", {"customer_id": "c_1"})
    assert result.ok
    decision, _ = _call(pinned, f"{key}.lookup_invoice", {"invoice_id": "i_1"})
    assert decision.reason_codes == ["UNKNOWN_TOOL"]
    _, result = _call(_snapshot(db, ana.org_id, key), f"{key}.lookup_invoice", {"invoice_id": "i_1"})
    assert result.ok and result.data == {"result": "invoice i_1"}


def test_a_sandbox_test_run_never_calls_the_server(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    snapshot = {**_snapshot(db, ana.org_id, key), "connector_mode": "sandbox"}
    snapshot.pop("routing")
    before = len(fake_mcp.paths)
    _, result = _call(snapshot, f"{key}.get_customer", {"customer_id": "c_1"})
    assert (result.ok, result.mocked) == (True, True)
    assert result.data == {"id": "sample", "name": "sample", "email": "sample"}
    assert len(fake_mcp.paths) == before


def test_a_route_of_another_org_cannot_reach_the_server(fake_mcp, ana, ben, db):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    driver = drivers.McpDriver(server["id"], org_id=ben.org_id)
    tool = {"id": "get_customer", "slug": "get_customer"}
    result = driver.execute(key, tool, {"customer_id": "c_1"})
    assert not result.ok and result.error.startswith("NotConnected:")
    assert drivers.McpDriver(server["id"], org_id=ana.org_id).execute(key, tool, {"customer_id": "c_1"}).ok
    # through the gateway: org B's snapshot with org A's server id (route account_id) is not connected
    route = routes.Route("mcp", account_id=server["id"])
    routed = gateway._route_driver({"org_id": ben.org_id}, key, connector_body(server_id=server["id"]), route)
    assert routed.execute(key, tool, {"customer_id": "c_1"}).error.startswith("NotConnected:")


def test_a_missing_secrets_key_fails_the_call_without_the_token(fake_mcp, ana, db, monkeypatch):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)
    snapshot = _snapshot(db, ana.org_id, key)
    monkeypatch.delenv("NM_SECRETS_KEY")
    _, result = _call(snapshot, f"{key}.get_customer", {"customer_id": "c_1"})
    assert not result.ok and result.error.startswith("SecretsUnavailable:")
    assert TOKEN not in result.error and not result.mocked
    assert ana.get(_base(ana)).json()[0]["status"] == "active"  # a key problem is not the server failing


def test_an_mcp_connector_never_gets_a_composio_driver():
    for mode in ("sandbox", "live", "auto"):
        assert not isinstance(drivers.driver_for(connector_body(), mode), drivers.ComposioDriver)


def test_a_connected_mcp_route_uses_the_mcp_driver_not_sandbox(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)
    snapshot = _snapshot(db, ana.org_id, key)
    found = gateway.find_tool(snapshot, f"{key}.get_customer")
    driver = gateway.driver_of(snapshot, found[0], found[1], "sandbox")
    assert isinstance(driver, drivers.McpDriver) and not isinstance(driver, drivers.SandboxDriver)


def test_a_route_naming_another_server_than_the_connector_runs_nothing():
    route = routes.Route("mcp", account_id="mcp_ffffffffffff")
    driver = gateway._route_driver({"org_id": "org-x"}, "org-x--acme-crm", connector_body(), route)
    assert isinstance(driver, drivers.UnconnectedDriver)


def test_a_removed_connection_routes_to_nothing(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    _grant(db, ana.org_id, key)
    snapshot = _snapshot(db, ana.org_id, key)
    assert ana.delete(f"{_base(ana)}/{server['id']}").status_code == 204
    found = gateway.find_tool(snapshot, f"{key}.get_customer")
    assert isinstance(gateway.driver_of(snapshot, found[0], found[1], "sandbox"), drivers.UnconnectedDriver)


def test_a_stored_header_that_cannot_be_sent_is_not_an_address_refusal(fake_mcp, ana, db, monkeypatch):  # noqa: F811
    key = _add(ana)["connectorKey"]
    _grant(db, ana.org_id, key)

    def refuse(*args):
        raise drivers_safety.UrlRefused("bad_header")

    monkeypatch.setattr(drivers_client, "call_tool", refuse)
    _, result = _call(_snapshot(db, ana.org_id, key), f"{key}.get_customer", {"customer_id": "c_1"})
    assert not result.ok and result.error.startswith("SecretsUnavailable:")
    assert "address" not in result.error and TOKEN not in result.error
    assert ana.get(_base(ana)).json()[0]["status"] == "active"


def test_an_unknown_mode_is_refused_for_an_mcp_connector_too():
    for mode in ("", "bogus", "Live"):
        with pytest.raises(ValueError):
            drivers.driver_for(connector_body(), mode)


def test_the_mcp_driver_needs_an_org():
    with pytest.raises(TypeError):
        drivers.McpDriver("mcp_0123456789ab")  # type: ignore[call-arg]
