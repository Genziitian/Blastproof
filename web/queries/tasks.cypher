// Agent timeline: the incident's tasks with their claims and current lease.
// lease_left_ms uses the database clock, the same clock the fence uses.
MATCH (:Incident {key: $incident_key})<-[:FOR]-(t:Task)
RETURN t.id AS id, t.type AS type, t.status AS status, t.epoch AS epoch,
       t.attempts AS attempts, t.lease_owner AS owner,
       t.lease_until - timestamp() AS lease_left_ms, t.claimed_by AS claimed_by,
       t.claimed_at AS claimed_at, t.recalled_json AS recalled_json,
       t.created_at AS created_at, t.done_at AS done_at
ORDER BY created_at
