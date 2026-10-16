"""The Studio and an org's own MCP server: its usable tools are in the palette under the server's name while
it is connected, and a pack or agent that uses it cannot be submitted to the marketplace."""

from app.defs import owners, registry
from tests.fake_mcp import TOKEN, URL, fake_mcp  # noqa: F401
from tests.publishing_seed import add_listing, add_publisher, add_version, approve_and_list
from tests.team_seed import TEAM_AGENT, _own, invoice_nudges
from tests.test_live_catalog import As, ana, live, starts  # noqa: F401

DETAIL = (
    "Anything that uses your own MCP server stays in your workspace. "
    "It cannot be submitted to the marketplace."
)


def _add(user: As) -> dict:
    res = user.post(
        f"/v1/organizations/{user.org_id}/mcp-servers", json={"name": "Acme CRM", "url": URL, "token": TOKEN}
    )
    assert res.status_code == 201, res.text
    return res.json()


def _palette(user: As) -> dict[str, dict]:
    res = user.get(f"/v1/organizations/{user.org_id}/studio/palette")
    assert res.status_code == 200, res.text
    return {t["ref"]: t for t in res.json()["tools"]}


def test_the_palette_offers_the_servers_usable_tools_under_its_name(fake_mcp, ana):  # noqa: F811
    key = _add(ana)["connectorKey"]
    tools = _palette(ana)
    assert tools[f"{key}.get_customer"]["app"] == "Acme CRM"
    assert tools[f"{key}.update_customer_note"]["actionClass"] == "write"
    assert f"{key}.delete_customer" not in tools and f"{key}.refund_payment" not in tools


def test_a_removed_servers_tools_leave_the_palette(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    ana.delete(f"/v1/organizations/{ana.org_id}/mcp-servers/{server['id']}")
    prefix = f"{server['connectorKey']}."
    assert not [ref for ref in _palette(ana) if ref.startswith(prefix)]


def test_a_removed_servers_tool_cannot_be_saved_into_an_agent_or_a_pack(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    ref = f"{server['connectorKey']}.get_customer"
    studio = f"/v1/organizations/{ana.org_id}/studio"
    body = TEAM_AGENT.model_dump(by_alias=True, exclude_none=True)
    assert ana.post(f"{studio}/agents", json={**body, "tools": [ref]}).status_code == 201
    ana.delete(f"/v1/organizations/{ana.org_id}/mcp-servers/{server['id']}")
    res = ana.post(f"{studio}/agents", json={**body, "tools": [ref]})
    assert res.status_code == 422, res.text
    assert f"{ref} is not a tool of any app." in res.text
    agent = ana.post(f"{studio}/agents", json=body).json()["key"]
    draft = invoice_nudges(agent).model_dump(by_alias=True, exclude_none=True)
    step = next(s for s in draft["steps"] if s["id"] == "invoices")
    step["config"] = {"tool": ref, "args": {"customer_id": "c1"}}
    assert ana.post(f"{studio}/packs", json=draft).status_code >= 400


def test_a_pack_that_uses_the_server_cannot_be_submitted(fake_mcp, ana, db):  # noqa: F811
    connector = _add(ana)["connectorKey"]
    key = owners.org_key(ana.org_id, "crm-follow-up")
    _own(db, ana.org_id, "pack", key, {"name": "CRM follow-up", "slug": key, "connectors": [connector]})
    add_publisher(db, ana.org_id)
    db.commit()
    res = ana.post(f"/v1/organizations/{ana.org_id}/studio/packs/{key}/submissions", json={"priceMinor": 50})
    assert (res.status_code, res.json()["code"], res.json()["detail"]) == (409, "NOT_PUBLISHABLE", DETAIL)
    db.commit()
    assert db.execute("SELECT count(*) AS n FROM listings").fetchone()["n"] == 0


def test_an_agent_that_uses_the_server_cannot_be_submitted(fake_mcp, ana, db):  # noqa: F811
    # The seed has no summary on purpose: the check must run before the definition checks.
    connector = _add(ana)["connectorKey"]
    key = owners.org_key(ana.org_id, "crm-helper")
    _own(
        db,
        ana.org_id,
        "agent",
        key,
        {"name": "CRM helper", "runtime": {"tools": [f"{connector}.get_customer"]}},
    )
    add_publisher(db, ana.org_id)
    db.commit()
    res = ana.post(f"/v1/organizations/{ana.org_id}/studio/agents/{key}/submissions", json={"priceMinor": 30})
    assert (res.status_code, res.json()["code"], res.json()["detail"]) == (409, "NOT_PUBLISHABLE", DETAIL)
    db.commit()
    assert db.execute("SELECT count(*) AS n FROM listings").fetchone()["n"] == 0


def test_a_pack_saved_through_the_studio_with_a_server_tool_step_cannot_be_submitted(fake_mcp, ana, db):  # noqa: F811
    key = _add(ana)["connectorKey"]
    studio = f"/v1/organizations/{ana.org_id}/studio"
    agent = ana.post(f"{studio}/agents", json=TEAM_AGENT.model_dump(by_alias=True, exclude_none=True))
    assert agent.status_code == 201, agent.text
    draft = invoice_nudges(agent.json()["key"]).model_dump(by_alias=True, exclude_none=True)
    step = next(s for s in draft["steps"] if s["id"] == "invoices")
    step["config"] = {"tool": f"{key}.get_customer", "args": {"customer_id": "c1"}}
    saved = ana.post(f"{studio}/packs", json=draft)
    assert saved.status_code == 201, saved.text
    add_publisher(db, ana.org_id)
    db.commit()
    res = ana.post(f"{studio}/packs/{saved.json()['key']}/submissions", json={"priceMinor": 50})
    assert (res.status_code, res.json()["code"], res.json()["detail"]) == (409, "NOT_PUBLISHABLE", DETAIL)


def test_a_listed_agent_that_gained_a_server_tool_cannot_carry_it_into_a_pack(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    studio = f"/v1/organizations/{ana.org_id}/studio"
    body = TEAM_AGENT.model_dump(by_alias=True, exclude_none=True)
    agent = ana.post(f"{studio}/agents", json=body).json()["key"]
    listing = add_listing(db, "agent", agent, ana.org_id, name="Listed agent")
    bundle = [{"kind": "agent", "key": agent, "version": registry.latest(db, "agent", agent).version}]
    approve_and_list(db, listing, add_version(db, listing, 1, bundle, price_minor=30))
    db.commit()
    with_tool = {**body, "tools": [*body["tools"], f"{key}.get_customer"]}
    v2 = ana.post(f"{studio}/agents/{agent}", json={"draft": with_tool, "baseVersion": 1})
    assert v2.status_code == 200, v2.text
    off = ana.post(f"/v1/organizations/{ana.org_id}/mcp-servers/{server['id']}/tools/get_customer:off")
    assert off.status_code == 200, off.text
    saved = ana.post(
        f"{studio}/packs", json=invoice_nudges(agent).model_dump(by_alias=True, exclude_none=True)
    )
    assert saved.status_code == 201, saved.text
    add_publisher(db, ana.org_id)
    db.commit()
    res = ana.post(f"{studio}/packs/{saved.json()['key']}/submissions", json={"priceMinor": 50})
    assert (res.status_code, res.json()["code"], res.json()["detail"]) == (409, "NOT_PUBLISHABLE", DETAIL)
    db.commit()
    assert (
        db.execute("SELECT count(*) AS n FROM listing_versions").fetchone()["n"] == 1
    )  # only the seeded one
