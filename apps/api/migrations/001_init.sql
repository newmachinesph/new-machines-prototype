CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE definition_versions (
  kind text NOT NULL, key text NOT NULL, version integer NOT NULL,
  digest text NOT NULL, body jsonb NOT NULL, files jsonb NOT NULL DEFAULT '{}'::jsonb,
  source text NOT NULL CHECK (source IN ('file','console')),
  published_by text NOT NULL, reason text NOT NULL, published_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, key, version)
);

CREATE TABLE runs (
  id text PRIMARY KEY, org_id text NOT NULL, pack_slug text NOT NULL, status text NOT NULL,
  snapshot jsonb NOT NULL, projection jsonb NOT NULL, input jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE SEQUENCE run_number START 2001;

CREATE TABLE receipt_entries (
  run_id text NOT NULL REFERENCES runs(id), seq integer NOT NULL, event_key text NOT NULL,
  at timestamptz NOT NULL DEFAULT now(), type text NOT NULL, node_id text, data jsonb NOT NULL,
  prev_hash text NOT NULL, hash text NOT NULL,
  PRIMARY KEY (run_id, seq), UNIQUE (run_id, event_key)
);

CREATE TABLE run_tasks (
  id text PRIMARY KEY, run_id text NOT NULL REFERENCES runs(id), node_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('human','approval')), status text NOT NULL,
  payload jsonb NOT NULL, result jsonb, created_at timestamptz NOT NULL DEFAULT now(),
  decided_by text, decided_at timestamptz
);

CREATE TABLE memory_items (
  id text PRIMARY KEY, space text NOT NULL, text text NOT NULL, source text NOT NULL,
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX memory_items_tsv ON memory_items USING gin (tsv);
CREATE INDEX memory_items_space ON memory_items (space);
