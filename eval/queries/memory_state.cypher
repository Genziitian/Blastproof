// Evaluator: a memory's current counts and status (M5 retirement).
MATCH (m:Memory {id: $id})
RETURN m.helped AS helped, m.misled AS misled, m.trust AS trust, m.status AS status
