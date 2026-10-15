MATCH (a:Action {key: $intent_key})
RETURN a.key AS key, a.status AS status, a.recipient AS recipient, a.channel AS channel
