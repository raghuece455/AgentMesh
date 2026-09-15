# OpenTelemetry

AgentMesh speaks OpenTelemetry in both directions:

| Direction | What | Where |
|---|---|---|
| **In** | Receive OTLP/HTTP traces from any framework (`POST /v1/traces`) and map the GenAI semantic conventions to traces, model calls, tools, sessions, and scores | [integrations.md](integrations.md) |
| **Out (files/API)** | Export any stored trace as OTLP-shaped JSON for Jaeger, Grafana Tempo, or another backend | this page |
| **Out (live)** | Mirror AgentMesh *runtime* events to an OTLP collector while a workflow runs | this page |

---

## Ingesting OpenTelemetry Traces

Start the dashboard and point an exporter at it:

```bash
agentmesh dashboard --port 8787
export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:8787"
```

Framework recipes, the attribute mapping, authentication, and privacy settings are in [integrations.md](integrations.md).

---

## Exporting a Trace as OTLP JSON

```bash
# CLI
agentmesh traces export <trace_id> --format otel-json --out trace.otel.json

# API
curl "http://127.0.0.1:8787/api/traces/<trace_id>/export?format=otel-json"
curl "http://127.0.0.1:8787/api/traces/<trace_id>/export/otel-json"
```

The export is an `ExportTraceServiceRequest` in OTLP/JSON form. To move a trace between AgentMesh databases without losing model, cost, or checkpoint detail, use the native format instead: `agentmesh export <trace_id> --out trace.json` and `agentmesh import trace.json`.

### Shape

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": "agentmesh"}},
          {"key": "service.version", "value": {"stringValue": "0.4.0"}},
          {"key": "agentmesh.trace_id", "value": {"stringValue": "trace_7e5c1f62f7c5f239"}},
          {"key": "agentmesh.environment", "value": {"stringValue": "local"}}
        ]
      },
      "scopeSpans": [
        {
          "scope": {"name": "agentmesh.otel_export", "version": "0.4.0"},
          "spans": [
            {
              "traceId": "5b8aa5a2d2c872e8321cf37308d69df2",
              "spanId": "051581bf3cb55c13",
              "parentSpanId": "5fb397be34d26b51",
              "name": "model.response",
              "kind": "SPAN_KIND_CLIENT",
              "startTimeUnixNano": 1757800000000000000,
              "endTimeUnixNano": 1757800001260000000,
              "attributes": [...],
              "events": [...],
              "status": {"code": "STATUS_CODE_OK"}
            }
          ]
        }
      ]
    }
  ]
}
```

AgentMesh trace and span IDs are hashed to the 32/16 hex characters OpenTelemetry requires, so the same trace always exports with the same IDs. Model and tool spans use `SPAN_KIND_CLIENT`; everything else is `SPAN_KIND_INTERNAL`. Failed spans get `STATUS_CODE_ERROR` with the error message.

### Span Attributes

| Attribute | Description |
|---|---|
| `agentmesh.trace_id`, `agentmesh.run_id` | Original AgentMesh IDs |
| `agentmesh.workflow_id`, `agentmesh.workflow_name` | Workflow (or trace) identity |
| `agentmesh.agent_id`, `agentmesh.agent_name` | Agent that produced the span |
| `agentmesh.task_id`, `agentmesh.task_name` | Task or step |
| `agentmesh.event_type` | e.g. `model.response`, `tool.finished`, `task.failed` |
| `agentmesh.provider`, `agentmesh.model` | Model provider and model |
| `agentmesh.prompt_tokens`, `agentmesh.completion_tokens`, `agentmesh.total_tokens` | Token usage |
| `agentmesh.estimated_cost`, `agentmesh.cost_status` | Cost in USD and how it was derived (`exact`, `estimated`, `local/free`, `unknown`) |
| `agentmesh.tool_name` | Tool called |
| `agentmesh.retry_count` | Retries before this span |
| `agentmesh.error_type` | Error class when the span failed |
| `agentmesh.environment`, `agentmesh.is_demo` | Environment label and demo flag |

### Span Events

Each span carries its recorded events (`agentmesh.event_id`, `agentmesh.actor`, `agentmesh.payload`) plus the related records as named events: `model.call`, `tool.call`, `memory.operation`, `rag.retrieval`, and `approval.request`.

---

## Mirroring Runtime Events to a Collector

Workflows built with the AgentMesh runtime can also emit OpenTelemetry spans live, alongside the local database. Install the `otel` extra and attach a bridge to the recorder:

```bash
pip install "agentmesh-ai[otel]"
```

```python
from agentmesh import SQLiteStore, TraceRecorder, Workflow, configure_opentelemetry

store = SQLiteStore()
bridge = configure_opentelemetry("research-service", otlp_endpoint="http://otel-collector:4318/v1/traces")
workflow = Workflow("research", store=store, recorder=TraceRecorder(store, otel=bridge))
```

Each runtime event (`workflow.started`, `model.response`, `tool.finished`, ...) becomes a span with `agentmesh.*` attributes and its payload fields. These are event-level spans rather than a nested, timed span tree; for full hierarchies in another backend, export stored traces as shown above.

---

## Secret Redaction

API keys, tokens, passwords, private keys, and credentials in URLs are redacted before a trace is stored, exported, or mirrored. Redacted values appear as `[REDACTED]`.

---

## Not Yet Supported

| Feature | Status |
|---|---|
| gRPC OTLP receiver (port 4317) | Use an OpenTelemetry Collector with an `otlphttp` exporter in front of AgentMesh |
| OTLP logs and metrics ingestion | Planned |
| Nested, timed span export while a runtime workflow is running | Planned |
