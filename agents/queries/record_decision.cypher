// The investigator's root-cause decision. Immutable once written.
MATCH (t:Task {id: $task_id})-[:FOR]->(i:Incident)
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
MERGE (d:Decision {id: $decision_id})
ON CREATE SET d.kind = 'root_cause', d.root = $root, d.family = $family,
              d.summary = $summary, d.evidence_steps = $evidence_steps,
              d.agent = $instance, d.task_id = $task_id, d.epoch = $epoch,
              d.at = timestamp(), d.scenario_at = $scenario_now
MERGE (d)-[:FOR]->(i)
SET i.status = 'diagnosed'
RETURN d.id AS id, d.epoch AS written_by_epoch
