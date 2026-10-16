// Learner: the oldest active playbook with this signature, so a repeat adds a source
// instead of a duplicate playbook.
MATCH (p:Memory:Playbook {signature: $signature})
WHERE p.status = 'active'
RETURN p.id AS id
ORDER BY p.recorded_at ASC
LIMIT 1
