// The engineer's recent conversations, newest first, so a new session can resume.
MATCH (p:Person {key: $person_key})<-[:WITH]-(s:Session)<-[:IN]-(m:Message)
MATCH (s)-[:CONCERNS]->(i:Incident)
RETURN i.id AS incident, m.role AS role, m.text AS text, m.at AS at
ORDER BY m.at DESC, m.seq DESC
LIMIT $limit
