# Deploying the live demo

The UI and its agents can run as a public, **read-only** demo. With `PUBLIC_MODE=1`:

- every POST is refused (403). Visitors can't reset the graph, kill workers, start incidents or type into the war room;
- the scripted engineer answers, and the server plays the story by itself, over and over:
  - **s01:** nothing in memory, one page to Priya, her preference read back;
  - **s04:** the playbook recalled by kind; the investigator SIGKILLed after step 3 and taken over at step 4; one ticket;
  - **s05:** the DB playbook ruled out on evidence.
- every round starts with any killed investigator started again, and from the graph as seeded: it is reset after every round (`PUBLIC_RESET_EVERY`, default 1) and on every start, so s01 always begins with nothing in memory;
- the model is off unless `PUBLIC_LLM=1`, so visitors can't run up a bill;
- error responses carry no internals.

Local use (`make ui`) keeps every control. Its POSTs are also refused when they come from another site's page (an `Origin` check), and the server only answers to the host names in `ALLOWED_HOSTS` (default `localhost,127.0.0.1`).

## One host with Docker (tested)

```bash
export FALKORDB_PASSWORD=$(openssl rand -hex 16)
docker compose -f docker-compose.public.yml up -d --build
# http://localhost:8080  (mission control: /mission-control)
```

FalkorDB runs beside the app with a password and is not published outside the compose network. To serve a domain, set `ALLOWED_HOSTS=your.domain` (comma-separated, or `*` to turn the check off) and put a TLS proxy (Caddy, nginx, or your platform's) in front of port 8080.

This was run on Docker Desktop on Oct 18: the graph seeds itself, the story loops (two full rounds watched, each with a real kill and a takeover at step 4), and `POST /api/reset` returns 403.

## A platform (Fly.io, Render, Railway)

The `Dockerfile` is the app. It listens on `$PORT` (default 8000) and needs:

| Variable | Value |
|---|---|
| `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_PASSWORD` | your FalkorDB: a second service on the same platform running the FalkorDB image (with `--requirepass`), or FalkorDB Cloud |
| `ALLOWED_HOSTS` | the public host name, e.g. `blast-radius.fly.dev` |
| `PUBLIC_MODE` | `1` (already set in the image) |

Investigators run as child processes of the app, so one instance is enough; don't scale it out (two copies would play two stories into one graph).
