-- Sub-project D: developer publishing. A workspace with a publisher profile lists its own agents and packs;
-- ops reviews every version; other workspaces see only approved versions (listed_definitions) and pay
-- itemized, simulated publisher fees (fee_lines). Money here is simulated: nothing is paid out.

SET LOCAL lock_timeout = '5s';

CREATE TABLE publishers (
  org_id text PRIMARY KEY REFERENCES orgs(id),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  description text NOT NULL DEFAULT '',
  payout_note text NOT NULL DEFAULT '',          -- simulated payout details
  enabled boolean NOT NULL DEFAULT true,         -- off: no new submissions; listings keep the name
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE listings (
  id text PRIMARY KEY,                           -- lst_<12 hex>
  kind text NOT NULL CHECK (kind IN ('agent', 'pack')),
  definition_key text NOT NULL,                  -- the publisher's own key, org-<id>--<name>
  publisher_org_id text NOT NULL REFERENCES orgs(id),
  name text NOT NULL,                            -- the definition's name at the newest approved version
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'listed', 'unlisted')),
  price_minor bigint NOT NULL DEFAULT 0 CHECK (price_minor >= 0),   -- the current approved version's
  current_version_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (kind, definition_key),
  CHECK (status = 'pending' OR current_version_id IS NOT NULL)
);
CREATE INDEX listings_publisher ON listings (publisher_org_id);

CREATE TABLE listing_versions (
  id text PRIMARY KEY,                           -- lsv_<12 hex>
  listing_id text NOT NULL REFERENCES listings(id),
  definition_version integer NOT NULL,           -- the agent's or pack's own registry version
  definitions jsonb NOT NULL,                    -- [{kind, key, version}] it exposes once approved
  price_minor bigint NOT NULL CHECK (price_minor >= 0),   -- per run (pack) or per call (agent)
  status text NOT NULL CHECK (status IN
    ('checking', 'checks_failed', 'in_review', 'approved', 'changes_requested', 'rejected')),
  checks jsonb NOT NULL DEFAULT '[]',            -- [{name, state, detail, run_id?}]
  check_run_id text REFERENCES runs(id),         -- the sandbox run of the automatic checks
  check_input jsonb,
  submitted_at timestamptz NOT NULL DEFAULT now(),
  submitted_by text NOT NULL,
  decided_at timestamptz,
  decided_by text,
  note text NOT NULL DEFAULT '',
  UNIQUE (listing_id, id),                       -- target of listings_current_version and fee_lines
  CHECK ((status IN ('approved', 'changes_requested', 'rejected')) = (decided_at IS NOT NULL))
);
CREATE UNIQUE INDEX listing_versions_one_open ON listing_versions (listing_id)
  WHERE status IN ('checking', 'in_review');
CREATE INDEX listing_versions_listing ON listing_versions (listing_id, submitted_at DESC);
CREATE INDEX listing_versions_status ON listing_versions (status);

-- A listing's current version is one of its own versions.
ALTER TABLE listings ADD CONSTRAINT listings_current_version
  FOREIGN KEY (id, current_version_id) REFERENCES listing_versions(listing_id, id);

-- The versions other workspaces may use: the current approved bundle of every listed listing.
CREATE TABLE listed_definitions (
  kind text NOT NULL,
  key text NOT NULL,
  version integer NOT NULL,
  listing_id text NOT NULL REFERENCES listings(id),
  publisher_org_id text NOT NULL,
  PRIMARY KEY (kind, key),
  FOREIGN KEY (kind, key, version) REFERENCES definition_versions(kind, key, version)
);
CREATE INDEX listed_definitions_listing ON listed_definitions (listing_id);

-- One row per charge: a pack's per-run fee at run start (event_key 'pack'), an agent's per-call fee per agent
-- step attempt. Written once at the pinned version's price; never updated.
CREATE TABLE fee_lines (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL REFERENCES runs(id),
  event_key text NOT NULL,
  listing_id text NOT NULL REFERENCES listings(id),
  listing_version_id text NOT NULL REFERENCES listing_versions(id),
  buyer_org_id text NOT NULL REFERENCES orgs(id),
  publisher_org_id text NOT NULL REFERENCES orgs(id),
  kind text NOT NULL CHECK (kind IN ('pack_run', 'agent_call')),
  quantity integer NOT NULL CHECK (quantity > 0),
  unit_minor bigint NOT NULL CHECK (unit_minor >= 0),
  amount_minor bigint NOT NULL,
  publisher_share_minor bigint NOT NULL CHECK (publisher_share_minor >= 0),
  platform_share_minor bigint NOT NULL CHECK (platform_share_minor >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, event_key),
  FOREIGN KEY (listing_id, listing_version_id) REFERENCES listing_versions(listing_id, id),  -- its own version
  CHECK (amount_minor = quantity * unit_minor),
  CHECK (publisher_share_minor + platform_share_minor = amount_minor),
  CHECK (publisher_share_minor = (amount_minor * 80) / 100),
  CHECK (buyer_org_id <> publisher_org_id)
);
CREATE INDEX fee_lines_publisher_at ON fee_lines (publisher_org_id, created_at);
CREATE INDEX fee_lines_listing_at ON fee_lines (listing_id, created_at);
CREATE INDEX fee_lines_buyer_at ON fee_lines (buyer_org_id, created_at);

CREATE OR REPLACE FUNCTION fee_lines_never_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'fee lines never change once written';
END
$$;
CREATE TRIGGER fee_lines_no_update BEFORE UPDATE OR DELETE ON fee_lines
  FOR EACH ROW EXECUTE FUNCTION fee_lines_never_change();

ALTER TABLE ops_audit DROP CONSTRAINT ops_audit_target_type_check;
ALTER TABLE ops_audit ADD CONSTRAINT ops_audit_target_type_check CHECK (target_type IN
  ('tenant', 'pack', 'connector', 'reviewer', 'guardrail', 'incident', 'definition', 'memory', 'listing'));
