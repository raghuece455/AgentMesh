# TypeScript / JavaScript SDK

`agentmesh-sdk` traces Node.js agents, auto-instruments the OpenAI and Anthropic SDKs, attaches scores, and runs experiments. It lives in [`sdks/typescript`](../sdks/typescript) and sends OTLP/JSON to the AgentMesh server, so traces from TypeScript and Python services appear side by side.

```bash
npm install agentmesh-sdk
```

```ts
import { init, instrumentAnthropic, observe, trace } from "agentmesh-sdk";
import Anthropic from "@anthropic-ai/sdk";

init({ endpoint: "http://127.0.0.1:8787", serviceName: "research-agent" });
const anthropic = instrumentAnthropic(new Anthropic());

const research = observe(async (topic: string) => {
  const message = await anthropic.messages.create({
    model: "claude-sonnet-5",
    max_tokens: 1024,
    messages: [{ role: "user", content: `Summarize recent work on ${topic}` }],
  });
  return message.content;
}, { name: "researcher", kind: "agent" });

await trace("research-request", { sessionId: "s-1", userId: "u-9" }, () => research("agent evaluation"));
```

The [package README](../sdks/typescript/README.md) is the full reference: options, span API, scores, integrations, and experiments.

## How it maps to AgentMesh

| SDK | OpenTelemetry attribute | Dashboard |
|---|---|---|
| `trace(..., { sessionId })` | `gen_ai.conversation.id` | Sessions |
| `userId`, `tags`, `metadata` | `user.id`, `tag.tags`, `agentmesh.metadata.*` | Trace badges and filters |
| `kind: "agent" / "tool" / "llm"` | `gen_ai.operation.name`, `openinference.span.kind`, `gen_ai.agent.name`, `gen_ai.tool.name` | Span tree, Agents, Tools |
| `setInput` / `setOutput` | `input.value` / `output.value` (tool spans also `gen_ai.tool.call.arguments` / `result`) | Inspector |
| `setModel`, `setUsage` | `gen_ai.request.model`, `gen_ai.provider.name`, `gen_ai.usage.*` | Models, Costs |
| `recordException` | `exception` event, `error.type`, status error | Insights root cause |
| `score()` | `POST /api/scores` | Insights & Scores |

These are the same attributes the Python SDK writes, so insights, pricing, and alerts treat both languages identically.

## Serverless and edge

- Call `await flush()` at the end of each handler (AWS Lambda, Vercel Node.js functions, and similar), because the process may freeze before the background batch is sent.
- The SDK uses `node:async_hooks`, `node:crypto`, and global `fetch`, so it runs on Node.js 18+ and runtimes with Node compatibility. Browsers are not supported; send browser telemetry through your backend.

## Develop the SDK

```bash
cd sdks/typescript
npm ci
npm test          # builds ESM + CJS, then runs node:test with mocked OpenAI/Anthropic HTTP
```

Tests use the real `openai` and `@anthropic-ai/sdk` packages with a mocked `fetch`, so they need no API keys. CI also runs the examples against a live AgentMesh server.
