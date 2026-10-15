-- Runs settled before the worker named a network review's verdict (`app.worker.activities._shown_decision`,
-- `app.runtime.projection.VERDICT_TITLES`): the timeline entry that resolved a network-claimed task still
-- reads "Resolved the task" (migration 014 renamed its `who` only). It is titled by the task's verdict, with
-- the projection's titles; a task whose verdict is unknown keeps its title. Nothing else in the projection
-- changes (spend stays as posted), and the receipt entries stay as written (the buyer sees the timeline; the
-- receipt is hash-chained). Idempotent: a title changes only while it still reads "Resolved the task", and a
-- run with no such entry for a network claim with a known verdict is not rewritten.
WITH titles(verdict, title) AS (
  VALUES
    ('APPROVED', 'Approved the result'),
    ('REVISION_REQUIRED', 'Sent back with corrections'),
    ('REJECTED', 'Rejected the result'),
    ('ESCALATED', 'Escalated the result')
),
network_reviews AS (
  SELECT t.run_id, t.id, v.title
  FROM run_tasks t
  JOIN titles v ON v.verdict = t.result ->> 'verdict'
  WHERE t.kind = 'human' AND t.payload ->> 'claimed_via' = 'network'
)
UPDATE runs r
SET projection = jsonb_set(
  r.projection,
  '{timeline}',
  (
    SELECT jsonb_agg(
      CASE
        WHEN item ->> 'actor' = 'human' AND item ->> 'title' = 'Resolved the task' AND n.title IS NOT NULL
        THEN item || jsonb_build_object('title', n.title)
        ELSE item
      END
      ORDER BY e.n
    )
    FROM jsonb_array_elements(r.projection -> 'timeline') WITH ORDINALITY AS e(item, n)
    LEFT JOIN network_reviews n ON n.run_id = r.id AND n.id = item ->> 'ref'
  )
)
WHERE jsonb_typeof(r.projection -> 'timeline') = 'array'
  AND EXISTS (
    SELECT 1
    FROM jsonb_array_elements(r.projection -> 'timeline') AS i
    JOIN network_reviews n ON n.run_id = r.id AND n.id = i ->> 'ref'
    WHERE i ->> 'actor' = 'human' AND i ->> 'title' = 'Resolved the task'
  );
