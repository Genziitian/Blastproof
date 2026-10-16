// Responder: the root-cause decision behind a respond task.
MATCH (t:Task {id: $task_id})-[:FOR]->(i:Incident)<-[:FOR]-(d:Decision {kind: 'root_cause'})
RETURN i.key AS incident_key, i.id AS incident_id, i.observed_at AS observed_at,
       d.id AS decision_id, d.root AS root, d.family AS family, d.summary AS summary,
       d.evidence_steps AS evidence_steps
ORDER BY d.at DESC
LIMIT 1
