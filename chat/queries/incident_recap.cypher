// "Where did we leave <incident>?": the stored conversation with its outcome.
MATCH (s:Session)-[:CONCERNS]->(i:Incident {key: $incident_key})
MATCH (m:Message)-[:IN]->(s)
OPTIONAL MATCH (i)<-[:FOR]-(d:Decision {kind: 'root_cause'})
OPTIONAL MATCH (d)<-[:ON]-(f:Feedback)
RETURN i.status AS status, d.root AS root, d.family AS family, f.verdict AS verdict,
       m.role AS role, m.text AS text, m.seq AS seq
ORDER BY seq
