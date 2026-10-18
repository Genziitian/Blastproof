// Root-cause suspects for a set of alerting services. Ranked by how many alerting
// services depend on each node (hits), how close it is (hops), then by FalkorDB's
// PageRank over DEPENDS_ON: how much of the whole system leans on that node, so a
// shared dependency beats a leaf when the walk alone can't tell them apart.
CALL algo.pageRank(NULL, 'DEPENDS_ON') YIELD node, score
WITH node, score WHERE node:Service OR node:Datastore
WITH collect([node.name, score]) AS ranks
MATCH (a:Service) WHERE a.name IN $alerting
MATCH p = (a)-[:DEPENDS_ON*1..3]->(c)
WITH c, count(DISTINCT a) AS hits, min(length(p)) AS hops, ranks
RETURN c.name AS name, labels(c)[0] AS label, c.kind AS kind, hits, hops,
       [r IN ranks WHERE r[0] = c.name | r[1]][0] AS pagerank
ORDER BY hits DESC, hops ASC, pagerank DESC, name ASC
