import assert from "node:assert/strict";
import { createServer } from "node:http";
import { afterEach, beforeEach, test } from "node:test";

import {
  getCurrentTraceId,
  InMemoryExporter,
  init,
  observe,
  score,
  shutdown,
  span,
  startSpan,
  trace,
  updateCurrentTrace,
  withActiveSpan,
} from "../dist/esm/index.js";

let exporter;

beforeEach(() => {
  exporter = new InMemoryExporter();
  init({ exporter, serviceName: "ts-test", environment: "test", flushIntervalMs: 10 });
});

afterEach(async () => {
  await shutdown();
});

async function spansByName() {
  await (await import("../dist/esm/index.js")).flush();
  return Object.fromEntries(exporter.spans.map((item) => [item.name, item]));
}

test("observe and trace build a nested trace with session, user, tags, and errors", async () => {
  const lookupOrder = observe(async (orderId) => ({ orderId, status: "shipped" }), { name: "lookup_order", kind: "tool" });
  const refund = observe(
    (orderId) => {
      throw new TypeError(`refunds for ${orderId} need approval`);
    },
    { name: "refund", kind: "tool" },
  );
  const supportAgent = observe(
    async (question) => {
      const order = await lookupOrder("A-1");
      assert.throws(() => refund("A-1"), TypeError);
      return `Order is ${order.status} (${question.length})`;
    },
    { name: "support_agent", kind: "agent" },
  );

  const answer = await trace("ticket", { sessionId: "chat-1", userId: "u-1", tags: ["beta"], metadata: { plan: "pro" } }, async (root) => {
    const result = await supportAgent("where is my order?");
    root.setOutput(result);
    return result;
  });
  assert.equal(answer, "Order is shipped (18)");

  const spans = await spansByName();
  assert.deepEqual(new Set(Object.keys(spans)), new Set(["ticket", "support_agent", "lookup_order", "refund"]));
  assert.equal(new Set(Object.values(spans).map((item) => item.traceId)).size, 1);
  assert.equal(spans.ticket.parentSpanId, undefined);
  assert.equal(spans.support_agent.parentSpanId, spans.ticket.spanId);
  assert.equal(spans.lookup_order.parentSpanId, spans.support_agent.spanId);
  assert.equal(spans.lookup_order.attributes["gen_ai.operation.name"], "execute_tool");
  assert.equal(spans.lookup_order.attributes["input.value"], "A-1");
  assert.deepEqual(JSON.parse(spans.lookup_order.attributes["output.value"]), { orderId: "A-1", status: "shipped" });
  assert.equal(spans.support_agent.attributes["gen_ai.agent.name"], "support_agent");
  assert.equal(spans.ticket.attributes["gen_ai.workflow.name"], "ticket");
  assert.equal(spans.ticket.attributes["agentmesh.metadata.plan"], "pro");
  for (const item of Object.values(spans)) {
    assert.equal(item.attributes["gen_ai.conversation.id"], "chat-1");
    assert.equal(item.attributes["user.id"], "u-1");
    assert.deepEqual(item.attributes["tag.tags"], ["beta"]);
  }
  assert.equal(spans.refund.status, "error");
  assert.equal(spans.refund.attributes["error.type"], "TypeError");
  assert.equal(spans.refund.events[0].name, "exception");
  assert.equal(spans.refund.events[0].attributes["exception.message"], "refunds for A-1 need approval");
  assert.ok(BigInt(spans.ticket.endTimeUnixNano) >= BigInt(spans.support_agent.endTimeUnixNano));
  assert.equal(exporter.resource["service.name"], "ts-test");
  assert.equal(exporter.resource["deployment.environment.name"], "test");
});

test("concurrent async work keeps parents straight", async () => {
  const step = observe(async (label) => {
    await new Promise((resolve) => setTimeout(resolve, Math.random() * 15));
    return label;
  }, { name: "step" });
  await Promise.all(
    ["a", "b", "c", "d"].map((label) => trace(`request-${label}`, { sessionId: `s-${label}` }, async () => Promise.all([step(label), step(label)]))),
  );
  await (await import("../dist/esm/index.js")).flush();
  const roots = exporter.spans.filter((item) => item.name.startsWith("request-"));
  assert.equal(roots.length, 4);
  for (const root of roots) {
    const children = exporter.spans.filter((item) => item.parentSpanId === root.spanId);
    assert.equal(children.length, 2);
    const label = root.name.slice(-1);
    for (const child of children) {
      assert.equal(child.traceId, root.traceId);
      assert.equal(child.attributes["input.value"], label);
      assert.equal(child.attributes["gen_ai.conversation.id"], `s-${label}`);
    }
  }
});

