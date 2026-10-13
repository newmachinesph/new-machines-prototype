-- A member who accepts an invitation to another workspace keeps their row, as 'inactive', in a workspace
-- they leave that is not empty: one active workspace per user. A declined invitation is deleted, not kept. Invitations are
-- accepted explicitly (POST /v1/invitations/{org_id}:accept), never by signing in.
ALTER TABLE org_members DROP CONSTRAINT org_members_status_check;
ALTER TABLE org_members ADD CONSTRAINT org_members_status_check
  CHECK (status IN ('active','invited','inactive'));
