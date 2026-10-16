// Recap: how far the investigation got, and which workers did it.
MATCH (:Incident {key: $incident_key})<-[:FOR]-(t:Task {type: 'investigate'})
OPTIONAL MATCH (t)-[:HAS_CHECKPOINT]->(c:Checkpoint)
RETURN t.status AS status, count(c) AS steps, collect(DISTINCT c.agent) AS agents,
       max(c.epoch) AS epochs
