"""An org's own MCP servers over the API, against the in-process FastMCP server (tests.fake_mcp): add, list,
refresh, switch tools, replace the token and remove, owners and admins only, the token never shown."""

import pytest
from mcp.types import ToolAnnotations

from app import mcp_servers, secrets_box
from app.custom_mcp import safety
from app.defs import owners, registry
from app.models.mcp import AddMcpServerRequest, ReplaceMcpTokenRequest
from tests.fake_mcp import FRESH_TOKEN, READ_ONLY, TOKEN, URL, fake_mcp  # noqa: F401
from tests.test_live_catalog import As, ana, ben, live, starts  # noqa: F401
from tests.test_live_connections_guards import _as_role


def _base(user: As) -> str:
    return f"/v1/organizations/{user.org_id}/mcp-servers"


def _add(user: As, **over) -> dict:
    res = user.post(_base(user), json={"name": "Acme CRM", "url": URL, "token": TOKEN, **over})
    assert res.status_code == 201, res.text
    return res.json()


def _tools(server: dict) -> dict[str, tuple[str, str, bool]]:
    return {t["name"]: (t["toolClass"], t["why"], t["on"]) for t in server["tools"]}


def _connector(db, key: str) -> dict:
    db.commit()
    return registry.latest(db, "connector", key).body


def _servers(db) -> int:
    db.commit()
    return db.execute("SELECT count(*) AS n FROM mcp_servers").fetchone()["n"]


def _lookup_invoice(invoice_id: str) -> str:
    return f"invoice {invoice_id}"


