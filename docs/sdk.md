# Python tracing SDK

Trace any Python agent code with a decorator and two context managers. The SDK has no
dependencies beyond AgentMesh itself and never raises into your application: export errors are
logged and dropped.

```python
import agentmesh

agentmesh.init(service_name="support-bot")   # local SQLite by default


@agentmesh.observe(kind="tool")
def lookup_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "shipped"}


@agentmesh.observe(kind="agent")
async def support_agent(question: str) -> str:
    order = lookup_order("A-1001")
    return f"Your order is {order['status']}."


async def handle(question: str, chat_id: str, user_id: str) -> str:
    with agentmesh.trace("support-turn", session_id=chat_id, user_id=user_id, tags=["prod"]):
        answer = await support_agent(question)
        agentmesh.score("answered", True)
        return answer
```

Then open the dashboard (`agentmesh dashboard`) or ask your coding agent through the
[MCP server](mcp.md).

---

## `agentmesh.init(...)`

| Argument | Env var | Default | Meaning |
|---|---|---|---|
| `endpoint` | `AGENTMESH_ENDPOINT` | unset | Remote AgentMesh server, e.g. `http://agentmesh.internal:8787`. When set, spans are sent as OTLP/JSON to `<endpoint>/v1/traces`. |
| `api_key` | `AGENTMESH_API_KEY` | unset | Bearer token for a server running with `AGENTMESH_AUTH_MODE=api_key` |
| `db_path` | `AGENTMESH_DB_URL` | `.agentmesh/agentmesh.db` | Local database used when no endpoint is set |
| `service_name` | `AGENTMESH_SERVICE_NAME` / `OTEL_SERVICE_NAME` | `agentmesh-app` | Shown on every trace |
| `environment` | `AGENTMESH_ENVIRONMENT` | unset | e.g. `dev`, `staging`, `prod` |
| `enabled` | `AGENTMESH_TRACING_ENABLED` | `true` | `false` turns every span into a no-op |
| `capture_content` | `AGENTMESH_CAPTURE_CONTENT` | `true` | `false` never records inputs, outputs, prompts or completions |
| `exporter` | | | Custom `SpanExporter`, e.g. `InMemoryExporter()` in tests |

Calling `init()` is optional: the first span initializes the SDK from environment variables.

Spans are exported from a background thread. Short-lived processes (scripts, serverless handlers,
CLI tools) should call `agentmesh.flush()` before exiting; an `atexit` hook also flushes.

---

## `@agentmesh.observe`

```python
@agentmesh.observe                                  # name = function's qualified name, kind = "chain"
@agentmesh.observe(kind="tool", name="web_search")
@agentmesh.observe(kind="llm", capture_input=False)
```

Works on sync functions, `async def`, generators and async generators (the span covers the whole
iteration and records the yielded items). Arguments are recorded as the span input (a single
argument is recorded as-is; several become a JSON object; `self`/`cls` are skipped) and the return
value as the output. Exceptions are recorded with type, message and stack trace, then re-raised.

| `kind` | Recorded as |
|---|---|
| `chain` (default) | a generic step |
| `agent` | `invoke_agent`; spans below it are attributed to this agent |
| `tool` | `execute_tool`, with arguments and result |
| `llm` | a model call, priced from the model and usage you set |
| `embedding`, `retrieval`, `workflow`, `guardrail`, `evaluator` | the matching category |

---

## `agentmesh.trace(...)` and `agentmesh.span(...)`

```python
with agentmesh.trace("ticket-1234", session_id="chat-42", user_id="u-7", tags=["beta"], metadata={"plan": "pro"}):
    ...

async with agentmesh.span("rerank", kind="retrieval", input=query) as span:
    results = await rerank(query)
    span.set_output(results)
```

`trace()` starts a root span and sets session, user and tags for everything inside it.
`update_current_trace(session_id=..., user_id=..., tags=...)` sets them later, for example once the
user is authenticated.

### Span methods

| Method | Purpose |
|---|---|
| `set_input(value)` / `set_output(value)` | Any JSON-serializable value, dataclass or Pydantic model |
| `set_model(model, provider=None, temperature=..., top_p=..., max_tokens=...)` | Model request details |
| `set_usage(input_tokens, output_tokens, cache_read_tokens=..., cache_write_tokens=..., reasoning_tokens=..., cost_usd=...)` | Token usage. `input_tokens` includes cached tokens. Pass `cost_usd` if you know the exact cost. |
| `set_attribute(key, value)` / `set_attributes({...})` | Any OpenTelemetry attribute |
| `add_event(name, attributes)` | Point-in-time event |
| `record_exception(exc)` / `set_status("error", message)` | Mark the span failed |
| `score(name, value, comment=...)` | Score this span |

`agentmesh.get_current_span()` and `agentmesh.get_current_trace_id()` return the active span and
trace id (useful for linking logs or user feedback to a trace).

---

## Scores and user feedback

```python
agentmesh.score("user_feedback", True, comment="Solved my problem")   # inside a trace
agentmesh.score("correctness", 0.8, trace_id=saved_trace_id)          # later, e.g. from a feedback endpoint
```

Values can be numbers, booleans or labels (strings). Scores also arrive through
`POST /api/scores`, the dashboard thumbs up/down buttons, the MCP `add_score` tool, and OpenTelemetry
`gen_ai.evaluation.result` events.

---

## Auto-instrumentation for model clients

```python
import agentmesh
from anthropic import Anthropic
from openai import OpenAI

agentmesh.instrument_openai()        # all OpenAI clients: chat.completions, responses, embeddings
agentmesh.instrument_anthropic()     # all Anthropic clients: messages.create, messages.stream

client = OpenAI()
agentmesh.instrument_openai(client)  # or instrument a single client instance
```

Captured per call: provider (OpenAI, Azure OpenAI, and OpenAI-compatible endpoints such as Groq,
DeepSeek, OpenRouter or a local server), requested and served model, sampling parameters, input
messages, output messages and tool calls, finish reasons, and usage including cached and reasoning
tokens. Streaming responses are wrapped transparently; the span ends when the stream is exhausted or
closed. Sync and async clients are both supported. `uninstrument_openai()` /
`uninstrument_anthropic()` undo global patching.

---

## Testing with the SDK

```python
import agentmesh
from agentmesh import InMemoryExporter

def test_agent_calls_search():
    exporter = InMemoryExporter()
    agentmesh.init(exporter=exporter)
    run_agent("question")
    agentmesh.flush()
    assert any(span.name == "search" for span in exporter.spans)
```

---

## Experiments and evaluators

The SDK also runs your code over a dataset and scores it, with each item traced:

```python
from agentmesh import ExactMatch, LLMJudge

result = agentmesh.run_experiment(
    "support-regressions",
    task=support_agent,
    evaluators=[ExactMatch(), LLMJudge("correctness", judge=call_my_llm)],
    name="prompt-v2",
)
print(result.format_summary())

# Score traces already recorded in production:
agentmesh.evaluate_traces([LLMJudge("helpfulness", judge=call_my_llm)], store=store, limit=100)
```

See [datasets-and-experiments.md](datasets-and-experiments.md). For Node.js agents, see [typescript-sdk.md](typescript-sdk.md).
