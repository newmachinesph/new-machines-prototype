"""The mcp_servers table: a live server holds its sealed token, one live server per connector key and name in
an org, and a connection may reach an MCP server (mode 'mcp')."""

import psycopg
import pytest
from psycopg.types.json import Jsonb

from tests.live_seed import add_org

ORG = "org_acme"


def _server(
    db,
    server_id: str,
    *,
    key: str = "org-acme--crm",
    name: str = "CRM",
    status: str = "active",
    token: bytes | None = b"sealed",
) -> None:
    db.execute(
        "INSERT INTO mcp_servers (id, org_id, connector_key, name, url, token_ciphertext, token_last4, "
        "status, tools, created_by) "
        "VALUES (%s, %s, %s, %s, 'https://mcp.acme.test/mcp', %s, '1234', %s, %s, 'uid')",
        (server_id, ORG, key, name, token, status, Jsonb([{"id": "get_customer"}])),
    )


@pytest.fixture
def org(db):
    add_org(db, ORG, "Acme")
    db.commit()
    return db


def test_a_server_row_keeps_its_sealed_token_and_tools(org):
    _server(org, "mcp_0123456789ab")
    org.commit()
    row = org.execute("SELECT * FROM mcp_servers WHERE id = 'mcp_0123456789ab'").fetchone()
    assert bytes(row["token_ciphertext"]) == b"sealed"
    assert (row["header_name"], row["status"], row["tools"]) == (
        "Authorization",
        "active",
        [{"id": "get_customer"}],
    )
    assert row["tools_listed_at"] is None and row["last_error"] is None and row["created_at"] is not None


def test_only_one_live_server_per_connector_key_and_per_name(org):
    _server(org, "mcp_000000000001")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _server(org, "mcp_000000000002", name="Other")
    org.rollback()
    _server(org, "mcp_000000000001")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _server(org, "mcp_000000000003", key="org-acme--crm-2", name="crm")
    org.rollback()
    _server(org, "mcp_000000000001", status="removed", token=None)
    _server(org, "mcp_000000000004")  # a removed server frees its key and name
    org.commit()


def test_a_live_server_needs_its_token(org):
    with pytest.raises(psycopg.errors.CheckViolation):
        _server(org, "mcp_000000000001", token=None)
    org.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        _server(org, "mcp_000000000001", status="paused")
    org.rollback()


def test_a_connection_may_reach_an_mcp_server(org):
    org.execute(
        "INSERT INTO connections (org_id, app, status, mode, connected_by, account_id) "
        "VALUES (%s, 'org-acme--crm', 'connected', 'mcp', 'uid', 'mcp_0123456789ab')",
        (ORG,),
    )
    org.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        org.execute(
            "INSERT INTO connections (org_id, app, status, mode, connected_by) "
            "VALUES (%s, 'gmail', 'connected', 'ftp', 'uid')",
            (ORG,),
        )
    org.rollback()
