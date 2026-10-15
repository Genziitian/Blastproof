// Extend the lease, only if this worker still holds it (full fence guard).
MATCH (t:Task {id: $task_id})
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
SET t.lease_until = timestamp() + $ttl_ms
RETURN t.id AS id, t.lease_until AS lease_until
