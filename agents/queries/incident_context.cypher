MATCH (t:Task {id: $task_id})-[:FOR]->(i:Incident)
OPTIONAL MATCH (i)<-[:PART_OF]-(:Alert)-[:FIRED_ON]->(s:Service)
RETURN i.key AS incident_key, i.id AS incident_id, i.observed_at AS observed_at,
       collect(DISTINCT s.name) AS alerting
