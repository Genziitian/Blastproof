// Everything the learner needs: the decision, its verdict, and the root's kind.
MATCH (l:Task {id: $task_id})-[:FOR]->(i:Incident)<-[:FOR]-(d:Decision {kind: 'root_cause'})
MATCH (d)<-[:ON]-(f:Feedback)
OPTIONAL MATCH (root) WHERE (root:Service OR root:Datastore) AND root.name = d.root
RETURN i.key AS incident_key, i.observed_at AS observed_at,
       d.id AS decision_id, d.root AS root, d.family AS family,
       d.task_id AS investigate_task, f.verdict AS verdict,
       coalesce(root.kind, 'service') AS root_kind
ORDER BY d.at DESC
LIMIT 1
