// The source of a deliberately wrong playbook is not a real incident; label it.
MATCH (i:Incident {key: $incident_key})
SET i.status = 'planted'
RETURN i.key AS key
