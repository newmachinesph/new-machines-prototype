-- An installation of another workspace's listed pack holds the approved listing version it was added or last
-- updated at, not only the pack version: a version approved again with the same pack version (a wider
-- contract, a new price) changes nothing for the org until it updates. NULL for the platform's packs and
-- the org's own.

-- The ALTER takes an exclusive lock on installations: give up rather than queue behind a long transaction
-- (and block every reader queued behind it).
SET LOCAL lock_timeout = '5s';

ALTER TABLE installations ADD COLUMN listing_version_id text REFERENCES listing_versions(id);
