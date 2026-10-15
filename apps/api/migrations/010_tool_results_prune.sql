-- tool_results rows are needed only while their run can still retry a connector call. Since this release
-- record_events deletes a run's rows when it appends the run's receipt.sealed entry; this removes the rows of
-- runs sealed before that, the payloads of reads (a retried read reads again, so none is kept any more), and
-- makes created_at NOT NULL so a later sweep can key on it.

DELETE FROM tool_results r
WHERE EXISTS (
  SELECT 1 FROM receipt_entries e WHERE e.run_id = r.run_id AND e.type = 'receipt.sealed'
);

DELETE FROM tool_results r
WHERE EXISTS (
  SELECT 1 FROM receipt_entries e
  WHERE e.run_id = r.run_id AND e.event_key = r.event_key
    AND e.type = 'tool.call' AND e.data->>'action_class' = 'read'
);

UPDATE tool_results SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE tool_results ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE tool_results ALTER COLUMN created_at SET DEFAULT now();
