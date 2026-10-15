// The G1 pass check: every task on the incident with its checkpoints and actions.
MATCH (i:Incident {key: $incident_key})<-[:FOR]-(t:Task)
OPTIONAL MATCH (t)-[:HAS_CHECKPOINT]->(c:Checkpoint)
OPTIONAL MATCH (t)-[:EMITTED]->(a:Action)
RETURN t.id AS task, t.type AS type, t.status AS status, t.created_at AS created_at,
       count(DISTINCT c) AS checkpoints, count(DISTINCT a) AS actions
ORDER BY created_at
