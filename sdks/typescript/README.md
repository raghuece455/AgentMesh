# agentmesh-sdk

Trace, score, and evaluate AI agents written in TypeScript or JavaScript, and see every run in [AgentMesh](https://github.com/raghuece455/AgentMesh), the free, open-source, self-hosted observability platform for AI agents.

- `observe()`, `trace()`, and `span()` build nested traces across async code, with sessions, users, and tags
- `instrumentOpenAI()` and `instrumentAnthropic()` record model, tokens (including cache and reasoning tokens), prompts, outputs, and tool calls, streaming included
- `score()` attaches feedback and eval results to traces
- `runExperiment()` runs your agent over a dataset and grades it with `exactMatch()`, `contains()`, and `llmJudge()`
- Sends standard OpenTelemetry (OTLP/JSON) with GenAI semantic-convention attributes; no dependencies

Requires Node.js 18+ (or Bun/Deno with Node compatibility). Works from ESM and CommonJS.

## Install

```bash
pip install agentmesh-ai && agentmesh dashboard      # the server, http://127.0.0.1:8787
npm install agentmesh-sdk
```

## Trace an agent

```ts
import OpenAI from "openai";
import { flush, init, instrumentOpenAI, observe, score, trace } from "agentmesh-sdk";

init({ serviceName: "support-bot" });             // AGENTMESH_ENDPOINT, default http://127.0.0.1:8787
const openai = instrumentOpenAI(new OpenAI());

const lookupOrder = observe(
  async (orderId: string) => ({ orderId, status: "shipped" }),
  { name: "lookup_order", kind: "tool" },
);

const supportAgent = observe(async (question: string) => {
  const order = await lookupOrder("A-1001");
  const response = await openai.responses.create({ model: "gpt-5-mini", input: `${question}\nOrder: ${JSON.stringify(order)}` });
  return response.output_text;
}, { name: "support_agent", kind: "agent" });

await trace("support-turn", { sessionId: "chat-42", userId: "u-7", tags: ["beta"] }, async (root) => {
  const answer = await supportAgent("Where is my order?");
  root.setOutput(answer);
  score("resolved", true);
});

await flush();                                     // before a script or serverless handler exits
```

Open the dashboard: the trace shows `support_agent` → `lookup_order` and the model call with tokens and cost; **Sessions** groups turns of `chat-42`.

## API

### `init(options?)`

| Option | Env var | Default |
|---|---|---|
| `endpoint` | `AGENTMESH_ENDPOINT` | `http://127.0.0.1:8787` |
| `apiKey` | `AGENTMESH_API_KEY` | none (sent as `Authorization: Bearer`) |
| `serviceName` | `AGENTMESH_SERVICE_NAME`, `OTEL_SERVICE_NAME` | `agentmesh-app` |
| `environment` | `AGENTMESH_ENVIRONMENT` | none |
| `enabled` | `AGENTMESH_TRACING_ENABLED` | `true` |
| `captureContent` | `AGENTMESH_CAPTURE_CONTENT` | `true` (set `false` to keep prompts and outputs out of traces) |
| `flushIntervalMs`, `maxBatchSize`, `maxQueueSize` | | `1000`, `512`, `10000` |
| `headers` | | extra HTTP headers |
| `exporter` | | custom exporter, e.g. `new InMemoryExporter()` in tests |

Spans are batched and sent in the background. Export errors never reach your code (set `AGENTMESH_DEBUG=true` to log them). Call `flush()` before a short-lived process exits; `shutdown()` flushes and stops.

### Spans

```ts
observe(fn, { name?, kind?, captureInput?, captureOutput?, attributes? })  // wraps sync, async, and async generator functions
trace(name, { sessionId?, userId?, tags?, metadata?, input?, kind? }, async (span) => ...)
span(name, { kind?, input?, attributes? }, (span) => ...)                   // ends when the callback or its promise settles
startSpan(name, options) + withActiveSpan(span, fn) + span.end()            // manual control
updateCurrentTrace({ sessionId?, userId?, tags? })
getCurrentSpan(), getCurrentTraceId()
```

`kind` is `chain` (default), `agent`, `tool`, `llm`, `embedding`, `retrieval`, `workflow`, `guardrail`, or `evaluator`. A `Span` has `setInput`, `setOutput`, `setAttribute(s)`, `setModel(model, { provider, temperature, ... })`, `setUsage({ inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens, reasoningTokens, costUsd })`, `addEvent`, `recordException`, `setStatus`, and `score`. Errors thrown inside a span are recorded and re-thrown.

Context follows async work through `AsyncLocalStorage`, so concurrent requests keep separate traces.

### Scores

```ts
score("helpfulness", 0.8, { comment: "clear answer" });            // current trace
score("thumbs_up", false, { traceId, spanId, source: "feedback" }); // any trace
```

### OpenAI and Anthropic

```ts
const openai = instrumentOpenAI(new OpenAI());          // chat.completions, responses, embeddings
const anthropic = instrumentAnthropic(new Anthropic()); // messages.create, messages.stream, beta.messages
```

Streaming responses are recorded when the stream finishes. `.withResponse()` keeps working. Any OpenAI-compatible base URL works (Azure OpenAI, Groq, OpenRouter, vLLM, Ollama); the provider is detected from the URL. For OpenAI chat streams, pass `stream_options: { include_usage: true }` to get token counts.

### Experiments

```ts
import { contains, exactMatch, llmJudge, runExperiment } from "agentmesh-sdk";

const result = await runExperiment({
  dataset: "refund-questions",                     // a dataset on the server, or [{ input, expected }]
  name: "prompt-v2",
  task: async (input, item) => supportAgent(input.question),
  evaluators: [
    exactMatch(),
    contains(),
    llmJudge({ criteria: "correctness", judge: async (prompt) => (await openai.responses.create({ model: "gpt-5-mini", input: prompt })).output_text }),
    Object.assign(({ output }) => String(output).length < 500, { evaluatorName: "short_answer" }),
  ],
});
console.log(result.summary.scores, result.url);
```

Each item runs in its own trace; scores are attached to those traces and the experiment is stored on the server, where the dashboard compares it with other runs. See [Datasets, Experiments, and LLM-as-Judge](https://github.com/raghuece455/AgentMesh/blob/main/docs/datasets-and-experiments.md).

## Other OpenTelemetry sources

Already using the Vercel AI SDK, OpenLLMetry, or another OpenTelemetry instrumentation? Point its OTLP exporter at `http://127.0.0.1:8787/v1/traces`; AgentMesh understands those attributes too, and this SDK's spans appear in the same traces view.

## License

MIT
