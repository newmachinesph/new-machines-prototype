-- Live app connections: each org connection is either sandbox data or the org's own account through
-- Composio, whatever NM_CONNECTOR_MODE says. A Composio connection is `pending` from its sign-in link until
-- Composio reports the account ACTIVE, and keeps the Composio connected account id it was made with (also
-- after a disconnect whose removal at Composio failed, so the next connect can retry it).

-- The ALTER takes an exclusive lock on connections: give up rather than queue behind a long transaction
-- (and block every reader queued behind it).
SET LOCAL lock_timeout = '5s';

ALTER TABLE connections
  ADD COLUMN account_id text,
  DROP CONSTRAINT connections_status_check,
  ADD CONSTRAINT connections_status_check
    CHECK (status IN ('connected','not_connected','sandbox','needs_reauth','pending'));
