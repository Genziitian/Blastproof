// Header chip: how big this company's graph is right now.
MATCH (n)
WITH count(n) AS nodes
OPTIONAL MATCH ()-[r]->()
RETURN nodes, count(r) AS edges
