// Messages are stored verbatim and keyed, so a retried write adds nothing.
MATCH (s:Session {id: $session_id})
MERGE (m:Message {key: $key})
ON CREATE SET m.role = $role, m.text = $text, m.seq = $seq, m.at = $at
MERGE (m)-[:IN]->(s)
RETURN m.key AS key
