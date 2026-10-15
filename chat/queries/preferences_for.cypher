// A person's preferences that hold at scenario time for this kind of incident,
// with the message (and incident) each one came from.
MATCH (f:Memory:Fact)-[:ABOUT]->(p:Person {key: $person_key})
WHERE f.status = 'active'
  AND f.valid_from <= $scenario_now
  AND (f.valid_to IS NULL OR $scenario_now < f.valid_to)
  AND (f.condition_family IS NULL OR f.condition_family = $family)
OPTIONAL MATCH (f)-[:LEARNED_FROM]->(m:Message)-[:IN]->(:Session)-[:CONCERNS]->(i:Incident)
RETURN f.id AS id, f.predicate AS predicate, f.object AS value,
       f.condition_family AS condition_family, f.source AS source,
       f.recorded_at AS recorded_at, m.text AS said, i.id AS learned_in
