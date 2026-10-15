// Which memories the decision considered, with the evidence for or against each.
// One USED edge per (memory, target) tried. The verdict is filled in later, once,
// by the learner (memory/queries/feedback.cypher).
MATCH (t:Task {id: $task_id})
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
MATCH (d:Decision {id: $decision_id})
UNWIND $used AS u
MATCH (m:Memory {id: u.id})
MERGE (d)-[r:USED {target: u.target}]->(m)
ON CREATE SET r.score = u.score, r.hops = u.hops, r.path = u.path,
              r.trust_at_use = u.trust, r.applied = u.applied, r.checks_json = u.checks_json
RETURN m.id AS id, r.target AS target
