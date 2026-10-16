"""A custom MCP connector and its connection row, seeded without a server, for the routing, runtime and ops
tests."""

from psycopg.types.json import Jsonb

from app.defs import owners
from tests.team_seed import _own

SERVER_ID = "mcp_0123456789ab"
DEFAULTS = {"read": "permit", "write": "require_approval", "delete": "deny", "money": "deny"}
CUSTOMER_INPUT = {
    "type": "object",
    "properties": {"customer_id": {"type": "string"}},
    "required": ["customer_id"],
    "additionalProperties": False,
}
NOTE_INPUT = {
    "type": "object",
    "properties": {"customer_id": {"type": "string"}, "note": {"type": "string"}},
    "required": ["customer_id", "note"],
    "additionalProperties": False,
}


def connector_body(app: str = "Acme CRM", server_id: str = SERVER_ID) -> dict:
    return {
        "app": app,
        "transport": "mcp",
        "server": server_id,
        "tools": [
            {
                "id": "get_customer",
                "slug": "get_customer",
                "action_class": "read",
                "capability": "acme-crm.read",
                "description": "Look up a customer by id.",
                "input_schema": CUSTOMER_INPUT,
                "sample": {"id": "sample", "name": "sample", "email": "sample"},
            },
            {
                "id": "update_customer_note",
                "slug": "update_customer_note",
                "action_class": "write",
                "capability": "acme-crm.write",
                "description": "Replace the note on a customer.",
                "input_schema": NOTE_INPUT,
            },
        ],
        "defaults": dict(DEFAULTS),
    }


def custom_connector(db, org_id: str, name: str = "acme-crm", server_id: str = SERVER_ID) -> str:
    key = owners.org_key(org_id, name)
    _own(db, org_id, "connector", key, connector_body(server_id=server_id))
    return key


def mcp_connection(
    db, org_id: str, key: str, *, status: str = "connected", account: str | None = SERVER_ID, grants=()
) -> None:
    db.execute(
        "INSERT INTO connections (org_id, app, status, mode, grants, connected_by, account_id) "
        "VALUES (%s, %s, %s, 'mcp', %s, 'uid_ana', %s) ON CONFLICT (org_id, app) DO UPDATE SET "
        "status = EXCLUDED.status, grants = EXCLUDED.grants, account_id = EXCLUDED.account_id",
        (org_id, key, status, Jsonb(list(grants)), account),
    )
