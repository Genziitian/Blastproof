// Claim the oldest claimable task of a type and start a new fencing epoch.
// Lease time comes from the database clock, never from the worker.
MATCH (t:Task {type: $type})
WHERE (t.status = 'open' OR (t.status = 'leased' AND t.lease_until < timestamp()))
  AND t.attempts < $max_attempts
WITH t ORDER BY t.created_at LIMIT 1
SET t.status = 'leased', t.lease_owner = $instance,
    t.lease_until = timestamp() + $ttl_ms,
    t.attempts = t.attempts + 1, t.epoch = t.epoch + 1
RETURN t.id AS id, t.epoch AS epoch, t.attempts AS attempts
