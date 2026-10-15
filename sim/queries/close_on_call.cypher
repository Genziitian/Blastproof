// Org change: whoever is on call for a team stops being on call at $at.
// Validity is closed, never deleted, so who_to_page still answers for earlier times.
MATCH (:Person)-[oc:ON_CALL]->(t:Team {name: $team})
WHERE oc.valid_from < $at AND (oc.valid_to IS NULL OR oc.valid_to > $at)
SET oc.valid_to = $at
RETURN count(oc) AS closed
