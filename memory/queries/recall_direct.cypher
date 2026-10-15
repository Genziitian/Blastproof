// A1, 0 hops: memories pinned to an alerting service itself.
// $scenario_now is SIMULATED time, so a replayed scenario never sees later memory.
MATCH (a:Service)<-[:ABOUT]-(m:Memory)
WHERE a.name IN $alerting
  AND m.status = 'active'
  AND m.recorded_at <= $scenario_now
  AND m.valid_from <= $scenario_now
  AND (m.valid_to IS NULL OR $scenario_now < m.valid_to)
RETURN m.id AS id, a.name AS alerting, a.name AS target, 0 AS hops,
       [a.name] AS path, 1.0 AS weight, m.trust AS trust, m.recorded_at AS recorded_at
