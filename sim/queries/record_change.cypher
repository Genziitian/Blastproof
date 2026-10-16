// The world's deploy history: (:Person)-[:AUTHORED]->(:Change)-[:MODIFIED]->(:Service).
// Written by the simulator when a scenario starts, as a CI system would; nothing
// says which change (if any) caused an incident. Idempotent by key.
MATCH (s:Service {name: $service}), (p:Person {handle: $author})
MERGE (c:Change {key: $key})
ON CREATE SET c.kind = $kind, c.at = $at, c.summary = $summary
MERGE (p)-[:AUTHORED]->(c)
MERGE (c)-[:MODIFIED]->(s)
RETURN c.key AS key