def test_adding_a_server_sorts_its_tools_and_publishes_a_private_connector(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key = owners.org_key(ana.org_id, "acme-crm")
    assert {k: server[k] for k in ("name", "url", "headerName", "tokenLast4", "status", "connectorKey")} == {
        "name": "Acme CRM",
        "url": URL,
        "headerName": "Authorization",
        "tokenLast4": "1234",
        "status": "active",
        "connectorKey": key,
    }
    assert server["id"].startswith("mcp_") and server["toolCount"] == 4
    assert _tools(server) == {
        "get_customer": ("read", "marked_read_only", True),
        "list_orders": ("read", "marked_read_only", True),
        "get_broken_report": ("read", "marked_read_only", True),
        "update_customer_note": ("write", "changes_data", True),
        "delete_customer": ("blocked", "marked_destructive", False),
        "refund_payment": ("blocked", "moves_money", False),
    }
    body = _connector(db, key)
    assert (body["app"], body["transport"], body["server"]) == ("Acme CRM", "mcp", server["id"])
    tools = {t["id"]: t for t in body["tools"]}
    assert sorted(tools) == ["get_broken_report", "get_customer", "list_orders", "update_customer_note"]
    assert (tools["get_customer"]["capability"], tools["update_customer_note"]["action_class"]) == (
        "acme-crm.read",
        "write",
    )
    assert tools["get_customer"]["input_schema"]["additionalProperties"] is False
    assert tools["get_customer"]["sample"] == {"id": "sample", "name": "sample", "email": "sample"}
    assert registry.owner_of(db, "connector", key) == owners.org_owner(ana.org_id)
    row = db.execute(
        "SELECT status, mode, account_id FROM connections WHERE org_id = %s AND app = %s", (ana.org_id, key)
    ).fetchone()
    assert dict(row) == {"status": "connected", "mode": "mcp", "account_id": server["id"]}


def test_the_token_is_sealed_and_never_shown(fake_mcp, ana, db):  # noqa: F811
    res = ana.post(_base(ana), json={"name": "Acme CRM", "url": URL, "token": TOKEN})
    assert res.status_code == 201 and TOKEN not in res.text
    listed = ana.get(_base(ana))
    assert listed.status_code == 200 and TOKEN not in listed.text
    db.commit()
    sealed = bytes(db.execute("SELECT token_ciphertext FROM mcp_servers").fetchone()["token_ciphertext"])
    assert TOKEN.encode() not in sealed
    assert secrets_box.open_sealed(sealed, res.json()["id"]) == TOKEN


def test_an_api_key_header_is_kept(fake_mcp, ana):  # noqa: F811
    assert _add(ana, headerName="X-Api-Key")["headerName"] == "X-Api-Key"


def test_an_http_address_is_refused_before_any_request(fake_mcp, ana, db):  # noqa: F811
    res = ana.post(_base(ana), json={"name": "Acme CRM", "url": "http://mcp.acme.test/mcp", "token": TOKEN})
    assert (res.status_code, res.json()["code"]) == (422, "MCP_URL_REFUSED")
    assert res.json()["detail"] == "This address cannot be used. Use an https address on the public internet."
    assert fake_mcp.paths == [] and _servers(db) == 0


def test_a_host_that_resolves_to_a_private_address_is_refused(fake_mcp, ana, monkeypatch):  # noqa: F811
    monkeypatch.setattr(safety, "resolve", lambda host, port: ["10.0.0.5"])
    res = ana.post(_base(ana), json={"name": "Acme CRM", "url": URL, "token": TOKEN})
    assert (res.status_code, res.json()["code"]) == (422, "MCP_URL_REFUSED")
    assert fake_mcp.paths == []


def test_a_wrong_token_is_unreachable(fake_mcp, ana, db):  # noqa: F811
    res = ana.post(_base(ana), json={"name": "Acme CRM", "url": URL, "token": "wrong-token-0000"})
    assert (res.status_code, res.json()["code"]) == (422, "MCP_UNREACHABLE")
    assert "wrong-token" not in res.text and _servers(db) == 0


def test_a_server_with_only_blocked_tools_is_refused(fake_mcp, ana):  # noqa: F811
    for name in ("get_customer", "list_orders", "update_customer_note", "get_broken_report"):
        fake_mcp.server.remove_tool(name)
    res = ana.post(_base(ana), json={"name": "Acme CRM", "url": URL, "token": TOKEN})
    assert (res.status_code, res.json()["code"]) == (422, "MCP_NO_TOOLS")


def test_a_name_in_use_or_a_platform_app_name_is_taken(fake_mcp, ana):  # noqa: F811
    _add(ana)
    for name in ("acme crm", "Stripe"):
        res = ana.post(_base(ana), json={"name": name, "url": URL, "token": TOKEN})
        assert (res.status_code, res.json()["code"]) == (409, "NAME_TAKEN"), name


def test_without_the_secrets_key_nothing_is_added(fake_mcp, ana, db, monkeypatch):  # noqa: F811
    monkeypatch.delenv("NM_SECRETS_KEY")
    res = ana.post(_base(ana), json={"name": "Acme CRM", "url": URL, "token": TOKEN})
    assert (res.status_code, res.json()["code"]) == (503, "SECRETS_UNAVAILABLE")
    assert fake_mcp.paths == [] and _servers(db) == 0


def test_the_request_is_checked_without_echoing_the_token(fake_mcp, ana):  # noqa: F811
    for body in (
        {"name": "  ", "url": URL, "token": TOKEN},
        {"name": "A", "url": URL, "token": "two\nlines-secret"},
        {"name": "A", "url": URL, "token": TOKEN, "headerName": "Host"},
        {"name": "A", "url": URL, "token": TOKEN, "headerName": "Bad Header"},
        {"name": "A", "url": URL, "token": TOKEN, "extra": 1},
        {"name": "A", "url": URL, "token": TOKEN, "headerName": "X-Key\r\nHost"},
        {"name": "A", "url": URL, "token": TOKEN, "headerName": "host"},
        {"name": "A", "url": URL, "token": TOKEN, "headerName": "Content-Type"},
        {"name": "A", "url": URL, "token": TOKEN, "headerName": "Mcp-Foo"},
        {"name": "Stripe​", "url": URL, "token": TOKEN},
        {"name": "A", "url": URL, "token": "12345678"},
        {"name": "A", "url": URL, "token": "has a space-secret"},
    ):
        res = ana.post(_base(ana), json=body)
        assert res.status_code == 422, body
        assert TOKEN not in res.text and "lines-secret" not in res.text


def test_refreshing_publishes_a_new_version_only_when_the_tools_changed(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key, refresh = server["connectorKey"], f"{_base(ana)}/{server['id']}:refresh"
    assert ana.post(refresh).status_code == 200
    assert len(registry.versions(db, "connector", key)) == 1
    fake_mcp.server.add_tool(
        _lookup_invoice, name="lookup_invoice", description="Look up an invoice.", annotations=READ_ONLY
    )
    res = ana.post(refresh)
    assert res.status_code == 200, res.text
    assert _tools(res.json())["lookup_invoice"] == ("read", "marked_read_only", True)
    assert res.json()["toolCount"] == 5 and res.json()["toolsListedAt"]
    db.commit()
    assert len(registry.versions(db, "connector", key)) == 2
    assert "lookup_invoice" in {t["id"] for t in _connector(db, key)["tools"]}


def test_a_tool_switched_off_leaves_the_connector_and_comes_back_on(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    tools = f"{_base(ana)}/{server['id']}/tools"
    off = ana.post(f"{tools}/update_customer_note:off")
    assert off.status_code == 200, off.text
    assert _tools(off.json())["update_customer_note"] == ("write", "changes_data", False)
    assert off.json()["toolCount"] == 3
    assert "update_customer_note" not in {t["id"] for t in _connector(db, server["connectorKey"])["tools"]}
    refreshed = ana.post(f"{_base(ana)}/{server['id']}:refresh").json()
    assert _tools(refreshed)["update_customer_note"][2] is False  # a refresh keeps the switch
    on = ana.post(f"{tools}/update_customer_note:on")
    assert _tools(on.json())["update_customer_note"][2] is True
    assert "update_customer_note" in {t["id"] for t in _connector(db, server["connectorKey"])["tools"]}


def test_a_blocked_tool_cannot_be_switched_on(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    tools = f"{_base(ana)}/{server['id']}/tools"
    res = ana.post(f"{tools}/delete_customer:on")
    assert (res.status_code, res.json()["code"]) == (409, "TOOL_BLOCKED")
    assert res.json()["detail"] == "A blocked tool cannot be switched on."
    assert ana.post(f"{tools}/no_such_tool:off").status_code == 404


def test_a_new_token_replaces_the_old_one_only_when_the_server_takes_it(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    url = f"{_base(ana)}/{server['id']}:replace-token"
    bad = ana.post(url, json={"token": "wrong-token-0000"})
    assert (bad.status_code, bad.json()["code"]) == (422, "MCP_UNREACHABLE")
    fake_mcp.tokens = {FRESH_TOKEN}  # the server now takes only the new token
    res = ana.post(url, json={"token": FRESH_TOKEN})
    assert res.status_code == 200, res.text
    assert res.json()["tokenLast4"] == "5678" and FRESH_TOKEN not in res.text
    assert ana.post(f"{_base(ana)}/{server['id']}:refresh").status_code == 200


def test_a_failed_refresh_marks_the_server_failing(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    fake_mcp.tokens = set()
    res = ana.post(f"{_base(ana)}/{server['id']}:refresh")
    assert (res.status_code, res.json()["code"]) == (422, "MCP_UNREACHABLE")
    listed = ana.get(_base(ana)).json()[0]
    assert (listed["status"], listed["lastError"]) == ("failing", "unreachable")


def test_removing_a_server_forgets_its_token_and_disconnects_it(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    res = ana.delete(f"{_base(ana)}/{server['id']}")
    assert res.status_code == 204
    assert ana.get(_base(ana)).json() == []
    db.commit()
    row = db.execute(
        "SELECT status, token_ciphertext, token_last4 FROM mcp_servers WHERE id = %s", (server["id"],)
    ).fetchone()
    assert dict(row) == {"status": "removed", "token_ciphertext": None, "token_last4": None}
    connection = db.execute(
        "SELECT status, grants, account_id FROM connections WHERE org_id = %s AND app = %s", (ana.org_id, key)
    ).fetchone()
    assert dict(connection) == {"status": "not_connected", "grants": [], "account_id": None}
    assert registry.latest(db, "connector", key) is not None  # pinned runs still need it
    assert ana.delete(f"{_base(ana)}/{server['id']}").status_code == 404


def test_a_removed_name_can_be_added_again(fake_mcp, ana):  # noqa: F811
    first = _add(ana)
    ana.delete(f"{_base(ana)}/{first['id']}")
    second = _add(ana)
    assert second["connectorKey"] == first["connectorKey"] and second["id"] != first["id"]


def test_members_list_servers_but_only_owners_and_admins_change_them(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    one = f"{_base(ana)}/{server['id']}"
    _as_role(db, ana, "member")
    assert ana.get(_base(ana)).status_code == 200
    for res in (
        ana.post(_base(ana), json={"name": "Other", "url": URL, "token": TOKEN}),
        ana.post(f"{one}:refresh"),
        ana.post(f"{one}/tools/get_customer:off"),
        ana.post(f"{one}:replace-token", json={"token": FRESH_TOKEN}),
        ana.delete(one),
    ):
        assert (res.status_code, res.json()["code"]) == (403, "FORBIDDEN")
    _as_role(db, ana, "admin")
    assert ana.post(f"{one}:refresh").status_code == 200


def test_another_org_cannot_see_or_change_the_servers(fake_mcp, ana, ben):  # noqa: F811
    server = _add(ana)
    assert ben.get(_base(ana)).status_code == 403
    assert ben.get(_base(ben)).json() == []
    assert ben.post(f"{_base(ben)}/{server['id']}:refresh").status_code == 404
    assert ben.delete(f"{_base(ben)}/{server['id']}").status_code == 404


def test_a_bad_token_for_a_new_token_is_a_validation_error(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    for token in ("12345678", "has a space-secret"):
        res = ana.post(f"{_base(ana)}/{server['id']}:replace-token", json={"token": token})
        assert res.status_code == 422 and "space-secret" not in res.text


def test_a_refused_header_from_the_client_is_a_validation_error(fake_mcp, ana, monkeypatch):  # noqa: F811
    def refuse(*args):
        raise safety.UrlRefused("bad_header")

    monkeypatch.setattr(mcp_servers.client, "list_tools", refuse)
    res = ana.post(_base(ana), json={"name": "Acme CRM", "url": URL, "token": TOKEN})
    assert (res.status_code, res.json()["code"]) == (422, "SCHEMA_INVALID")


def test_a_fullwidth_platform_name_clashes_with_it(fake_mcp, ana):  # noqa: F811
    res = ana.post(_base(ana), json={"name": "Ｓｔｒｉｐｅ", "url": URL, "token": TOKEN})
    assert (res.status_code, res.json()["code"]) == (409, "NAME_TAKEN")


def test_a_refresh_that_blocks_every_tool_stores_it_and_stops_calls(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    for tool in fake_mcp.server._tool_manager._tools.values():
        tool.annotations = ToolAnnotations(destructiveHint=True)
    res = ana.post(f"{_base(ana)}/{server['id']}:refresh")
    assert res.status_code == 200, res.text
    assert res.json()["toolCount"] == 0
    assert {(t["toolClass"], t["on"]) for t in res.json()["tools"]} == {("blocked", False)}
    db.commit()
    assert len(registry.versions(db, "connector", key)) == 2
    assert _connector(db, key)["tools"] == []
    with pytest.raises(mcp_servers.ToolOff):
        mcp_servers.reach(server["id"], key, "get_customer", org_id=ana.org_id)


def test_a_tool_with_an_empty_name_does_not_break_add_or_refresh(fake_mcp, ana, db):  # noqa: F811
    server = _add(ana)
    fake_mcp.server._tool_manager._tools[""] = fake_mcp.server._tool_manager._tools[
        "get_customer"
    ].model_copy(update={"name": ""})
    res = ana.post(f"{_base(ana)}/{server['id']}:refresh")
    assert res.status_code == 200, res.text
    assert ("blocked", "reserved_name", False) in _tools(res.json()).values()
    assert _add(ana, name="Second CRM")["toolCount"] >= 1


def test_the_token_never_shows_in_a_repr():  # noqa: F811
    assert TOKEN not in repr(AddMcpServerRequest(name="A", url=URL, token=TOKEN))
    assert TOKEN not in repr(ReplaceMcpTokenRequest(token=TOKEN))
    assert TOKEN not in repr(mcp_servers.Reach(URL, "Authorization", TOKEN))


def test_a_name_that_grows_under_nfkc_is_checked_after_it(fake_mcp, ana):  # noqa: F811
    # "ﷺ" is one character that NFKC turns into 18: four of them pass 60 only before normalising.
    res = ana.post(_base(ana), json={"name": "ﷺ" * 4, "url": URL, "token": TOKEN})
    assert res.status_code == 422
    assert ana.post(_base(ana), json={"name": "A" * 60, "url": URL, "token": TOKEN}).status_code == 201


def test_names_that_draw_nothing_are_refused(fake_mcp, ana):  # noqa: F811
    for name in ("Acme\ue000", "Acme\u0378", "Acme\u3164", "Acme\u2800", "\u3164", "A\u200bB"):
        res = ana.post(_base(ana), json={"name": name, "url": URL, "token": TOKEN})
        assert res.status_code == 422, name


def test_reach_needs_the_org_and_fails_closed(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    key = server["connectorKey"]
    assert mcp_servers.reach(server["id"], key, "get_customer", org_id=ana.org_id).url
    for org in ("", "org_other"):
        with pytest.raises(mcp_servers.ServerGone):
            mcp_servers.reach(server["id"], key, "get_customer", org_id=org)
    with pytest.raises(TypeError):
        mcp_servers.reach(server["id"], key, "get_customer")  # type: ignore[call-arg]


def test_a_reach_hides_its_token_in_a_repr(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    reach = mcp_servers.reach(server["id"], server["connectorKey"], "get_customer", org_id=ana.org_id)
    assert reach.token == TOKEN and TOKEN not in repr(reach)


def test_a_tool_the_admin_switched_off_stays_off_through_blocked_and_unblocked(fake_mcp, ana):  # noqa: F811
    server = _add(ana)
    base = f"{_base(ana)}/{server['id']}"
    assert ana.post(f"{base}/tools/get_customer:off").status_code == 200
    tool = fake_mcp.server._tool_manager._tools["get_customer"]
    tool.annotations = ToolAnnotations(destructiveHint=True)
    blocked = ana.post(f"{base}:refresh").json()
    assert _tools(blocked)["get_customer"][0] == "blocked"
    tool.annotations = READ_ONLY
    again = ana.post(f"{base}:refresh").json()
    assert _tools(again)["get_customer"] == ("read", "marked_read_only", False)
    assert _tools(ana.post(f"{base}/tools/get_customer:on").json())["get_customer"][2] is True


def test_a_surrogate_in_a_token_is_a_validation_error_not_a_crash(fake_mcp, ana):  # noqa: F811
    json_header = {**ana.headers, "content-type": "application/json"}
    escaped = r"abcdefghi\ud800"  # a JSON escape for a lone surrogate
    bad = '{"name": "A", "url": "' + URL + '", "token": "' + escaped + '"}'
    assert ana.api.post(_base(ana), content=bad, headers=json_header).status_code == 422
    server = _add(ana)
    res = ana.api.post(
        f"{_base(ana)}/{server['id']}:replace-token",
        content='{"token": "' + escaped + '"}',
        headers=json_header,
    )
    assert res.status_code == 422


def test_every_route_that_opens_or_seals_a_token_answers_503_without_a_key(fake_mcp, ana, monkeypatch):  # noqa: F811
    server = _add(ana)
    monkeypatch.delenv("NM_SECRETS_KEY")
    base = f"{_base(ana)}/{server['id']}"
    for res in (
        ana.post(f"{base}:refresh"),
        ana.post(f"{base}:replace-token", json={"token": FRESH_TOKEN}),
        ana.post(_base(ana), json={"name": "Other", "url": URL, "token": TOKEN}),
    ):
        assert (res.status_code, res.json()["code"]) == (503, "SECRETS_UNAVAILABLE")
