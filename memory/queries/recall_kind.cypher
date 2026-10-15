// A1b: playbooks learned on another datastore of the same kind (e.g. any postgres),
// at half weight. Restricted to Datastore so service-level playbooks stay specific.
MATCH (a:Service) WHERE a.name IN $alerting
MATCH p = (a)-[:DEPENDS_ON*1..2]->(n:Datastore)
MATCH (m:Memory:Playbook)
WHERE m.applies_to_kind = n.kind
  AND m.status = 'active'
  AND m.recorded_at <= $scenario_now
  AND m.valid_from <= $scenario_now
  AND (m.valid_to IS NULL OR $scenario_now < m.valid_to)
RETURN m.id AS id, a.name AS alerting, n.name AS target, length(p) AS hops,
       [x IN nodes(p) | x.name] AS path, 0.5 AS weight,
       m.trust AS trust, m.recorded_at AS recorded_at
