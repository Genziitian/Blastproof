// Evaluator: every memory an incident's decision considered, with its family,
// so a scorer can tell a misleading memory from a rejected one.
MATCH (i:Incident {key: $incident_key})<-[:FOR]-(d:Decision)-[u:USED]->(m:Memory)
RETURN m.id AS memory, m.family AS family, u.target AS target, u.applied AS applied,
       u.verdict AS verdict
