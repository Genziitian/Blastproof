// UI: the incident feed, newest first, with the diagnosis and whether memory solved it.
MATCH (i:Incident)
OPTIONAL MATCH (i)<-[:FOR]-(d:Decision)
OPTIONAL MATCH (d)<-[:ON]-(f:Feedback)
OPTIONAL MATCH (d)-[u:USED]->(:Memory)
WITH i, d, f, count(u) AS considered,
     sum(CASE WHEN u.applied THEN 1 ELSE 0 END) AS applied
RETURN i.key AS key, i.id AS id, i.status AS status, i.observed_at AS observed_at,
       i.opened_at AS opened_at, d.root AS root, d.family AS family, d.agent AS agent,
       f.verdict AS verdict, considered, applied
ORDER BY opened_at DESC
LIMIT $limit
