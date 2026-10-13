-- Live workspace (NM_WORKSPACE=live): one org per signed-in user, its members, hired packs, app connections
-- and API tokens. The demo workspace keeps serving fixtures and never reads these tables.

CREATE TABLE orgs (
  id text PRIMARY KEY,
  name text NOT NULL,
  plan text NOT NULL DEFAULT 'trial',
  monthly_cap_minor bigint NOT NULL DEFAULT 2500 CHECK (monthly_cap_minor >= 0),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- An invitation is a row with status 'invited' and no user yet; signing in with that verified email
-- accepts it. Emails are stored lower-case.
CREATE TABLE org_members (
  org_id text NOT NULL REFERENCES orgs(id),
  user_id text,
  email text,
  name text,
  role text NOT NULL CHECK (role IN ('owner','admin','member')),
  status text NOT NULL CHECK (status IN ('active','invited')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, email),
  UNIQUE (org_id, user_id),
  CHECK (status = 'invited' OR user_id IS NOT NULL)
);
CREATE INDEX org_members_user ON org_members (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX org_members_invited ON org_members (email) WHERE status = 'invited';

CREATE TABLE installations (
  org_id text NOT NULL REFERENCES orgs(id),
  pack_slug text NOT NULL,
  pack_version integer NOT NULL,
  cap_minor bigint NOT NULL CHECK (cap_minor > 0),
  reviewer_pool text NOT NULL,
  installed_by text NOT NULL,
  installed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, pack_slug)
);

CREATE TABLE connections (
  org_id text NOT NULL REFERENCES orgs(id),
  app text NOT NULL,
  status text NOT NULL,
  mode text NOT NULL CHECK (mode IN ('sandbox','composio')),
  grants jsonb NOT NULL DEFAULT '[]'::jsonb,
  connected_by text NOT NULL,
  connected_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, app)
);

-- Only a SHA-256 hash of each secret is kept; `prefix` is its first characters, for recognising a token.
CREATE TABLE api_tokens (
  id text PRIMARY KEY,
  org_id text NOT NULL REFERENCES orgs(id),
  user_id text NOT NULL,
  name text NOT NULL,
  prefix text NOT NULL,
  secret_hash text NOT NULL UNIQUE,
  scopes text[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);
CREATE INDEX api_tokens_owner ON api_tokens (org_id, user_id);

-- Null = the shared seed memory every org reads; otherwise the org that owns the item.
ALTER TABLE memory_items ADD COLUMN org_id text;
CREATE INDEX memory_items_org ON memory_items (org_id);

CREATE INDEX runs_org_created ON runs (org_id, created_at DESC);
