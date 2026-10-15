// Tasks whose lease expired after the last allowed attempt are flagged for a human.
MATCH (t:Task)
WHERE t.status = 'leased' AND t.lease_until < timestamp() AND t.attempts >= $max_attempts
SET t.status = 'stuck'
RETURN t.id AS id
