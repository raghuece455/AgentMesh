# Integrations: trace any agent framework

You don't need to rewrite your agent on top of AgentMesh to observe it. AgentMesh runs an
**OTLP/HTTP trace receiver** at `POST /v1/traces`, and understands the
[OpenTelemetry GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai)
plus the attribute styles used by the most common instrumentation libraries.

There are four ways in:

| Path | Best for | Setup |
|---|---|---|
| **OpenTelemetry exporter** | Frameworks that already emit OTel spans (OpenAI Agents SDK, Pydantic AI, LangGraph/LangChain, CrewAI, Google ADK, Strands, Vercel AI SDK, ...) | Point `OTEL_EXPORTER_OTLP_ENDPOINT` at AgentMesh |
| **AgentMesh Python SDK** | Your own agent loop, scripts, notebooks | `@agentmesh.observe`, `agentmesh.trace(...)` — see [sdk.md](sdk.md) |
| **AgentMesh TypeScript SDK** | Node.js agents and services | `npm install agentmesh-sdk`, `observe()`, `trace()` — see [typescript-sdk.md](typescript-sdk.md) |
| **Auto-instrumentation** | Direct use of the `openai` / `anthropic` clients | Python: `agentmesh.instrument_openai()` / `instrument_anthropic()`; TypeScript: `instrumentOpenAI(client)` / `instrumentAnthropic(client)` |

All of them produce the same traces: span tree, waterfall, model calls with token and cost
accounting, tool calls, retrieval, sessions, scores, and automatic insights.

---

## 1. Start AgentMesh

```bash
pip install "agentmesh-ai[otlp]"      # [otlp] adds protobuf decoding
agentmesh dashboard --port 8787
```

```
AgentMesh dashboard:   http://127.0.0.1:8787
OTLP trace endpoint:   http://127.0.0.1:8787/v1/traces
```

Or with Docker: `docker compose up --build` (protobuf support is included in the image).

## 2. Point your exporter at it

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:8787"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"   # or http/json
export OTEL_SERVICE_NAME="my-agent"
```

Exporters append `/v1/traces` to the base endpoint automatically. If you construct an exporter
in code, pass the full URL: `OTLPSpanExporter(endpoint="http://127.0.0.1:8787/v1/traces")`.

| Wire format | Content-Type | Requirement |
|---|---|---|
| OTLP/HTTP JSON | `application/json` | always available |
| OTLP/HTTP protobuf | `application/x-protobuf` | `pip install "agentmesh-ai[otlp]"` (the default format of the Python, Go and Java exporters) |
| gzip / deflate bodies | `Content-Encoding: gzip` | always available |

gRPC (port 4317) is not served directly. If your stack only speaks gRPC, run an
[OpenTelemetry Collector](otel-collector.yaml) with an `otlphttp` exporter pointing at AgentMesh.

### Authentication

When the server runs with `AGENTMESH_AUTH_MODE=api_key`, send the key as a bearer token:

```bash
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20${AGENTMESH_API_KEY}"
```

`X-AgentMesh-Api-Key: <key>` is accepted as well.

---

## Framework recipes

### OpenAI Agents SDK

```bash
pip install openai-agents openinference-instrumentation-openai-agents opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

```python
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="http://127.0.0.1:8787/v1/traces")))
OpenAIAgentsInstrumentor().instrument(tracer_provider=provider)
```

### Pydantic AI

