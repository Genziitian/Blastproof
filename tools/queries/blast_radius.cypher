// Everything that depends on a node, with distance and customer impact.
MATCH (root {name: $node}) WHERE root:Service OR root:Datastore
MATCH p = (up:Service)-[:DEPENDS_ON*1..4]->(root)
RETURN up.name AS service, min(length(p)) AS hops, up.customer_facing AS customer_facing
ORDER BY hops ASC, service ASC
