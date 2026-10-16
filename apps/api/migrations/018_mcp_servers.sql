-- An org's own MCP servers, connected as custom connectors (live workspace). The token is sealed with
-- AES-GCM under NM_SECRETS_KEY (app/secrets_box.py) and dropped when the server is removed; `tools` holds
-- the sorted tools with their switches; `last_error` is a code (unreachable | address_refused), never the
-- server's words. A connection reaches a server with mode 'mcp' and the server id as its account id.

-- The ALTER takes an exclusive lock on connections: give up rather than queue behind a long transaction
-- (and block every reader queued behind it).
SET LOCAL lock_timeout = '5s';

CREATE TABLE mcp_servers (
  id text PRIMARY KEY,
  org_id text NOT NULL REFERENCES orgs(id),
  connector_key text NOT NULL,
  name text NOT NULL,
  url text NOT NULL,
  header_name text NOT NULL DEFAULT 'Authorization',
  token_ciphertext bytea,
  token_last4 text,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','failing','removed')),
  tools jsonb NOT NULL DEFAULT '[]'::jsonb,
  tools_listed_at timestamptz,
  last_error text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status = 'removed' OR token_ciphertext IS NOT NULL)
);

CREATE UNIQUE INDEX mcp_servers_live_key ON mcp_servers (org_id, connector_key) WHERE status <> 'removed';
CREATE UNIQUE INDEX mcp_servers_live_name ON mcp_servers (org_id, lower(name)) WHERE status <> 'removed';

ALTER TABLE connections
  DROP CONSTRAINT connections_mode_check,
  ADD CONSTRAINT connections_mode_check CHECK (mode IN ('sandbox','composio','mcp'));
