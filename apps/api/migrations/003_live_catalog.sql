-- Live workspace, part 2: the values hires and app connections may hold, and memory items that belong to
-- one org and can be retracted.

ALTER TABLE installations
  ADD CONSTRAINT installations_reviewer_pool_check CHECK (reviewer_pool IN ('team','team_and_pool'));

ALTER TABLE connections
  ADD CONSTRAINT connections_status_check
  CHECK (status IN ('connected','not_connected','sandbox','needs_reauth'));

-- active: recalled by runs and listed; retracted: withdrawn by its org; quarantined: written before items
-- carried an org and with no run to take it from, so no org may read it.
ALTER TABLE memory_items
  ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','retracted','quarantined')),
  ADD COLUMN retracted_by text,
  ADD COLUMN retracted_at timestamptz;

-- A run writes its items with source "run:<run id>:<node>:<attempt>": give older ones their run's org.
UPDATE memory_items m SET org_id = r.org_id
  FROM runs r
 WHERE m.org_id IS NULL AND m.source LIKE 'run:%' AND r.id = split_part(m.source, ':', 2);

-- Shared items are the definition seed and what operators add in the console; any other item without an
-- org would otherwise be read by every org.
UPDATE memory_items SET status = 'quarantined'
 WHERE org_id IS NULL AND source NOT IN ('seed','console');
