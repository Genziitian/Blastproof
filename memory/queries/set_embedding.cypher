// Arm B indexing: store a playbook's text embedding (index data, not content).
MATCH (m:Memory {id: $id})
SET m.embedding = vecf32($vector), m.embed_hash = $hash
RETURN m.id AS id
