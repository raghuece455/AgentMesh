# Egress and data access

Two questions that come up after every agent incident: **did it talk to anything it shouldn't have?** and **what data did it touch first?** AgentMesh answers both from the traces you already send, and can block the call before it happens.

![Access: hosts agents reached and data they read](../dashboard/screenshots/access.png)

---

## What is recorded

Access records are derived when spans are ingested, so any framework that exports OpenTelemetry gets them — no extra SDK calls needed.

| Kind | Where it comes from |
|---|---|
| `network` | `url.full`, `http.url`, `server.address`, `net.peer.name`, `http.host`, `peer.service` on any span, plus URLs in a tool call's arguments — not in its result, since the links on a fetched page were never called |
| `retrieval` | RAG spans: the data source or vector store, and how many documents came back |
| `memory` | memory spans: the store and key, with the operation (read, write, delete) |
| `db` | `db.system` / `db.namespace` / `db.collection.name`, with `db.operation.name` as the detail |
| `file` | `file.path`, `code.file.path` |
| anything else | `agentmesh.record_access(...)` from your own code |

```python
agentmesh.record_access("customers.invoices", kind="db", operation="read", detail="200 rows")
```

Each record keeps the agent, the service, the trace and span, whether the call failed, and when it happened. With `AGENTMESH_CAPTURE_CONTENT=false`, hosts from span attributes are still recorded, but URLs inside arguments are not — AgentMesh cannot read what it is not allowed to store.

---

## Blocking what agents reach

A policy rule matches on `host`, checked **before the call runs**, so an allowlist actually prevents the request instead of reporting it afterwards:

```yaml
name: egress
mode: enforce
rules:
  - name: approved-domains-only
    match: {kind: tool, host: "*"}          # only calls that reach a host at all
    except: {host: ["*.mycompany.com", "api.openai.com", "duckduckgo.com"]}
    action: deny
    reason: That domain is not on the allowlist.

  - name: no-paste-sites
    match: {host: ["pastebin.com", "*.pastebin.com", "transfer.sh"]}
    action: deny
```

`host` matches the hosts AgentMesh can see in the call: its span attributes and its arguments. A call with no host (a calculator tool, say) never matches `host`, so `match: {kind: tool, host: "*"}` is what limits an allowlist rule to calls that actually go somewhere.

Denied calls raise `agentmesh.PolicyViolation` in the agent and are still recorded on the Access page — with the status `failed` — so you can see what an agent *tried* to reach. See [guardrails.md](guardrails.md).

To be told about a destination instead of blocking it, add a `new_destination` alert rule: it notifies once for each host or store nothing in this AgentMesh had reached before. See [alerts.md](alerts.md#swarm-and-egress-anomalies).

**What this does not do:** it reads the call AgentMesh is given. An agent that builds a URL inside an opaque binary, resolves an IP itself, or uses a tool that never reveals its destination is not covered. For hard network isolation, use a proxy or egress firewall and keep these rules as the in-agent layer.

---

## Dashboard

**Access** (under Monitor) lists every destination and resource for the selected time range: kind, target, how many accesses, by how many agents and traces, errors, and when it was last used. Anything first seen inside the range is marked **new**, which is usually the interesting row. Select one to see the individual accesses, the agent behind each, and a link to its trace.

Elsewhere:

- a trace shows a **Reached** card with the hosts and stores that run touched;
- a swarm has an **Access** tab with the same grouped by destination, so "this swarm read the price database and then called an unknown host" is one screen.

---

## CLI, API, and MCP

```bash
agentmesh access summary [--hours 24] [--kind network] [--limit 50]
agentmesh access list [--kind db] [--target invoices] [--exact] [--trace <id>] [--agent researcher] [--hours 24]
```

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/access` | Individual accesses, newest first. Query params: `kind`, `target` (substring, or exact with `exact=true`), `trace_id`, `agent`, `hours`, `limit` |
| `GET` | `/api/access/summary` | Destinations and resources with counts, errors, first and last use, and `is_new` for the window. Query params: `kind`, `hours`, `limit` |

Trace detail (`GET /api/traces/{trace_id}`) includes `access`, and swarm detail includes it grouped by destination. The MCP server exposes `list_access`, so a coding agent can answer "did anything reach an unexpected domain today?".

Access records are deleted with their traces by `agentmesh traces prune`.
