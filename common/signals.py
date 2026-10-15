"""Thresholds that turn an observation into a finding.

Shared by the rule-based planner and by learned playbooks, so "saturated" means
the same thing whether the agent reasons it out or recalls it.
"""

SATURATED_PCT = 90.0          # database connections in use
CACHE_COLLAPSED_PCT = 50.0    # cache hit rate
DEPLOY_ERROR_PCT = 20.0       # error rate on a freshly deployed service