Pydantic AI emits GenAI semantic-convention spans natively:

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import set_tracer_provider
from pydantic_ai import Agent

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # reads OTEL_EXPORTER_OTLP_ENDPOINT
set_tracer_provider(provider)
Agent.instrument_all()
```

### LangChain / LangGraph, CrewAI, LlamaIndex, and others

Use the matching [OpenInference](https://github.com/Arize-ai/openinference) instrumentor with the
same tracer provider setup as above, for example:

```python
from openinference.instrumentation.langchain import LangChainInstrumentor
LangChainInstrumentor().instrument(tracer_provider=provider)
```

### Vercel AI SDK (TypeScript)

Register OpenTelemetry (for example with `@vercel/otel`) and enable the AI SDK telemetry
integration as described in the [AI SDK telemetry docs](https://ai-sdk.dev/docs/ai-sdk-core/telemetry),
then set `OTEL_EXPORTER_OTLP_ENDPOINT` to your AgentMesh server. Both the current GenAI-convention
spans and the older `ai.*` attributes are understood. For code outside the AI SDK (tools, agent loops,
other clients), add the [TypeScript SDK](typescript-sdk.md).

### Anything else that speaks OpenTelemetry

Google ADK, Strands Agents, Semantic Kernel, and custom code using the OTel SDK with `gen_ai.*`
attributes all work the same way: export OTLP/HTTP to `/v1/traces`.

### Import a trace file

Saved an `ExportTraceServiceRequest` as JSON (for example from a collector's file exporter or a CI run)?

```bash
agentmesh ingest trace.otlp.json
```

---

## How spans are interpreted

Each span is classified, first match wins:

| AgentMesh category | Recognized by |
|---|---|
| LLM call | `gen_ai.operation.name` in `chat`, `text_completion`, `generate_content`; `openinference.span.kind=LLM`; Vercel `ai.*.doGenerate` / `ai.*.doStream`; any span carrying `gen_ai.request.model` or `gen_ai.usage.input_tokens` |
| Embeddings | `gen_ai.operation.name=embeddings`; `openinference.span.kind=EMBEDDING` |
| Tool call | `execute_tool`; `openinference.span.kind=TOOL`; `traceloop.span.kind=tool`; MCP `mcp.method.name=tools/call`; Vercel `ai.toolCall.*` |
| Agent | `invoke_agent`, `create_agent`; `openinference.span.kind=AGENT`; `traceloop.span.kind=agent` |
| Workflow | `invoke_workflow`; `traceloop.span.kind=workflow` |
| Retrieval | `retrieval`; `openinference.span.kind=RETRIEVER` / `RERANKER` |
| Memory | `create_memory`, `search_memory`, `update_memory`, `upsert_memory`, `delete_memory`, ... |
| Other | everything else is shown as a task/chain span |

Wrapper spans that only aggregate usage (for example Vercel's outer `ai.generateText`, or an
`invoke_agent` span) are **not** counted as model calls, so costs are never double-counted.

### Attributes used

| Field | Attributes (first present wins) |
|---|---|
| Model | `gen_ai.response.model`, `gen_ai.request.model`, `llm.model_name`, `ai.model.id` |
| Provider | `gen_ai.provider.name`, `gen_ai.system`, `llm.provider`, `ai.model.provider` (inferred from the model name if absent) |
| Input / output tokens | `gen_ai.usage.input_tokens` / `output_tokens`, `llm.token_count.prompt` / `completion`, `ai.usage.*` |
| Cache tokens | `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens` (and `cache_creation` variants), `llm.token_count.prompt_details.cache_read` |
| Reasoning tokens | `gen_ai.usage.reasoning.output_tokens`, `llm.token_count.completion_details.reasoning` |
| Reported cost | `agentmesh.cost_usd`, `gen_ai.usage.cost`, `llm.cost.total` (otherwise estimated, see [cost-tracking.md](cost-tracking.md)) |
| Prompt / completion | `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `llm.input_messages.N.*`, `gen_ai.prompt.N.*`, `input.value` / `output.value`, and GenAI content events |
| Agent | `gen_ai.agent.name` (child spans inherit the nearest agent ancestor) |
| Tool | `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` |
| Session | `gen_ai.conversation.id`, `session.id`, `langfuse.session.id`, `ai.telemetry.metadata.sessionId` |
| User | `user.id`, `enduser.id`, `langfuse.user.id`, `ai.telemetry.metadata.userId` |
| Tags | `tag.tags`, `agentmesh.tags` |
| Workflow name | `gen_ai.workflow.name`, `traceloop.workflow.name`; otherwise the root agent name or root span name |
| Environment | resource `deployment.environment.name` |
| Errors | span status `ERROR`, `error.type`, `exception` events |
| Scores | span events named `gen_ai.evaluation.result` (`gen_ai.evaluation.name`, `score.value`, `score.label`, `explanation`) |
| Swarm | `agentmesh.swarm.id` / `agentmesh.swarm.name` (resource or span; `swarm.id` also works), span links with `agentmesh.link.type` (`spawned_by`, `handoff`), and `agentmesh.agent.message` span events. See [swarms.md](swarms.md) |

Token semantics follow the conventions: input tokens **include** cached tokens and output tokens
include reasoning tokens. If an instrumentation reports cache tokens larger than input tokens
(Anthropic-style usage), AgentMesh adds them to the input total.

### Out-of-order and repeated delivery

Batch exporters send children before their parents. AgentMesh creates the trace on the first
span it sees (shown as `running`, named after `service.name`) and fills in the final name, status,
input/output and duration when the root span arrives. Re-sending a span is idempotent.

---

## Privacy controls

| Setting | Effect |
|---|---|
| `AGENTMESH_CAPTURE_CONTENT=false` (server) | Drop prompts, completions, tool arguments/results and document content at ingest. Tokens, costs, timings and errors are kept. |
| `agentmesh.init(capture_content=False)` (SDK) | Never record content in the first place |
| `AGENTMESH_MAX_CONTENT_CHARS` | Truncate stored content (default 100,000 characters per field) |
| Secret redaction | API keys, bearer tokens, private keys and credentials in URLs are redacted before storage |
| `agentmesh traces prune --older-than 30d` | Retention: delete old traces and everything attached to them |
