# chat/

The war room between the on-call engineer and the responder.

| Module | Role |
| --- | --- |
| `preferences.py` | Engineer's words → conditional facts (`preferred_channel = ticket` when `family = db_saturation`). LLM if configured, deterministic parser otherwise; any model answer outside the vocabulary is discarded |
| `war_room.py` | Sessions per engineer per incident, verbatim messages, preference writes (A3) sourced to the exact message, lookup for a new incident with citations |

The condition is part of each fact's lineage, so "for bad deploys, page me" sits beside
"for DB saturation, open a ticket" instead of replacing it. Lookups are per person and per
company graph, so one engineer's preferences never reach another, even with the same handle.
