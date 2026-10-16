// Armed kill: investigations currently held under a lease, with how many steps
// their worker has checkpointed so far.
MATCH (t:Task {type: 'investigate', status: 'leased'})
OPTIONAL MATCH (t)-[:HAS_CHECKPOINT]->(c:Checkpoint)
RETURN t.id AS id, t.lease_owner AS owner, t.epoch AS epoch, count(c) AS steps
