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

All `/api/*` routes, `POST /v1/traces`, and `WS /ws/events` then require:

```
Authorization: Bearer my-secret-key
```

`X-AgentMesh-Api-Key: my-secret-key` is also accepted. `/`, `/assets/*`, `/healthz`, `/readyz`, and `/metrics` stay open.

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
| `GET` | `/api/traces` | List traces. Query params: `limit`, `offset`, `q`, `status`, `workflow`, `agent`, `task`, `model`, `provider`, `tool`, `error_type`, `min_cost`, `max_cost`, `min_latency`, `max_latency`, `started_after`, `started_before`, `environment`, `is_demo` |
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
| `GET` | `/api/traces/{trace_id}/insights` | Automatic insights: root cause, tool loops, repeated prompts, context growth, cache usage, hotspots |
| `GET` | `/api/traces/{trace_id}/scores` | Scores attached to the trace |

`/api/traces` also accepts `session_id`, `user_id`, `tag`, and `source` (`runtime`, `otlp`, `sdk`, `file`) filters.

---

## Ingestion (OpenTelemetry)

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/traces` | OTLP/HTTP trace receiver. `application/json` or `application/x-protobuf` (requires the `otlp` extra); gzip/deflate bodies accepted. Returns an OTLP `ExportTraceServiceResponse`. See [integrations.md](integrations.md). |
| `GET` | `/api/integrations` | The server's OTLP endpoint URL, protobuf support, auth mode, and content-capture setting |

---

## Sessions and Scores

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/sessions` | Sessions (grouped traces) with turn count, failures, cost. Query params: `limit`, `offset`, `user_id` |
| `GET` | `/api/sessions/{session_id}` | Every trace in the session in order, with inputs, outputs, and scores |
| `POST` | `/api/scores` | Create a score: `{"trace_id", "name", "value": number/bool/string, "span_id"?, "comment"?, "label"?, "passed"?, "source"?, "metadata"?}` |
| `GET` | `/api/scores` | List scores. Query params: `trace_id`, `name`, `limit` |

---

## Datasets and Experiments

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/datasets` | Datasets with item count, experiment count, and last run |
| `POST` | `/api/datasets` | Create: `{"name", "description"?, "metadata"?}` (`409` if the name exists) |
| `GET` | `/api/datasets/{name_or_id}` | Dataset with a page of its items. Query params: `limit` (default 5000), `offset`; `item_count` is the total |
| `DELETE` | `/api/datasets/{name_or_id}` | Delete the dataset, its items, and its experiments |
| `POST` | `/api/datasets/{name_or_id}/items` | Add items `{"items": [{"input", "expected"?, "metadata"?, "item_id"?}]}` or copy a trace `{"trace_id", "span_id"?, "use_trace_output"?, "expected"?}` |
| `DELETE` | `/api/datasets/{name_or_id}/items/{item_id}` | Remove one item |
| `GET` | `/api/experiments` | Experiments, newest first, with summaries, cost, and tokens. Query params: `dataset`, `limit` |
| `POST` | `/api/experiments` | Create or update an experiment and upsert its results (used by the SDKs) |
| `GET` | `/api/experiments/{experiment_id}` | Experiment with per-item results, scores, cost, and trace ids |
| `GET` | `/api/experiments/compare?base=&candidate=` | Item-by-item comparison: counts, score deltas, cost and latency change, changed items first |
| `DELETE` | `/api/experiments/{experiment_id}` | Delete one experiment |

See [datasets-and-experiments.md](datasets-and-experiments.md).

---

## Alerts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/alerts/kinds` | Rule kinds with descriptions, and the scheduler interval |
| `GET` | `/api/alerts/rules` | Rules with state, last value, and last fired time (webhook URLs and secrets masked) |
| `POST` | `/api/alerts/rules` | Create: `{"name", "kind", "threshold", "window"?, "cooldown"?, "filters"?, "channel"?: {"url", "format"?, "secret"?, "notify_resolved"?}, "enabled"?}` |
| `PATCH` | `/api/alerts/rules/{rule_id_or_name}` | Update any of the fields above |
| `DELETE` | `/api/alerts/rules/{rule_id_or_name}` | Delete a rule |
| `POST` | `/api/alerts/rules/{rule_id_or_name}/test` | Send a test notification; returns `{"delivered", "error"}` |
| `POST` | `/api/alerts/check` | Evaluate every enabled rule now. Query param: `deliver` (default `true`) |
| `GET` | `/api/alerts/events` | Alert history. Query params: `rule`, `limit` |

See [alerts.md](alerts.md).

---

## Swarms

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/swarms` | Swarm runs with status, agents, failed and running agents, traces, LLM and tool calls, tokens, cost, and duration. Query params: `q`, `hours`, `limit`, `offset` |
| `GET` | `/api/swarms/{swarm_id}` | `summary`, agents (`nodes`), spawn/message/handoff `edges`, `roles` (the graph grouped by agent name), `messages`, `timeline`, `insights`, member `traces`, swarm-limit `usage` and `limits`, and the active `halt` |
| `POST` | `/api/swarms/check` | Evaluate swarm-wide limits now: halts swarms that broke one and returns every breach. Query param: `enforce` (default `true`) |

Trace detail (`GET /api/traces/{trace_id}`) includes `swarms`, the swarms the trace belongs to. Halts accept `"scope": "swarm"`. See [swarms.md](swarms.md).

---

## Guardrails

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/policies` | Policies with mode, enabled, spec, rule count, limits, and saved source text |
| `POST` | `/api/policies` | Create: `{"text": "<yaml or json>", "enabled"?}` or `{"spec": {...}}`. Invalid policies return `422` with every error |
| `GET` | `/api/policies/{policy_id_or_name}` | One policy |
| `PATCH` | `/api/policies/{policy_id_or_name}` | Update `text`, `spec`, `mode`, or `enabled` |
| `DELETE` | `/api/policies/{policy_id_or_name}` | Delete a policy |
| `POST` | `/api/policies/validate` | `{"text"}` returns `{"valid", "errors", "policy"}` |
| `POST` | `/api/policies/simulate` | Replay recent traces through a draft (`text`/`spec`) or saved (`policy`) policy. Optional `limit`, `hours` |
| `GET` | `/api/policy-decisions` | Decisions. Query params: `action` (`blocked`, `would_block`, `require_approval`, `warn`, `allow`, `deny`), `trace_id`, `hours`, `limit` |
| `GET` | `/api/guardrails/summary` | Policy counts, active halts, and decision counts. Query param: `hours` (default 24) |
| `GET` | `/api/guardrails/runtime` | Enabled policy specs and active halts, polled by SDKs |
| `GET` | `/api/halts` | Active halts; `?active=false` includes released ones |
| `POST` | `/api/halts` | Create: `{"scope": "all", "service", "agent", or "trace", "value"?, "reason"?}` (audited) |
| `POST` | `/api/halts/{halt_id}/release` | Lift a halt (audited) |
| `POST` | `/api/approvals` | Request an approval: `{"tool", "agent"?, "trace_id"?, "arguments"?}` (used by SDKs) |
| `GET` | `/api/approvals/{approval_id}` | One approval with its status |

See [guardrails.md](guardrails.md).

---

## Pricing

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/pricing` | All configured price rules |
| `GET` | `/api/pricing?model=<model>&provider=<provider>` | The rule used for one model |

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
