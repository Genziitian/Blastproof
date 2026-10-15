// Used after a fenced write returns no rows, to tell already_done from lease_lost.
MATCH (t:Task {id: $task_id})
OPTIONAL MATCH (t)-[:NEXT]->(n:Task)
RETURN t.status AS status, t.epoch AS epoch, t.lease_owner AS lease_owner, n.id AS next_id
