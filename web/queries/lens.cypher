// Memory Lens: every memory the incident's decision considered, applied or not:
// why it was recalled (path, hops, score, trust at use), the evidence for and
// against it (checks_json), and what changed afterwards (verdict, trust after).
MATCH (:Incident {key: $incident_key})<-[:FOR]-(d:Decision)-[u:USED]->(m:Memory)
OPTIONAL MATCH (m)-[:LEARNED_FROM]->(src:Incident)
OPTIONAL MATCH (m)-[:ABOUT]->(pin)
RETURN m.id AS memory, m.signature AS signature, m.family AS family,
       u.target AS target, u.score AS score, u.hops AS hops, u.path AS path,
       u.trust_at_use AS trust_at_use, u.applied AS applied, u.checks_json AS checks_json,
       u.verdict AS verdict, u.trust_after AS trust_after,
       m.trust AS trust_now, m.status AS status, collect(DISTINCT src.id) AS learned_from,
       collect(DISTINCT pin.name) AS pinned_to
ORDER BY score DESC
