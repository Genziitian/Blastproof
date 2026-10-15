// War room: the conversation on an incident, in order.
MATCH (:Incident {key: $incident_key})<-[:CONCERNS]-(s:Session)<-[:IN]-(m:Message)
MATCH (s)-[:WITH]->(p:Person)
RETURN s.id AS session, p.handle AS handle, m.key AS key, m.role AS role, m.text AS text,
       m.seq AS seq
ORDER BY seq
