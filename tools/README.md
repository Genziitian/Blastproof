# tools/

One registry (`registry.py`) used by the agents in-process and by the MCP server.
Each tool runs against a `ToolContext` the worker builds from trusted state; the
model supplies only the arguments in the tool's schema, never a graph or tenant.

| Tool | Source |
| --- | --- |
| `inspect_metrics(node, window_min)` | simulator |
| `inspect_logs(node, n)` | simulator |
| `inspect_recent_changes(service, hours)` | simulator (G2: `Change` nodes in the graph) |
| `check_dependency_health(service)` | simulator |
| `find_upstream_candidates(alerting)` | `queries/upstream_candidates.cypher` |
| `blast_radius(node)` | `queries/blast_radius.cypher` |
| `who_to_page(node)` | `queries/who_to_page.cypher`, valid at scenario time |

Try them by hand from any MCP client, for example the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector python -m tools.mcp_server --company a --scenario s01
```
