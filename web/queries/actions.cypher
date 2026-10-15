// Pager log: every action sent for the incident (there should be exactly one).
MATCH (:Incident {key: $incident_key})<-[:FOR]-(t:Task)-[:EMITTED]->(a:Action)
RETURN a.key AS key, a.kind AS kind, a.recipient AS recipient, a.channel AS channel,
       a.status AS status, a.payload AS payload, a.created_at AS created_at,
       a.sent_at AS sent_at, t.id AS task
ORDER BY created_at
