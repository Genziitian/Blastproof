// Another confirmed incident supports an existing playbook: record it as a source
// instead of writing a duplicate.
MATCH (p:Memory:Playbook {id: $id}), (i:Incident {key: $incident_key})
MERGE (p)-[:LEARNED_FROM]->(i)
RETURN p.id AS id
