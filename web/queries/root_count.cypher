// How many earlier incidents were diagnosed and confirmed on this node, so a
// repeat failure gets alert wording it has not used before.
MATCH (i:Incident)-[:TOUCHED {role: 'root'}]->(n {name: $node})
RETURN count(i) AS n
