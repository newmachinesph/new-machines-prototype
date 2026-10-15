-- Sub-project C: who owns a definition and who may see it. A definition with no row belongs to the platform
-- and is listed in the marketplace. An org's own definitions (built in the Studio) are private to it; their
-- keys are namespaced "org-<id>--<name>", which no platform key ever is.

-- The ALTER takes an exclusive lock on definition_versions: give up rather than queue behind a long
-- transaction (and block every reader queued behind it).
SET LOCAL lock_timeout = '5s';

ALTER TABLE definition_versions DROP CONSTRAINT definition_versions_source_check;
ALTER TABLE definition_versions ADD CONSTRAINT definition_versions_source_check
  CHECK (source IN ('file', 'console', 'builder'));

CREATE TABLE definition_owners (
  kind text NOT NULL,
  key text NOT NULL,
  owner_kind text NOT NULL CHECK (owner_kind IN ('platform', 'org', 'developer')),
  owner_id text,
  visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'marketplace')),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, key),
  CHECK ((owner_kind = 'platform') = (owner_id IS NULL))
);
CREATE INDEX definition_owners_owner ON definition_owners (owner_kind, owner_id);
