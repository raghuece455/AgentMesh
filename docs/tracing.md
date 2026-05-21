# Tracing

Every `workflow.run()` call automatically creates a **trace** — a complete, immutable recording of everything that happened during that run. No instrumentation required.

---

## The Trace ID

When a workflow runs, AgentMesh generates a unique `trace_id`:

```python
result = await workflow.run({"topic": "AI observability"})

print(result.trace_id)   # e.g. "trc_a1b2c3d4e5f6"
print(result.status)     # "succeeded" or "failed"
print(result.output)     # text output from the last step
```

Paste the trace ID into the dashboard search box to jump directly to that run. Pass it to the CLI to inspect from the terminal.

---

## What Gets Recorded

AgentMesh records every meaningful event during execution:

| Event | What it captures |
|---|---|
| `workflow.started` | Workflow name, mode, input payload |
| `workflow.finished` | Final status, output, total cost, total duration |
| `task.started` | Task description, step ID |
| `task.finished` | Step output, retries used |
| `agent.started` | Agent name, role, incoming message |
| `agent.finished` | Agent output, all tool results |
| `model.call` | Provider, model, full prompt text, temperature |
| `model.response` | Output text, token counts, cost, latency |
| `model.failed` | Error type, latency, retry flag |
| `tool.started` | Tool name, input arguments, permission level |
| `tool.finished` | Result, duration, side-effect flag |
| `tool.failed` | Error type, arguments |
| `memory.read` | Key, namespace, agent |
| `memory.write` | Key, namespace, value, agent |
| `rag.retrieval` | Query, chunks returned, similarity scores, source metadata |
| `approval.requested` | Tool name, arguments, requesting agent |
| `approval.resolved` | Decision (approved/rejected), resolver, reason |
| `budget.exceeded` | Which limit was hit, current spend |
| `retry.attempt` | Attempt number, delay, error |

---

## Queryable Tables

Events are materialized into dedicated tables for fast querying in the dashboard and via the API:

| Table | What it stores |
|---|---|
| `spans` | Every timed unit of work with start/end/duration |
| `model_calls` | One row per LLM call with full prompt and response |
| `tool_calls` | Every tool invocation with inputs, outputs, approval status |
| `memory_operations` | Every memory read and write |
| `rag_retrievals` | Every vector search with chunks and scores |
| `cost_records` | Token counts and cost per model call |
| `provider_health` | Provider latency, error rate, rate-limit hits |
| `replay_checkpoints` | Full workflow state snapshots at each step |

---

## Span Hierarchy

Spans nest to show exactly what triggered what:

```
workflow "research-report"          ← root span
  └── task "plan"
        └── agent "planner"
              └── model.call (gpt-4o-mini)
  └── task "write"
        └── agent "writer"
              ├── tool.call "search_docs"
              └── model.call (gpt-4o-mini)
  └── task "review"
        └── agent "reviewer"
              └── model.call (gpt-4o-mini)
```

The Trace Explorer in the dashboard renders this as a waterfall timeline and a collapsible span tree.

---

## CLI Commands

```bash
# List recent traces
agentmesh traces list

# Show full detail for one trace (span tree + events)
agentmesh traces show <trace_id>

# Export as raw JSON
agentmesh traces export <trace_id> --out trace.json

# Export in OpenTelemetry JSON format
agentmesh traces export <trace_id> --format otel-json --out trace.otel.json

# Diagnose a failed run
agentmesh diagnose <trace_id>
```

---

## API Endpoints

```bash
# List traces (paginated)
GET /api/traces?limit=50&offset=0&status=failed

# Full trace detail
GET /api/traces/<trace_id>

# All events for a trace
GET /api/traces/<trace_id>/events

# Model calls for a trace
GET /api/traces/<trace_id>/model-calls

# Compare two traces side by side
GET /api/compare?left=<trace_id>&right=<trace_id>
```

---

## OpenTelemetry Export

AgentMesh exports traces in an OpenTelemetry-compatible JSON format. See [opentelemetry.md](opentelemetry.md) for the full field mapping.

```bash
agentmesh traces export <trace_id> --format otel-json --out trace.otel.json
```

---

## Dashboard: Trace Explorer

The **Trace Explorer** page provides:

- **Search** — filter by status, agent name, date range, or cost
- **Span tree** — nested view of every workflow, task, agent, and model call
- **Waterfall timeline** — visual timing diagram showing parallel execution
- **Event table** — every recorded event in chronological order
- **Span detail** — click any span for full inputs, outputs, and metadata
- **Raw JSON** — view or copy the complete trace as JSON
- **Export** — download as standard JSON or OTEL JSON
- **Replay** — launch the Replay Studio from any trace
