// Org change: a team owns a node from $at (idempotent).
MATCH (n {name: $node}), (t:Team {name: $team})
WHERE n:Service OR n:Datastore
MERGE (n)-[:OWNED_BY {valid_from: $at}]->(t)
RETURN t.name AS team
