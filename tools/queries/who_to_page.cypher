// Owner team and on-call engineer for a node, as they were at scenario time $at.
MATCH (n {name: $node})-[o:OWNED_BY]->(team:Team)
WHERE (n:Service OR n:Datastore)
  AND o.valid_from <= $at AND (o.valid_to IS NULL OR $at < o.valid_to)
OPTIONAL MATCH (p:Person)-[oc:ON_CALL]->(team)
WHERE oc.valid_from <= $at AND (oc.valid_to IS NULL OR $at < oc.valid_to)
RETURN team.name AS team, team.channel AS channel, p.handle AS on_call, p.name AS on_call_name
