// Arm B targets: every datastore of a kind (text retrieval has no notion of "nearby").
MATCH (d:Datastore {kind: $kind})
RETURN d.name AS name
ORDER BY name
