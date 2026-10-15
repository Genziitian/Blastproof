// What recall returned, written before any of it is checked, so the Memory Lens
// can show it while the investigation runs. Fenced like every task write.
MATCH (t:Task {id: $task_id})
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
SET t.recalled_json = $recalled_json
RETURN t.id AS id
