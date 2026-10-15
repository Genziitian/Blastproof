// Send a notification once per logical intent (e.g. 'inc-104:initial-notification').
// Recipient, channel and payload are fixed on first write and reused on retry.
// before = 'pending' -> sent now (ok); before = 'sent' -> already_done.
MATCH (t:Task {id: $task_id})
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
MERGE (a:Action {key: $intent_key})
ON CREATE SET a.kind = $kind, a.recipient = $recipient, a.channel = $channel,
              a.payload = $payload_json, a.status = 'pending', a.created_at = timestamp()
MERGE (t)-[:EMITTED]->(a)
WITH a, a.status AS before
SET a.status = 'sent', a.sent_at = coalesce(a.sent_at, timestamp())
RETURN a.key AS key, before, a.recipient AS recipient, a.channel AS channel
