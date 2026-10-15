// Close a task this worker holds, with no follow-up task.
MATCH (t:Task {id: $task_id})
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
SET t.status = 'done', t.done_at = timestamp()
RETURN t.id AS id
