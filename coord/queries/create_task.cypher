// Create a task for an incident. Idempotent by task id.
// Tasks MUST start with epoch 0 and attempts 0: null + 1 is null, which would
// make every fenced write fail silently.
MATCH (i:Incident {key: $incident_key})
MERGE (t:Task {id: $task_id})
ON CREATE SET t.type = $type, t.status = 'open', t.epoch = 0, t.attempts = 0,
              t.created_at = timestamp()
MERGE (t)-[:FOR]->(i)
RETURN t.id AS id, t.status AS status
