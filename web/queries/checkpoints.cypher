// Agent timeline: every checkpoint on the incident's tasks, with who wrote it
// and under which fencing epoch.
MATCH (:Incident {key: $incident_key})<-[:FOR]-(t:Task)-[:HAS_CHECKPOINT]->(c:Checkpoint)
RETURN t.id AS task, c.n AS n, c.epoch AS epoch, c.agent AS agent, c.tool AS tool,
       c.args_json AS args_json, c.observation AS observation, c.at AS at
ORDER BY at
