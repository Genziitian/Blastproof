// Scenario clock: when the latest incident was observed (null on a fresh graph).
MATCH (i:Incident)
RETURN max(i.observed_at) AS last
