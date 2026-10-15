// Nodes the alerting services depend on (1-3 hops downstream), ranked by how
// many alerting services reach them, then by distance.
MATCH (a:Service) WHERE a.name IN $alerting
MATCH p = (a)-[:DEPENDS_ON*1..3]->(c)
WITH c, count(DISTINCT a) AS hits, min(length(p)) AS hops
RETURN c.name AS name, labels(c)[0] AS label, c.kind AS kind, hits, hops
ORDER BY hits DESC, hops ASC, name ASC
