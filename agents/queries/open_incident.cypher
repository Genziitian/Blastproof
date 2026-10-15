// Triage: one Incident per alert group, idempotent by key. observed_at is the
// scenario time every worker uses for this incident.
MERGE (i:Incident {key: $incident_key})
ON CREATE SET i.id = $incident_id, i.status = 'open', i.observed_at = $observed_at,
              i.opened_at = timestamp()
WITH i
UNWIND $alerts AS al
MATCH (s:Service) WHERE s.name = al.service
MERGE (a:Alert {key: al.key})
ON CREATE SET a.signal = al.signal, a.text = al.text, a.fired_at = al.fired_at
MERGE (a)-[:FIRED_ON]->(s)
MERGE (a)-[:PART_OF]->(i)
MERGE (i)-[:TOUCHED {role: 'alerting'}]->(s)
RETURN count(a) AS alerts
