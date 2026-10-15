// Evaluator: the notifications sent for an incident (who, how).
MATCH (:Incident {key: $incident_key})<-[:FOR]-(:Task)-[:EMITTED]->(a:Action)
RETURN a.recipient AS recipient, a.channel AS channel
