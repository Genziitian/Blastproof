// Org change: a person goes on call for a team from $at (idempotent).
MATCH (p:Person {handle: $handle}), (t:Team {name: $team})
MERGE (p)-[:ON_CALL {valid_from: $at}]->(t)
RETURN p.handle AS on_call
