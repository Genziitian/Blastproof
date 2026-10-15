// A2: one verdict per USED edge, applied once; a retried call changes nothing.
// $verdicts = [{id, target, verdict: 'helped' | 'misled' | 'not_applicable'}]
// Only memories that were followed can be credited or blamed.
MATCH (d:Decision {id: $decision_id})
UNWIND $verdicts AS v
MATCH (d)-[u:USED {target: v.target}]->(m:Memory {id: v.id})
WHERE u.verdict IS NULL
SET u.verdict = v.verdict,
    m.helped = m.helped + CASE WHEN v.verdict = 'helped' THEN 1 ELSE 0 END,
    m.misled = m.misled + CASE WHEN v.verdict = 'misled' THEN 1 ELSE 0 END
SET m.trust = (m.helped + m.prior_a) * 1.0 / (m.helped + m.misled + m.prior_a + m.prior_b)
SET m.status = CASE WHEN m.misled >= 2 AND m.trust < 0.5 THEN 'retired' ELSE m.status END
RETURN m.id AS id, u.target AS target, u.verdict AS verdict, m.trust AS trust,
       m.status AS status
