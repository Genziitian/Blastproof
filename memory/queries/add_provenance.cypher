// Another confirmed incident supports an existing playbook: record it as a source
// and pin the playbook to this incident's root too, instead of writing a duplicate.
// (A bad-deploy playbook learned on checkout-api then also applies to search-svc.)
MATCH (p:Memory:Playbook {id: $id}), (i:Incident {key: $incident_key})
MATCH (root) WHERE (root:Service OR root:Datastore) AND root.name = $root
MERGE (p)-[:LEARNED_FROM]->(i)
MERGE (p)-[:ABOUT]->(root)
RETURN p.id AS id
