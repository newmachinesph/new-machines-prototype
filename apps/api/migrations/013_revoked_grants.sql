-- A grant a person revoked stays revoked. Nothing that recomputes a connection's grants (connecting the app
-- again, to sandbox data or a real account; the sync that finds a real account ACTIVE; a new hire) brings it
-- back until someone grants it again explicitly. Entries are {install, capability}.

-- The ALTER takes an exclusive lock on connections: give up rather than queue behind a long transaction
-- (and block every reader queued behind it).
SET LOCAL lock_timeout = '5s';

ALTER TABLE connections ADD COLUMN revoked_grants jsonb NOT NULL DEFAULT '[]'::jsonb;
