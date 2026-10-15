// The company's dependency graph, for the map panel.
MATCH (n) WHERE n:Service OR n:Datastore
OPTIONAL MATCH (n)-[:DEPENDS_ON]->(m)
RETURN n.name AS name, n.kind AS kind, n.customer_facing AS customer_facing,
       collect(m.name) AS depends_on
ORDER BY name
