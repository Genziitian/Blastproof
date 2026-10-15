// What it remembers: every preference fact, every version, with the engineer's
// own words it came from. Superseded versions stay, closed by valid_to.
MATCH (f:Memory:Fact)-[:ABOUT]->(p:Person)
OPTIONAL MATCH (f)-[:LEARNED_FROM]->(m:Message)-[:IN]->(:Session)-[:CONCERNS]->(i:Incident)
OPTIONAL MATCH (f)-[:SUPERSEDES]->(old:Memory:Fact)
RETURN f.id AS id, p.handle AS handle, f.predicate AS predicate, f.object AS value,
       f.condition_family AS condition_family, f.source AS source,
       f.approved_by AS approved_by, f.trust AS trust, f.valid_from AS valid_from,
       f.valid_to AS valid_to, f.recorded_at AS recorded_at, m.text AS said,
       i.id AS learned_in, collect(old.id) AS supersedes
ORDER BY recorded_at
