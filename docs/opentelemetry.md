# OpenTelemetry Export

AgentMesh `v0.3.0-alpha` exports traces in an OpenTelemetry-compatible JSON format. Every span, event, and attribute is mapped to the OTEL schema so traces can be imported into Jaeger, Grafana Tempo, or any OTEL-compatible backend.

> **Note:** This is a file/API export format. Native OTLP collector push (streaming spans directly to a collector) is planned for a future release.

---

## Exporting via the CLI

```bash
# Export a single trace as OTEL JSON
agentmesh traces export <trace_id> --format otel-json --out trace.otel.json
```

---

## Exporting via the API

```bash
# Query parameter form
curl "http://127.0.0.1:8787/api/traces/<trace_id>/export?format=otel-json"

# Dedicated OTEL endpoint
curl "http://127.0.0.1:8787/api/traces/<trace_id>/export/otel-json"
```

---

## JSON Shape

The exported file follows the OTEL trace JSON format:

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": "agentmesh"}},
          {"key": "agentmesh.version", "value": {"stringValue": "0.3.0-alpha"}}
        ]
      },
      "scopeSpans": [
        {
          "scope": {"name": "agentmesh"},
          "spans": [
            {
              "traceId": "...",
              "spanId": "...",
              "parentSpanId": "...",
              "name": "agent.run",
              "kind": 1,
              "startTimeUnixNano": "1714500000000000000",
              "endTimeUnixNano": "1714500001500000000",
              "attributes": [...],
              "events": [...],
              "status": {"code": 1}
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Top-Level Keys

| Key | Description |
|---|---|
| `resourceSpans` | Array of resource groups (one per service) |
| `scopeSpans` | Array of instrumentation scopes |
| `spans` | Array of individual spans |
| `traceId` | Unique trace identifier |
| `spanId` | Unique span identifier |
| `parentSpanId` | Parent span (absent for root spans) |
| `name` | Span name (e.g. `agent.run`, `model.call`, `tool.call`) |
| `kind` | OTEL span kind (1=Internal, 3=Client, 4=Consumer) |
| `startTimeUnixNano` | Start timestamp in nanoseconds |
| `endTimeUnixNano` | End timestamp in nanoseconds |
| `attributes` | Key-value metadata (see below) |
| `events` | Timed events attached to the span |
| `status` | `{"code": 1}` = OK, `{"code": 2}` = Error |

---

## AgentMesh Attributes

All AgentMesh-specific fields are emitted as attributes with the `agentmesh.*` prefix:

| Attribute | Description |
|---|---|
| `agentmesh.workflow.name` | Workflow identifier |
| `agentmesh.workflow.mode` | `sequential`, `parallel`, `hierarchical`, `event_driven` |
| `agentmesh.agent.name` | Agent identifier |
| `agentmesh.agent.role` | Agent role |
| `agentmesh.task.id` | Step ID |
| `agentmesh.model.provider` | Provider name (e.g. `openai`) |
| `agentmesh.model.name` | Model name (e.g. `gpt-4o-mini`) |
| `agentmesh.model.prompt_tokens` | Input token count |
| `agentmesh.model.completion_tokens` | Output token count |
| `agentmesh.model.cost_usd` | Cost in USD |
| `agentmesh.tool.name` | Tool identifier |
| `agentmesh.tool.permission` | Permission level |
| `agentmesh.tool.requires_approval` | `true` or `false` |
| `agentmesh.retry.attempt` | Retry attempt number |
| `agentmesh.error.type` | Error class name |
| `agentmesh.environment` | `development`, `production` |

---

## Events in Spans

Model calls, tool calls, memory operations, RAG retrievals, approvals, retries, and errors are attached as OTEL events within their parent span:

```json
{
  "name": "model.response",
  "timeUnixNano": "1714500001000000000",
  "attributes": [
    {"key": "output_text", "value": {"stringValue": "Research complete."}},
    {"key": "prompt_tokens", "value": {"intValue": 412}},
    {"key": "completion_tokens", "value": {"intValue": 87}},
    {"key": "cost_usd", "value": {"doubleValue": 0.000114}}
  ]
}
```

---

## Secret Redaction

All API keys and secret values are redacted before the OTEL JSON is returned or written to disk. Redacted values appear as `[REDACTED]`.

---

## Planned Features

| Feature | Status |
|---|---|
| Native OTLP collector push (streaming) | Planned — v0.4 |
| Configurable resource attributes | Planned |
| Batch export of multiple traces | Planned |
| Integration tests against a live collector | Planned |
