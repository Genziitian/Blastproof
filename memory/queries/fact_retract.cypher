// A3: the engineer did not confirm the agent's reading of their message, so
// close it. Nothing is deleted or rewritten; the version just stops being valid
// from the moment they answered (it stays in the history, struck through).
MATCH (f:Memory:Fact)
WHERE f.id IN $ids AND f.source = 'agent' AND f.status = 'active'
  AND (f.valid_to IS NULL OR f.valid_to > $at)
SET f.valid_to = $at
RETURN f.id AS id
