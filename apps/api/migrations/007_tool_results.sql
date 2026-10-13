-- A permitted connector call's result, kept only so an activity retried after its commit landed can return
-- the same result without calling the connector again (retry idempotency). It is written in the same
-- transaction as the call's tool.call receipt entry and is keyed like it. The hash-chained receipt never holds
-- connector data, since a sealed receipt cannot be edited or deleted. No API reads this table. Its rows can be
-- pruned once their run reaches a terminal status (nothing prunes them yet).

CREATE TABLE tool_results (
  run_id text NOT NULL REFERENCES runs(id),
  event_key text NOT NULL,                         -- the tool.call receipt entry's event_key
  result jsonb NOT NULL,
  created_at timestamptz DEFAULT now(),
  PRIMARY KEY (run_id, event_key)
);
