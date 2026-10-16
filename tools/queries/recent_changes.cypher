// Deploys and config changes to a service between $since and $now (scenario time),
// with who made them: a two-hop walk Person -> Change -> Service.
MATCH (p:Person)-[:AUTHORED]->(c:Change)-[:MODIFIED]->(s:Service {name: $service})
WHERE c.at >= $since AND c.at <= $now
RETURN s.name AS service, c.kind AS kind, c.at AS at_ms, c.summary AS summary,
       p.handle AS author
ORDER BY at_ms
