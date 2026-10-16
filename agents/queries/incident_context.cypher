// Investigator: the incident behind a task, its alerting services and alert texts.
MATCH (t:Task {id: $task_id})-[:FOR]->(i:Incident)
OPTIONAL MATCH (i)<-[:PART_OF]-(a:Alert)-[:FIRED_ON]->(s:Service)
RETURN i.key AS incident_key, i.id AS incident_id, i.observed_at AS observed_at,
       collect(DISTINCT s.name) AS alerting, collect(DISTINCT a.text) AS alert_texts
