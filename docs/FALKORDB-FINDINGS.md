# FalkorDB findings

What we ran into while building Blast Radius on FalkorDB during Graph Hacks 2026, written so each item can be checked independently. We report only what we reproduced; one earlier suspicion that did not reproduce is listed at the end.

**Environments**

| | Server | Client | Where |
|---|---|---|---|
| Mac | FalkorDB 4.22.1, Redis 8.10.2, Docker image `falkordb/falkordb@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a` (`latest` on Oct 15–16, 2026) | falkordb-py 1.8.0, Python 3.15 | macOS arm64, Docker Desktop |
| Linux | FalkorDB 4.18.3, Redis 8.6.2 (the module bundled with falkordblite) | falkordb-py 1.8.0, Python 3.13 | Linux x86_64 |

## 1. AOF replay diverges and the server shuts down on every start (4.22.1)

**Severity:** high. The database would not start again, and with `restart: unless-stopped` the container restarted in a loop. The data could only be reached by replaying the log.

**Configuration:** `--appendonly yes --appendfsync everysec`, the image's defaults otherwise (AOF with RDB preamble), a named Docker volume.

**What happened:** after about ten hours of development (base RDB 36,394 s old), we stopped the container with `docker compose down` and started it with `docker compose up -d falkordb`. On loading:

```
* Reading RDB base file on AOF loading...
* Done loading RDB, keys loaded: 0, keys expired: 0.
* DB loaded from base file appendonly.aof.1.base.rdb: 0.000 seconds
# <module> GRAPH.EFFECT references label/relationship-type 'Memory' (id 0) which doesn't match local schema state
# <graph> Diverged applying GRAPH.EFFECT on graph 'company_a' while loading from disk: failed to apply effects, see preceding log entries. A full resync can't repair already-loaded state, shutting down.
```

Clients first saw `BusyLoadingError: Redis is loading the dataset in memory`, then connection refused, because the server exited.

**Workload in that AOF:**
- The same graph names deleted (`GRAPH.DELETE`) and re-created many times: our benchmark and tests reset scratch graphs, and our acceptance test resets `company_a`.
- After each re-creation: 20 exact-match indexes, then 14 unique constraints (`GRAPH.CONSTRAINT CREATE ... UNIQUE NODE <label> PROPERTIES 1 <prop>`), polled until `OPERATIONAL`.
- Then many `MERGE` and `SET` writes, some with `timestamp()`.
- Nodes carry multiple labels (`:Memory:Playbook`, `:Memory:Fact`), and `Memory` is the first label created after the schema setup.

**What did not reproduce it:** on 4.18.3 (Linux), a short sequence of schema, seed, delete, re-create, writes and restart replayed correctly (all 54 nodes back). We have not yet isolated a minimal sequence for 4.22.1.

**Possibly related:** see item 2. The AOF mixes `GRAPH.QUERY` (replayed verbatim) and `GRAPH.EFFECT` entries (in our short sequence: 192 queries, 15 effects), so a schema whose label ids are assigned in a different order during replay would explain an effect pointing at the wrong label id. That is our guess, not something we verified.

**What we did:** switched to RDB snapshots (`--appendonly no --save 30 1`, `stop_grace_period: 30s`). Snapshots load without replay, and our restart test (data written, `docker compose down && up`, then a worker killed mid-task and taken over) passes on 4.22.1.

## 2. Each unique-constraint creation is written to the AOF three times; replay logs errors (4.18.3)

**Severity:** low on 4.18.3 (loading continues), but it may matter for item 1.

Our schema setup issued 14 `GRAPH.CONSTRAINT CREATE` commands, twice: once at setup, once after the graph was deleted and re-created. That is 28 commands. The incremental AOF contained **84** `GRAPH.CONSTRAINT` entries. On the next start, loading logged 28 times:

```
# == CRITICAL == This server is sending an error to its AOF-loading-client: '-Constraint already exists' after processing the command 'graph.CONSTRAINT'
```

Loading then finished and the data was correct. Reproduce: with `--appendonly yes`, create 14 indexes and unique constraints on a graph, `GRAPH.DELETE` it, create them again, then count `GRAPH.CONSTRAINT` in `appendonlydir/*.incr.aof` and restart.

## 3. A later SET clause sees the values from before an earlier SET clause (4.18.3)

**Severity:** medium. Results are silently wrong, with no error.

```
GRAPH.QUERY g "CREATE (:M {h: 0, t: -1})"
GRAPH.QUERY g "MATCH (m:M) SET m.h = m.h + 1 SET m.t = m.h RETURN m.h, m.t"
-> m.h = 1, m.t = 0
```

In Cypher as we understand it (and in Neo4j), clauses run in order, so the second `SET` should read `m.h = 1` and set `m.t = 1`. Adding `WITH m` between the clauses gives the expected result:

```
GRAPH.QUERY g "MATCH (m:M) SET m.h = m.h + 1 WITH m SET m.t = m.h RETURN m.h, m.t"
-> m.h = 2, m.t = 2
```

**How we hit it:** our trust update increments `helped` and `misled` in one `SET`, then computes `trust` from them in the next `SET`, then decides retirement from `trust` in a third. Without `WITH`, trust lagged one verdict behind, and a misleading memory was never retired. Our Python test double did not catch it; only the run against FalkorDB did. Fixed in `memory/queries/feedback.cypher` with a `WITH u, m` between the clauses.

## Friction (not bugs)

- **Unique constraints:** they need an exact-match index on the same property first, and they are built asynchronously (`PENDING`, then `OPERATIONAL`). We poll `CALL db.constraints()` before starting any worker. The docs say so, but a blocking option, or an error when the index is missing, would save a round of debugging.
- **Right after a restart**, every command fails with `LOADING` until the dataset is in memory; falkordb-py surfaces it as `redis.exceptions.BusyLoadingError`. We poll `GRAPH.LIST` until it answers (`common/db.py: wait_ready`). A `wait_until_ready()` helper in the client would make restart handling the default.
- **The client constructor connects immediately:** `FalkorDB(host, port)` sends `INFO` (sentinel detection) and raises if the server is down, so a client cannot be created before the database is up.

## Checked and not reproduced

Early on, `db.idx.vector.queryNodes` once seemed to return fewer neighbours than requested on a tiny graph (1–2 of 3 embedded nodes for k = 10). We could not reproduce this in isolation on 4.18.3: 3, 5 and 10 nodes, 4 and 256 dimensions, dense and sparse (hashed bag-of-words) vectors, the index created before or after the nodes, embeddings set later and re-set, and other nodes with the same label but no embedding. All returned every node. Our arm-B retrieval uses exact `vec.cosineDistance` instead, which is exact by definition and cheap for a few hundred memories. We do not consider this a FalkorDB issue.
