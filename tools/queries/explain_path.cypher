// Why a node matters to these alerts: FalkorDB's shortest-path algorithm from each
// alerting service down DEPENDS_ON to the node (at most 4 hops), shortest first.
MATCH (a:Service) WHERE a.name IN $alerting
MATCH (t {name: $node}) WHERE t:Service OR t:Datastore
CALL algo.SPpaths({sourceNode: a, targetNode: t, relTypes: ['DEPENDS_ON'],
                   relDirection: 'outgoing', maxLen: 4, pathCount: 1})
YIELD path, pathWeight
RETURN a.name AS alerting, [n IN nodes(path) | n.name] AS path, pathWeight AS hops
ORDER BY hops ASC, alerting ASC
