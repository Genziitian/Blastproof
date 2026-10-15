// The engineer rejected the diagnosis. The incident goes to review, and a Learn
// task is still queued so any playbook that led the agent astray loses trust.
MATCH (t:Task {id: $task_id})-[:FOR]->(i:Incident)
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
MATCH (d:Decision {id: $decision_id})
MERGE (f:Feedback {id: $feedback_id})
ON CREATE SET f.verdict = 'rejected', f.by = $by, f.at = timestamp()
MERGE (f)-[:ON]->(d)
SET i.status = 'needs_review', t.status = 'done', t.done_at = timestamp()
MERGE (l:Task {id: $learn_task_id})
ON CREATE SET l.type = 'learn', l.status = 'open', l.epoch = 0, l.attempts = 0,
              l.created_at = timestamp()
MERGE (l)-[:FOR]->(i)
RETURN l.id AS learn_task_id
