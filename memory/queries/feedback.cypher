// A2: one verdict per USED edge, applied once; a retried call changes nothing.
// $verdicts = [{id, target, verdict: 'helped' | 'misled' | 'not_applicable'}]
// Only memories that were followed can be credited or blamed.
MATCH (d:Decision {id: $decision_id})
UNWIND $verdicts AS v
MATCH (d)-[u:USED {target: v.target}]->(m:Memory {id: v.id})
WHERE u.verdict IS NULL
SET u.verdict = v.verdict
// One decision can use the same memory twice (pinned here, and by kind elsewhere).
// Sum the verdicts per memory before touching its counters: row by row, each row
// would read the counter from before the others' updates and the last one wins.
WITH m, collect(u) AS used,
     toInteger(sum(CASE WHEN v.verdict = 'helped' THEN 1 ELSE 0 END)) AS helped,
     toInteger(sum(CASE WHEN v.verdict = 'misled' THEN 1 ELSE 0 END)) AS misled
SET m.helped = m.helped + helped, m.misled = m.misled + misled
// FalkorDB evaluates back-to-back SET clauses against the pre-update values,
// so each SET that reads an updated property needs its own WITH.
WITH m, used
SET m.trust = (m.helped + m.prior_a) * 1.0 / (m.helped + m.misled + m.prior_a + m.prior_b)
WITH m, used
SET m.status = CASE WHEN m.misled >= 2 AND m.trust < 0.5 THEN 'retired' ELSE m.status END
WITH m, used
UNWIND used AS u
SET u.trust_after = m.trust
RETURN m.id AS id, u.target AS target, u.verdict AS verdict, m.trust AS trust,
       m.status AS status
