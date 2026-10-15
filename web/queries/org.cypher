// Who owns each node and who is on call for each team at scenario time $at.
MATCH (t:Team)
OPTIONAL MATCH (p:Person)-[oc:ON_CALL]->(t)
  WHERE oc.valid_from <= $at AND (oc.valid_to IS NULL OR $at < oc.valid_to)
OPTIONAL MATCH (n)-[o:OWNED_BY]->(t)
  WHERE o.valid_from <= $at AND (o.valid_to IS NULL OR $at < o.valid_to)
RETURN t.name AS team, collect(DISTINCT p.handle) AS on_call, collect(DISTINCT n.name) AS owns
ORDER BY team
