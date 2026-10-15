// Work done so far on a task, in order. A taking-over worker reads this first.
MATCH (t:Task {id: $task_id})-[:HAS_CHECKPOINT]->(c:Checkpoint)
RETURN c.n AS n, c.tool AS tool, c.args_json AS args_json,
       c.observation AS observation, c.epoch AS epoch
ORDER BY c.n
