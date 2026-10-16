"""Ops and an org's own MCP servers: the connector list names the owning org, the tenant view shows the
connection's mode, and the usual disable switch pins the connector off for new runs."""

from app import ops_live, ops_state
from tests.live_seed import NOW, add_org
from tests.mcp_seed import custom_connector, mcp_connection

OPS = {"Authorization": "Bearer ops"}
REASON = "Testing own MCP servers"


def _seed(db) -> str:
    add_org(db, "org_acme", "Acme")
    key = custom_connector(db, "org_acme")
    mcp_connection(db, "org_acme", key)
    db.commit()
    return key


def test_the_connector_list_names_the_owning_org(defs):
    key = _seed(defs)
    entry = next(e for e in ops_live.list_connectors(defs, NOW) if e.id == key)
    assert (entry.app, entry.provider, entry.auth_type) == ("Acme CRM", "MCP", "api_key")
    assert (entry.owner_org_id, entry.owner_org_name, entry.tenants_connected) == ("org_acme", "Acme", 1)
    platform = next(e for e in ops_live.list_connectors(defs, NOW) if e.id == "stripe")
    assert (platform.provider, platform.owner_org_id) == ("Composio", None)


def test_ops_disables_the_connector_with_the_usual_switch(live_ops, defs):
    key = _seed(defs)
    res = live_ops.post(f"/v1/ops/connectors/{key}:disable", json={"reason": REASON}, headers=OPS)
    assert res.status_code == 200, res.text
    assert (res.json()["status"], res.json()["ownerOrgName"]) == ("disabled", "Acme")
    defs.commit()
    platform = next(e for e in ops_live.list_connectors(defs, NOW) if e.id == "stripe")
    assert platform.status == "enabled"  # the org's own key is off; a platform connector is not
    assert ops_state.snapshot_policy(defs, [key])[1] == [key]
    res = live_ops.post(f"/v1/ops/connectors/{key}:enable", json={"reason": REASON}, headers=OPS)
    assert res.json()["status"] == "enabled"


def test_the_tenant_view_shows_the_mcp_connection(live_ops, defs):
    key = _seed(defs)
    res = live_ops.get("/v1/ops/tenants/org_acme", headers=OPS)
    assert res.status_code == 200, res.text
    assert {"app": key, "status": "connected", "mode": "mcp"} in res.json()["connectorsList"]
    assert res.json()["connectors"] == 1