test("manual spans, usage, updateCurrentTrace, async generators, and scores", async () => {
  const tokens = observe(async function* stream(prompt) {
    for (const word of prompt.split(" ")) yield word;
  }, { name: "stream", kind: "llm" });

  await trace("chat", async (root) => {
    updateCurrentTrace({ sessionId: "late-session", userId: "u-9" });
    const words = [];
    for await (const word of tokens("hello big world")) words.push(word);
    assert.deepEqual(words, ["hello", "big", "world"]);

    const manual = startSpan("rerank", { kind: "retrieval", input: { query: "q" } });
    await withActiveSpan(manual, async () => {
      span("inner", (inner) => inner.setModel("claude-sonnet-5", { provider: "anthropic", temperature: 0.2 }).setUsage({ inputTokens: 1200, outputTokens: 80, cacheReadTokens: 1000 }));
    });
    manual.setOutput(["doc-1"]).end();
    score("helpfulness", 0.8, { comment: "good" });
    root.score("thumbs", true);
    assert.equal(getCurrentTraceId(), root.traceId);
  });
  score("orphan", 1);

  const spans = await spansByName();
  assert.deepEqual(JSON.parse(spans.stream.attributes["output.value"]), ["hello", "big", "world"]);
  assert.equal(spans.stream.attributes["gen_ai.conversation.id"], "late-session");
  assert.equal(spans.chat.attributes["user.id"], "u-9");
  assert.equal(spans.inner.parentSpanId, spans.rerank.spanId);
  assert.equal(spans.inner.attributes["gen_ai.usage.cache_read.input_tokens"], 1000);
  assert.equal(spans.inner.attributes["gen_ai.request.temperature"], 0.2);
  assert.equal(spans.rerank.attributes["openinference.span.kind"], "RETRIEVER");
  assert.deepEqual(exporter.scores.map((item) => [item.name, item.value, item.trace_id === spans.chat.traceId]), [
    ["helpfulness", 0.8, true],
    ["thumbs", true, true],
  ]);
  assert.equal(exporter.scores[1].span_id, spans.chat.spanId);
});

test("captureContent: false keeps inputs and outputs out of spans", async () => {
  exporter = new InMemoryExporter();
  init({ exporter, captureContent: false, flushIntervalMs: 10 });
  await trace("private", { input: "secret question" }, async (root) => root.setOutput("secret answer"));
  const spans = await spansByName();
  assert.equal(spans.private.attributes["input.value"], undefined);
  assert.equal(spans.private.attributes["output.value"], undefined);
});

test("HttpExporter posts OTLP/JSON and scores with the API key, retrying server errors", async () => {
  const requests = [];
  let failures = 1;
  const server = createServer((request, response) => {
    let body = "";
    request.on("data", (chunk) => (body += chunk));
    request.on("end", () => {
      requests.push({ path: request.url, auth: request.headers.authorization, body: JSON.parse(body) });
      if (request.url === "/v1/traces" && failures-- > 0) {
        response.writeHead(503).end("busy");
        return;
      }
      response.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ partialSuccess: {} }));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    const { flush } = await import("../dist/esm/index.js");
    init({ endpoint: `http://127.0.0.1:${port}/`, apiKey: "secret-key", serviceName: "http-test", flushIntervalMs: 10 });
    await trace("remote", { input: { n: 1 } }, async (root) => {
      span("child", { kind: "llm", attributes: { "gen_ai.request.model": "gpt-5-mini", ratio: 0.5, count: 3, flags: [true] } }, () => {});
      root.score("quality", 0.9);
    });
    await flush();

    const traces = requests.filter((item) => item.path === "/v1/traces");
    assert.equal(traces.length, 2); // one 503, then the retry
    assert.equal(traces[1].auth, "Bearer secret-key");
    const resourceSpans = traces[1].body.resourceSpans[0];
    assert.deepEqual(resourceSpans.resource.attributes.find((item) => item.key === "service.name").value, { stringValue: "http-test" });
    const spans = resourceSpans.scopeSpans[0].spans;
    const child = spans.find((item) => item.name === "child");
    const root = spans.find((item) => item.name === "remote");
    assert.equal(child.kind, 3);
    assert.equal(child.parentSpanId, root.spanId);
    assert.match(root.traceId, /^[0-9a-f]{32}$/);
    assert.match(root.startTimeUnixNano, /^\d{19}$/);
    const attributes = Object.fromEntries(child.attributes.map((item) => [item.key, item.value]));
    assert.deepEqual(attributes.ratio, { doubleValue: 0.5 });
    assert.deepEqual(attributes.count, { intValue: "3" });
    assert.deepEqual(attributes.flags, { arrayValue: { values: [{ boolValue: true }] } });
    const scorePost = requests.find((item) => item.path === "/api/scores");
    assert.equal(scorePost.body.name, "quality");
    assert.equal(scorePost.body.trace_id, root.traceId);
  } finally {
    server.close();
  }
});

test("a 200 response that is not JSON counts as delivered (no duplicate export)", async () => {
  let posts = 0;
  const server = createServer((request, response) => {
    request.resume();
    request.on("end", () => {
      if (request.url === "/v1/traces") posts += 1;
      response.writeHead(200, { "content-type": "text/plain" }).end("OK");
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const { flush } = await import("../dist/esm/index.js");
    init({ endpoint: `http://127.0.0.1:${server.address().port}`, flushIntervalMs: 10 });
    await trace("plain-text-receiver", async () => "done");
    await flush();
    assert.equal(posts, 1);
  } finally {
    server.close();
  }
});

test("a failing endpoint never throws into the application", async () => {
  init({ endpoint: "http://127.0.0.1:9", flushIntervalMs: 10 });
  const { flush } = await import("../dist/esm/index.js");
  const result = await trace("offline", async () => "still works");
  assert.equal(result, "still works");
  await flush();
});

test("CommonJS build exposes the same API", async () => {
  const { createRequire } = await import("node:module");
  const require = createRequire(import.meta.url);
  const cjs = require("../dist/cjs/index.js");
  assert.equal(typeof cjs.trace, "function");
  assert.equal(typeof cjs.instrumentOpenAI, "function");
  assert.equal(cjs.VERSION, "0.4.1");
});
