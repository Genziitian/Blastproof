// A4: a candidate playbook from a confirmed incident. Idempotent by id (derived
// from the decision), pinned ABOUT the root it was learned on, sourced to the incident.
// Writes nothing if another active playbook already has this signature (two learners
// racing on the same lesson): the caller then adds this incident as its source.
MATCH (i:Incident {key: $incident_key})
MATCH (root) WHERE (root:Service OR root:Datastore) AND root.name = $root
OPTIONAL MATCH (other:Memory:Playbook {signature: $signature})
WHERE other.status = 'active' AND other.id <> $id
WITH i, root, count(other) AS others
WHERE others = 0
MERGE (p:Memory:Playbook {id: $id})
ON CREATE SET p.lineage_id = $signature, p.version = 1,
              p.signature = $signature, p.family = $family,
              p.applies_to_kind = $applies_to_kind, p.params_json = $params_json,
              p.preconditions_json = $preconditions_json, p.steps_json = $steps_json,
              p.conclusion = $conclusion, p.stop_if = $stop_if,
              p.payload_hash = $payload_hash, p.source = 'agent',
              p.valid_from = $scenario_now, p.recorded_at = $scenario_now,
              p.status = 'active', p.helped = 0, p.misled = 0,
              p.prior_a = 1, p.prior_b = 1, p.trust = 0.5
MERGE (p)-[:ABOUT]->(root)
MERGE (p)-[:LEARNED_FROM]->(i)
RETURN p.id AS id, p.payload_hash AS payload_hash
