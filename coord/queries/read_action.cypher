// Read an action by its intent key (who it went to, and whether it was sent).
MATCH (a:Action {key: $intent_key})
RETURN a.key AS key, a.status AS status, a.recipient AS recipient, a.channel AS channel
