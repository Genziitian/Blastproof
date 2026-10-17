// Arm B retrieval: nearest memories to the alert text by exact cosine distance,
// with the same validity rules as graph recall. Exact search over a few dozen
// memories is cheap, and exact by definition, so this arm is never handicapped
// by approximate search.
MATCH (node:Memory)
WHERE node.embedding IS NOT NULL
  AND node.status = 'active'
  AND node.recorded_at <= $scenario_now
  AND node.valid_from <= $scenario_now
  AND (node.valid_to IS NULL OR $scenario_now < node.valid_to)
WITH node, vec.cosineDistance(node.embedding, vecf32($vector)) AS distance
ORDER BY distance ASC, node.id ASC
LIMIT $k
OPTIONAL MATCH (node)-[:ABOUT]->(n)
RETURN node.id AS id, distance, node.trust AS trust,
       node.applies_to_kind AS kind, collect(n.name) AS about
