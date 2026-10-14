-- Workforce (sub-project B): who reviews a hire's human tasks.

-- An org member with the reviewer capability reviews the org's tasks in /work. Before this migration every
-- member saw them, so every active or invited member keeps the capability; a new org's owner gets it at
-- provisioning, and a Reviewer invitation (role 'reviewer') carries it.
ALTER TABLE org_members DROP CONSTRAINT org_members_role_check;
ALTER TABLE org_members ADD CONSTRAINT org_members_role_check
  CHECK (role IN ('owner', 'admin', 'member', 'reviewer'));
ALTER TABLE org_members ADD COLUMN reviewer boolean NOT NULL DEFAULT false;
UPDATE org_members SET reviewer = true WHERE status IN ('active', 'invited');

-- The switch "Allow the New Machines reviewer network". Off (the default): none of the org's tasks is
-- offered to the network, whatever its hires choose.
ALTER TABLE orgs ADD COLUMN allow_network boolean NOT NULL DEFAULT false;

-- Per hire: team, network, or team_then_network (team first; the network after 30 minutes unclaimed).
-- 'team_and_pool' (the team and the New Machines pool) had no effect yet, since no task left its org; it
-- becomes team_then_network, which the switch above keeps inside the team until an owner allows the network.
ALTER TABLE installations DROP CONSTRAINT installations_reviewer_pool_check;
UPDATE installations SET reviewer_pool = 'team_then_network' WHERE reviewer_pool = 'team_and_pool';
ALTER TABLE installations ALTER COLUMN reviewer_pool SET DEFAULT 'team_then_network';
ALTER TABLE installations ADD CONSTRAINT installations_reviewer_pool_check
  CHECK (reviewer_pool IN ('team', 'network', 'team_then_network'));

-- A user who turned on "Review for the network" in /work. enabled: the user's own switch; status: set by
-- New Machines operators (a suspended reviewer is offered nothing).
CREATE TABLE network_reviewers (
  user_id text PRIMARY KEY,
  email text NOT NULL DEFAULT '',
  name text NOT NULL,
  languages text[] NOT NULL DEFAULT '{}',
  skills text[] NOT NULL DEFAULT '{}',
  enabled boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Open human tasks by age: the network's offers (app.review_routing).
CREATE INDEX run_tasks_open_human ON run_tasks (created_at) WHERE kind = 'human' AND status = 'open';
