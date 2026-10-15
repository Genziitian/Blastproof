// Org change: a node's current owning team stops owning it at $at.
MATCH (n {name: $node})-[o:OWNED_BY]->(:Team)
WHERE (n:Service OR n:Datastore)
  AND o.valid_from < $at AND (o.valid_to IS NULL OR o.valid_to > $at)
SET o.valid_to = $at
RETURN count(o) AS closed
