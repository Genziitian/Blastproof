// One war-room session per engineer per incident.
MATCH (p:Person {key: $person_key}), (i:Incident {key: $incident_key})
MERGE (s:Session {id: $session_id})
ON CREATE SET s.started_at = $scenario_now
MERGE (s)-[:WITH]->(p)
MERGE (s)-[:CONCERNS]->(i)
RETURN s.id AS id
