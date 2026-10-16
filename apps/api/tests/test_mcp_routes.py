"""A connection to an org's own MCP server (mode 'mcp') routes runs to that server, is pinned like an
account, counts as real, shows in the org's connections and is managed only under its MCP servers."""

from app import live_connections
from app.catalog.packs import SandboxForecast
from app.runtime import routes
from tests.live_seed import add_org
from tests.mcp_seed import SERVER_ID, custom_connector, mcp_connection
from tests.test_live_catalog import ana, ben, live, starts  # noqa: F401

ROW = {
    "status": "connected",
    "mode": "mcp",
    "account_id": SERVER_ID,
    "grants": [{"install": "CRM pack", "capability": "acme-crm.read"}],
}


def test_a_connected_mcp_row_routes_to_its_server():
    route = routes.route_of("org_1", ROW)
    assert (route.mode, route.account_id, route.user_id) == ("mcp", SERVER_ID, None)
    assert route.allows("CRM pack", "acme-crm.read")
    assert routes.route_of("org_1", {**ROW, "account_id": None}) == routes.NONE
    assert routes.route_of("org_1", {**ROW, "status": "not_connected"}) == routes.NONE
    assert {"composio", "mcp"} == routes.REAL_MODES


def test_only_a_connected_mcp_row_with_its_server_is_routable(db):
    add_org(db, "org_acme", "Acme")
    mcp_connection(db, "org_acme", "org-acme--a")
    mcp_connection(db, "org_acme", "org-acme--b", account=None)
    mcp_connection(db, "org_acme", "org-acme--c", status="not_connected")
    db.commit()
    sql = (
        f"SELECT count(*) AS n FROM connections c WHERE c.org_id = %s AND {routes.ROUTABLE_SQL.format(c='c')}"
    )
    assert db.execute(sql, ("org_acme",)).fetchone()["n"] == 1


def test_a_run_pins_the_server_and_notices_another_one(db):
    add_org(db, "org_acme", "Acme")
    key = custom_connector(db, "org_acme")
    mcp_connection(db, "org_acme", key)
    db.commit()
    pinned = routes.pinned_routes(db, "org_acme", [key])
    assert pinned == {"routes": {key: "mcp"}, "accounts": {key: SERVER_ID}}
    assert not routes.route_changed(pinned, key, routes.Route("mcp", account_id=SERVER_ID))
    assert routes.route_changed(pinned, key, routes.Route("mcp", account_id="mcp_ffffffffffff"))


def test_a_connected_server_is_real_not_simulated():
    forecast = SandboxForecast(by_app={"k": routes.Route("mcp", account_id=SERVER_ID)})
    assert forecast("k", {}) is False


def test_the_connections_list_shows_the_orgs_own_server(ana, db):  # noqa: F811
    key = custom_connector(db, ana.org_id)
    mcp_connection(db, ana.org_id, key)
    db.commit()
    res = ana.get("/v1/connections")
    assert res.status_code == 200, res.text
    found = next(c for c in res.json() if c.get("key") == key)
    assert {k: found[k] for k in ("app", "status", "provider", "mode")} == {
        "app": "Acme CRM",
        "status": "connected",
        "provider": "MCP",
        "mode": "mcp",
    }


def test_a_server_is_not_connected_or_disconnected_as_an_app(ana, db):  # noqa: F811
    key = custom_connector(db, ana.org_id)
    mcp_connection(db, ana.org_id, key)
    db.commit()
    for path in (
        f"/v1/connections/{key}:connect",
        "/v1/connections/Acme CRM:connect",
        f"/v1/connections/{key}:sync",
        f"/v1/connections/{key}:disconnect",
    ):
        res = ana.post(path)
        assert (res.status_code, res.json()["code"]) == (409, "MCP_SERVER_CONNECTION"), path
        assert res.json()["detail"] == "Manage this server under Your MCP servers."


def test_another_org_does_not_see_the_server(ana, ben, db):  # noqa: F811
    key = custom_connector(db, ana.org_id)
    db.commit()
    res = ben.post(f"/v1/connections/{key}:connect")
    assert (res.status_code, res.json()["code"]) == (404, "NOT_FOUND")


def test_the_start_gate_names_the_server(ana, db):  # noqa: F811
    key = custom_connector(db, ana.org_id)
    db.commit()
    assert live_connections.missing_apps(ana.org_id, [key]) == ["Acme CRM"]
