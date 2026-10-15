// Arm B binding only: routes from an alerting service to a target, so the shared
// precondition executor can bind $alerting and $caller.
MATCH p = (a:Service)-[:DEPENDS_ON*0..3]->(t)
WHERE a.name IN $alerting AND t.name = $target
RETURN [x IN nodes(p) | x.name] AS path
