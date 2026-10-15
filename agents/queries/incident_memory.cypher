// Memory Lens, in brief: every memory the incident's decision considered.
MATCH (i:Incident {key: $incident_key})<-[:FOR]-(d:Decision)-[u:USED]->(m:Memory)
RETURN m.id AS memory, u.target AS target, u.applied AS applied, u.verdict AS verdict,
       u.score AS score
ORDER BY score DESC
