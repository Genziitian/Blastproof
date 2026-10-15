// What it remembers: every playbook, where it is pinned and where it came from.
MATCH (p:Memory:Playbook)
OPTIONAL MATCH (p)-[:ABOUT]->(n)
OPTIONAL MATCH (p)-[:LEARNED_FROM]->(i:Incident)
RETURN p.id AS id, p.signature AS signature, p.family AS family,
       p.applies_to_kind AS kind, p.trust AS trust, p.helped AS helped, p.misled AS misled,
       p.status AS status, p.source AS source, p.preconditions_json AS preconditions_json,
       p.steps_json AS steps_json, p.recorded_at AS recorded_at,
       collect(DISTINCT n.name) AS about, collect(DISTINCT i.id) AS learned_from
ORDER BY recorded_at
