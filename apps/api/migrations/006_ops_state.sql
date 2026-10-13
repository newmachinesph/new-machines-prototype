-- Ops state of the live workspace: connector settings Ops changed (a connector without a row keeps its
-- definition's defaults and is enabled), platform switches such as pause_all_runs, and the ops audit log.

CREATE TABLE connector_settings (
  connector_key text PRIMARY KEY,                  -- a connector definition key, e.g. "gmail"
  status text NOT NULL DEFAULT 'enabled' CHECK (status IN ('enabled', 'disabled')),
  defaults jsonb,                                  -- {read, write, delete, money}; NULL = the definition's defaults
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE platform_settings (
  key text PRIMARY KEY,                            -- "pause_all_runs"
  value jsonb NOT NULL,                            -- {"enabled": true}
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops_audit (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  actor_email text NOT NULL,
  action text NOT NULL,                            -- e.g. connector.disable, tenant.suspend, guardrail.set
  target_type text NOT NULL CHECK (target_type IN
    ('tenant', 'pack', 'connector', 'reviewer', 'guardrail', 'incident', 'definition', 'memory')),
  target_id text NOT NULL,
  reason text NOT NULL DEFAULT '',
  data jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ops_audit_at ON ops_audit (at DESC);
-- One target's history, and a tenant's latest suspend reason.
CREATE INDEX ops_audit_target ON ops_audit (target_type, target_id, at DESC);

-- The ops console's day windows: today's tool calls per connector and runs by creation time.
CREATE INDEX receipt_entries_tool_call_at ON receipt_entries (at) WHERE type = 'tool.call';
CREATE INDEX runs_created ON runs (created_at);

-- The pause switch starts off, attributed to the system rather than to an operator.
INSERT INTO platform_settings (key, value, updated_by) VALUES ('pause_all_runs', '{"enabled": false}', 'system')
ON CONFLICT DO NOTHING;
