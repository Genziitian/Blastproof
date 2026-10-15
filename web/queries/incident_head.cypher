// UI: one incident with its alerts and, once made, the decision and the verdict.
MATCH (i:Incident {key: $incident_key})
OPTIONAL MATCH (i)<-[:PART_OF]-(a:Alert)-[:FIRED_ON]->(s:Service)
OPTIONAL MATCH (i)<-[:FOR]-(d:Decision)
OPTIONAL MATCH (d)<-[:ON]-(f:Feedback)
RETURN i.key AS key, i.id AS id, i.status AS status, i.observed_at AS observed_at,
       collect(DISTINCT s.name) AS alerting, collect(DISTINCT a.text) AS alert_texts,
       d.id AS decision_id, d.root AS root, d.family AS family, d.summary AS summary,
       d.agent AS decided_by, d.epoch AS decided_epoch, d.evidence_steps AS evidence_steps,
       f.verdict AS verdict, f.by AS verdict_by
