// Arm B indexing: what each active playbook says, where it is pinned and which
// alerts it was learned from, to embed as text.
MATCH (m:Memory:Playbook) WHERE m.status = 'active'
OPTIONAL MATCH (m)-[:ABOUT]->(n)
WITH m, collect(DISTINCT n.name) AS about
OPTIONAL MATCH (m)-[:LEARNED_FROM]->(:Incident)<-[:PART_OF]-(a:Alert)
RETURN m.id AS id, m.signature AS signature, m.family AS family, m.applies_to_kind AS kind,
       about, collect(DISTINCT a.text) AS alerts, m.embed_hash AS embed_hash
