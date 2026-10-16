// Learner: the memories a decision used, with whether each was applied and its verdict.
MATCH (d:Decision {id: $decision_id})-[u:USED]->(m:Memory)
RETURN m.id AS id, u.target AS target, u.applied AS applied, u.verdict AS verdict
