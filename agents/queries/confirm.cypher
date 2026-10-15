// The engineer confirmed the diagnosis. One write: record the feedback, mark the
// incident resolved, close the respond task and queue learning. The Learn task id
// is derived from the decision, so a crash before learning runs loses nothing.
MATCH (t:Task {id: $task_id})-[:FOR]->(i:Incident)
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
MATCH (d:Decision {id: $decision_id})
MATCH (root) WHERE (root:Service OR root:Datastore) AND root.name = d.root
MERGE (f:Feedback {id: $feedback_id})
ON CREATE SET f.verdict = 'confirmed', f.by = $by, f.at = timestamp()
MERGE (f)-[:ON]->(d)
MERGE (i)-[:TOUCHED {role: 'root'}]->(root)
SET i.status = 'resolved', i.resolved_at = $scenario_now,
    i.signature = d.family + ':' + coalesce(root.kind, 'service'),
    t.status = 'done', t.done_at = timestamp()
MERGE (l:Task {id: $learn_task_id})
ON CREATE SET l.type = 'learn', l.status = 'open', l.epoch = 0, l.attempts = 0,
              l.created_at = timestamp()
MERGE (l)-[:FOR]->(i)
RETURN l.id AS learn_task_id
