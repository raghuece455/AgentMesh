# API Reference

The dashboard backend is a FastAPI application exposed by `agentmesh.dashboard:create_app`. Start it with:

```bash
agentmesh dashboard --host 127.0.0.1 --port 8787
```

Interactive docs are available at [http://127.0.0.1:8787/docs](http://127.0.0.1:8787/docs).

---

## Authentication

By default the API is open (local mode). To require an API key:

```bash
export AGENTMESH_AUTH_MODE=api_key
export AGENTMESH_API_KEY=my-secret-key
```

All protected routes then require:

```
Authorization: Bearer my-secret-key
```

---

## Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Returns `{"status": "ok"}` — used by Docker health checks |
| `GET` | `/readyz` | Returns `{"status": "ready"}` once the database is reachable |
| `GET` | `/metrics` | Prometheus-compatible text metrics |

---

## Traces

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/traces` | List traces. Query params: `limit`, `offset`, `status` (`succeeded`/`failed`), `workflow_name`, `agent_name` |
| `GET` | `/api/traces/{trace_id}` | Full trace detail — spans, events, model calls, tool calls, diagnosis |
| `GET` | `/api/traces/{trace_id}/replay` | Replay metadata and checkpoint list |
| `GET` | `/api/traces/{trace_id}/costs` | Cost breakdown by step and agent |
| `GET` | `/api/traces/{trace_id}/checkpoints` | All checkpoints with memory state at each step |
| `GET` | `/api/traces/{trace_id}/prompts` | All model prompts and responses for the trace |
| `GET` | `/api/traces/{trace_id}/diagnose` | Failure diagnosis — classified errors, retry events, budget events |
| `GET` | `/api/traces/{trace_id}/export` | Export as JSON. Add `?format=otel-json` for OTEL format |
| `GET` | `/api/traces/{trace_id}/export/otel-json` | Export in OpenTelemetry JSON format directly |
| `POST` | `/api/traces/import` | Import a previously exported trace JSON |
| `GET` | `/api/compare` | Compare two traces side by side. Query params: `left=<trace_id>`, `right=<trace_id>` |

---

## Checkpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/checkpoints/{checkpoint_id}` | Full checkpoint detail — step ID, memory state, completed outputs |

---

## Runtime State

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/workflows/active` | Currently running workflows with step progress |
| `GET` | `/api/agents/status` | All agents with current status, last task, and recent metrics |
| `GET` | `/api/memory` | Long-term memory records. Query params: `agent_name`, `namespace`, `key` |
| `GET` | `/api/memory/audit` | Audit log of all memory reads and writes |

---

## Approvals

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/approvals` | List approval requests. Query params: `status` (`pending`/`approved`/`rejected`) |
| `POST` | `/api/approvals/{approval_id}/resolve` | Approve or reject. Body: `{"decision": "approved", "reason": "optional text"}` |

---

## Cost Analytics

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/costs` | Aggregate cost analytics. Query params: `dimension` (`model`/`agent`/`workflow`), `period` (`day`/`week`/`month`) |

---

## Live Updates

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/events/stream` | Server-Sent Events stream — workflow status, agent events, approvals |
| `WS` | `/ws/events` | WebSocket alternative to SSE |

---

## Example Requests

```bash
# List the last 10 failed traces
curl "http://127.0.0.1:8787/api/traces?status=failed&limit=10"

# Get full detail for a trace
curl "http://127.0.0.1:8787/api/traces/trc_abc123"

# Approve a pending tool call
curl -X POST "http://127.0.0.1:8787/api/approvals/apr_xyz789/resolve" \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "reason": "Confirmed safe to send"}'

# Export a trace in OTEL format
curl "http://127.0.0.1:8787/api/traces/trc_abc123/export?format=otel-json" \
  -o trace.otel.json

# Compare two traces
curl "http://127.0.0.1:8787/api/compare?left=trc_abc123&right=trc_def456"

# Cost breakdown by model for the current week
curl "http://127.0.0.1:8787/api/costs?dimension=model&period=week"
```

---

## With Authentication

```bash
curl "http://127.0.0.1:8787/api/traces" \
  -H "Authorization: Bearer my-secret-key"
```
