// The full records of recalled playbooks, so their checks can be run.
MATCH (m:Memory:Playbook) WHERE m.id IN $ids
RETURN m.id AS id, m.signature AS signature, m.family AS family,
       m.applies_to_kind AS applies_to_kind, m.params_json AS params_json,
       m.preconditions_json AS preconditions_json, m.steps_json AS steps_json,
       m.conclusion AS conclusion, m.stop_if AS stop_if,
       m.trust AS trust, m.helped AS helped, m.misled AS misled
