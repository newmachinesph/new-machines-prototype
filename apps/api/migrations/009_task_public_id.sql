-- Workforce (sub-project B): the id a network reviewer knows a task by.
--
-- A human task's own id is built from its run id (`ht_<run>_<node>_<attempt>`, written by the worker), and a
-- network reviewer works for another org, whose run ids are not theirs to know. Network copies, claims,
-- submissions and earnings address the task by this unguessable id instead; the org's own team keeps the task
-- id. The column default fills the existing rows and every row the worker inserts, so its INSERT is unchanged.
ALTER TABLE run_tasks ADD COLUMN public_id text NOT NULL
  DEFAULT ('nt_' || substr(md5(random()::text || clock_timestamp()::text), 1, 20)) UNIQUE;
