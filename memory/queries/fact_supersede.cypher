// A3 step 2: create one new version (safe to retry) and close older ones.
// Run only after fact_check says scope and source exist and the id is new
// or carries the same payload_hash. The agent's own (unconfirmed) reading
// never closes a version the engineer approved; only another approval does.
MATCH (scope {key: $scope_key}), (src {key: $source_key})
MERGE (new:Memory:Fact {id: $id})
ON CREATE SET new.lineage_id = $lineage, new.version = $version,
  new.subject = $s, new.predicate = $p, new.condition_family = $cond, new.object = $o,
  new.source = $source_kind, new.approved_by = $approver,
  new.valid_from = $valid_from, new.recorded_at = $scenario_now, new.status = 'active',
  new.helped = 0, new.misled = 0, new.prior_a = $a, new.prior_b = $b,
  new.trust = $a * 1.0 / ($a + $b), new.payload_hash = $hash
MERGE (new)-[:ABOUT]->(scope)
MERGE (new)-[:LEARNED_FROM]->(src)
WITH new
MATCH (old:Memory:Fact {lineage_id: $lineage})
WHERE old.id <> new.id AND old.status = 'active'
  AND (old.valid_to IS NULL OR old.valid_to > $valid_from)
  AND ($source_kind = 'human' OR old.source <> 'human')
SET old.valid_to = $valid_from
MERGE (new)-[:SUPERSEDES]->(old)
