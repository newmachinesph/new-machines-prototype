-- A network reviewer is anonymous to the buyer: a run's timeline names them "Network reviewer". Runs settled
-- before the worker did so show the reviewer's account id on the entry that resolved the task (actor
-- "human", ref = the task id); this names those entries the way the worker now does. The receipt entries
-- themselves stay as written: the buyer sees the timeline, and the receipt is hash-chained.
UPDATE runs r
SET projection = jsonb_set(
  r.projection,
  '{timeline}',
  (
    SELECT jsonb_agg(
      CASE
        WHEN item ->> 'actor' = 'human' AND item ->> 'ref' IN (
          SELECT t.id FROM run_tasks t
          WHERE t.run_id = r.id AND t.kind = 'human' AND t.payload ->> 'claimed_via' = 'network'
        )
        THEN item || '{"who": "Network reviewer"}'::jsonb
        ELSE item
      END
      ORDER BY n
    )
    FROM jsonb_array_elements(r.projection -> 'timeline') WITH ORDINALITY AS e(item, n)
  )
)
WHERE jsonb_typeof(r.projection -> 'timeline') = 'array'
  AND jsonb_array_length(r.projection -> 'timeline') > 0
  AND EXISTS (
    SELECT 1 FROM run_tasks t
    WHERE t.run_id = r.id AND t.kind = 'human' AND t.payload ->> 'claimed_via' = 'network'
      AND t.decided_by IS NOT NULL
  );
