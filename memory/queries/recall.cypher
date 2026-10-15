// A1, 1-2 hops: walk DOWNSTREAM only (an alerting service fails because
// something it depends on failed), so hub services don't drag in unrelated memory.
// If *0..2 works in your FalkorDB version, this and recall_direct can merge.
MATCH (a:Service) WHERE a.name IN $alerting
MATCH p = (a)-[:DEPENDS_ON*1..2]->(n)
MATCH (n)<-[:ABOUT]-(m:Memory)
WHERE m.status = 'active'
  AND m.recorded_at <= $scenario_now
  AND m.valid_from <= $scenario_now
  AND (m.valid_to IS NULL OR $scenario_now < m.valid_to)
RETURN m.id AS id, a.name AS alerting, n.name AS target, length(p) AS hops,
       [x IN nodes(p) | x.name] AS path, 1.0 AS weight,
       m.trust AS trust, m.recorded_at AS recorded_at
