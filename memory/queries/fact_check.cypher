// A3 step 1 (read-only): validate scope, source and any existing version first,
// and count earlier versions of this lineage.
OPTIONAL MATCH (scope {key: $scope_key})
OPTIONAL MATCH (src {key: $source_key})
OPTIONAL MATCH (existing:Memory {id: $id})
OPTIONAL MATCH (prev:Memory:Fact {lineage_id: $lineage})
RETURN scope IS NOT NULL AS scope_ok, src IS NOT NULL AS source_ok,
       existing.payload_hash AS existing_hash, count(prev) AS versions
