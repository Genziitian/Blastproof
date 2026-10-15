MATCH (i:Incident {key: $incident_key})
OPTIONAL MATCH (i)<-[:FOR]-(d:Decision)
OPTIONAL MATCH (d)<-[:ON]-(f:Feedback)
OPTIONAL MATCH (i)<-[:FOR]-(:Task)-[:EMITTED]->(a:Action)
RETURN i.status AS status, i.signature AS signature, d.root AS root, d.family AS family,
       f.verdict AS verdict, collect(DISTINCT a.recipient) AS notified
