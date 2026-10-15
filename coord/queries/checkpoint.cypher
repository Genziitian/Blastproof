// Durable, idempotent checkpoint for step n. Written BEFORE the next step starts.
MATCH (t:Task {id: $task_id})
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
MERGE (c:Checkpoint {cid: $cid})
ON CREATE SET c.task_id = $task_id, c.n = $n, c.epoch = $epoch, c.agent = $instance,
              c.tool = $tool,
              c.args_json = $args_json, c.observation = $observation,
              c.at = timestamp(), c.scenario_at = $scenario_now
MERGE (t)-[:HAS_CHECKPOINT]->(c)
RETURN c.n AS n, c.epoch AS written_by_epoch
