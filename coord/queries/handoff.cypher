// Close this task and open the next one. The next id is derived, so a retry
// finds the same task instead of creating a second one.
MATCH (t:Task {id: $task_id})-[:FOR]->(i:Incident)
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
SET t.status = 'done', t.done_at = timestamp()
MERGE (n:Task {id: $task_id + ':next'})
ON CREATE SET n.type = $next_type, n.status = 'open', n.epoch = 0,
              n.attempts = 0, n.created_at = timestamp()
MERGE (t)-[:NEXT]->(n)
MERGE (n)-[:FOR]->(i)
RETURN n.id AS next_id
