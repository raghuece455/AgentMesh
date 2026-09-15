import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import Anthropic from "@anthropic-ai/sdk";
import OpenAI from "openai";

import { flush, InMemoryExporter, init, instrumentAnthropic, instrumentOpenAI, shutdown, trace, uninstrumentOpenAI } from "../dist/esm/index.js";

let exporter;

beforeEach(() => {
  exporter = new InMemoryExporter();
  init({ exporter, flushIntervalMs: 10 });
});

afterEach(async () => {
  await shutdown();
});

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function sse(events, { named = false } = {}) {
  const text = events
    .map((event) => (event === "[DONE]" ? "data: [DONE]\n\n" : `${named ? `event: ${event.type}\n` : ""}data: ${JSON.stringify(event)}\n\n`))
    .join("");
  return new Response(text, { status: 200, headers: { "content-type": "text/event-stream" } });
}

function mockFetch(routes) {
  const calls = [];
  const fetch = async (url, init) => {
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: String(url), body });
    const pathname = new URL(String(url)).pathname;
    const route = Object.keys(routes).find((key) => pathname.endsWith(key.slice("/v1".length)));
    const handler = route ? routes[route] : undefined;
    if (!handler) return json({ error: { message: "not found" } }, 404);
    return handler(body);
  };
  return { fetch, calls };
}

async function spans() {
  await flush();
  return exporter.spans;
}

test("OpenAI chat completions: request, usage, output, and withResponse()", async () => {
  const { fetch } = mockFetch({
    "/v1/chat/completions": (body) =>
      json({
        id: "chatcmpl-1",
        object: "chat.completion",
        model: `${body.model}-2026-01-01`,
        choices: [{ index: 0, finish_reason: "stop", message: { role: "assistant", content: "Paris" } }],
        usage: { prompt_tokens: 120, completion_tokens: 5, prompt_tokens_details: { cached_tokens: 100 }, completion_tokens_details: { reasoning_tokens: 2 } },
      }),
  });
  const client = instrumentOpenAI(new OpenAI({ apiKey: "sk-test", baseURL: "https://api.openai.com/v1", fetch, maxRetries: 0 }));

  const answer = await trace("qa", async () => {
    const completion = await client.chat.completions.create({ model: "gpt-5-mini", messages: [{ role: "user", content: "Capital of France?" }], temperature: 0.1 });
    const { data, response } = await client.chat.completions.create({ model: "gpt-5-mini", messages: [{ role: "user", content: "again" }] }).withResponse();
    assert.equal(response.status, 200);
    return `${completion.choices[0].message.content}/${data.choices[0].message.content}`;
  });
  assert.equal(answer, "Paris/Paris");

  const [first, second] = (await spans()).filter((item) => item.name === "chat gpt-5-mini");
  const root = exporter.spans.find((item) => item.name === "qa");
  assert.ok(first && second);
  assert.equal(first.parentSpanId, root.spanId);
  assert.equal(first.kind, "CLIENT");
  assert.equal(first.attributes["gen_ai.provider.name"], "openai");
  assert.equal(first.attributes["gen_ai.request.temperature"], 0.1);
  assert.equal(first.attributes["gen_ai.response.model"], "gpt-5-mini-2026-01-01");
  assert.equal(first.attributes["gen_ai.usage.input_tokens"], 120);
  assert.equal(first.attributes["gen_ai.usage.cache_read.input_tokens"], 100);
  assert.equal(first.attributes["gen_ai.usage.reasoning.output_tokens"], 2);
  assert.deepEqual(first.attributes["gen_ai.response.finish_reasons"], ["stop"]);
  assert.deepEqual(JSON.parse(first.attributes["gen_ai.output.messages"]), [{ role: "assistant", content: "Paris" }]);
  assert.deepEqual(JSON.parse(first.attributes["gen_ai.input.messages"]), [{ role: "user", content: "Capital of France?" }]);
  assert.equal(second.attributes["gen_ai.usage.output_tokens"], 5);
});

test("OpenAI streaming: tokens, tool calls, and usage are assembled when the stream ends", async () => {
  const { fetch } = mockFetch({
    "/v1/chat/completions": () =>
      sse([
        { id: "c1", model: "gpt-5", choices: [{ index: 0, delta: { role: "assistant", content: "Hel" } }] },
        { id: "c1", model: "gpt-5", choices: [{ index: 0, delta: { content: "lo" } }] },
        { id: "c1", model: "gpt-5", choices: [{ index: 0, delta: { tool_calls: [{ index: 0, id: "call_1", function: { name: "lookup", arguments: '{"q":' } }] } }] },
        { id: "c1", model: "gpt-5", choices: [{ index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: '"x"}' } }] }, finish_reason: "tool_calls" }] },
        { id: "c1", model: "gpt-5", choices: [], usage: { prompt_tokens: 50, completion_tokens: 9 } },
        "[DONE]",
      ]),
  });
  const client = instrumentOpenAI(new OpenAI({ apiKey: "sk-test", fetch, maxRetries: 0 }));
  const stream = await client.chat.completions.create({ model: "gpt-5", messages: [], stream: true, stream_options: { include_usage: true } });
  let text = "";
  for await (const chunk of stream) text += chunk.choices[0]?.delta?.content ?? "";
  assert.equal(text, "Hello");

  const [llm] = await spans();
  assert.equal(llm.attributes["gen_ai.request.stream"], true);
  assert.equal(llm.attributes["gen_ai.usage.output_tokens"], 9);
  assert.deepEqual(llm.attributes["gen_ai.response.finish_reasons"], ["tool_calls"]);
  const [message] = JSON.parse(llm.attributes["gen_ai.output.messages"]);
  assert.equal(message.content, "Hello");
  assert.deepEqual(message.tool_calls, [{ id: "call_1", type: "function", function: { name: "lookup", arguments: '{"q":"x"}' } }]);
});

test("OpenAI Responses API, embeddings, errors, and uninstrument", async () => {
  const { fetch } = mockFetch({
    "/v1/responses": (body) =>
      json({ id: "resp_1", object: "response", model: body.model, status: "completed", output: [{ type: "message", content: [{ type: "output_text", text: "hi" }] }], usage: { input_tokens: 10, output_tokens: 3, input_tokens_details: { cached_tokens: 4 } } }),
    "/v1/embeddings": (body) => json({ object: "list", model: body.model, data: [{ index: 0, embedding: [0.1, 0.2, 0.3] }], usage: { prompt_tokens: 7, total_tokens: 7 } }),
    "/v1/chat/completions": () => json({ error: { message: "Invalid model", type: "invalid_request_error" } }, 400),
  });
  const client = instrumentOpenAI(new OpenAI({ apiKey: "sk-test", baseURL: "https://api.groq.com/openai/v1", fetch, maxRetries: 0 }));
  await client.responses.create({ model: "gpt-5", input: "hello", instructions: "be brief", previous_response_id: "resp_0" });
  await client.embeddings.create({ model: "text-embedding-3-small", input: "hello" });
  await assert.rejects(client.chat.completions.create({ model: "nope", messages: [] }), /Invalid model/);
  uninstrumentOpenAI(client);
  await client.embeddings.create({ model: "text-embedding-3-small", input: "untraced" });

  const all = await spans();
  assert.equal(all.length, 3);
  const [responses, embeddings, failed] = all;
  assert.equal(responses.attributes["gen_ai.provider.name"], "groq");
  assert.equal(responses.attributes["gen_ai.usage.cache_read.input_tokens"], 4);
  assert.equal(responses.attributes["gen_ai.system_instructions"], "be brief");
  assert.equal(responses.attributes["gen_ai.request.previous_response.id"], "resp_0");
  assert.equal(embeddings.kind, "CLIENT");
  assert.equal(embeddings.attributes["gen_ai.operation.name"], "embeddings");
  assert.equal(embeddings.attributes["gen_ai.embeddings.dimension.count"], 3);
  assert.equal(failed.status, "error");
  assert.match(failed.statusMessage, /Invalid model/);
});

test("Anthropic messages: cache-aware usage, streaming events, and the stream() helper", async () => {
  const message = {
    id: "msg_1",
    type: "message",
    role: "assistant",
    model: "claude-sonnet-5",
    content: [{ type: "text", text: "Hi there" }],
    stop_reason: "end_turn",
    usage: { input_tokens: 20, output_tokens: 6, cache_read_input_tokens: 1000, cache_creation_input_tokens: 50 },
  };
  const events = [
    { type: "message_start", message: { ...message, content: [], stop_reason: null, usage: { input_tokens: 20, output_tokens: 1, cache_read_input_tokens: 1000, cache_creation_input_tokens: 50 } } },
    { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
    { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "Hi " } },
    { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "there" } },
    { type: "content_block_stop", index: 0 },
    { type: "content_block_start", index: 1, content_block: { type: "tool_use", id: "tu_1", name: "search", input: {} } },
    { type: "content_block_delta", index: 1, delta: { type: "input_json_delta", partial_json: '{"q": "docs"}' } },
    { type: "content_block_stop", index: 1 },
    { type: "message_delta", delta: { stop_reason: "tool_use" }, usage: { output_tokens: 6 } },
    { type: "message_stop" },
  ];
  const { fetch } = mockFetch({
    "/v1/messages": (body) => (body.stream ? sse(events, { named: true }) : json(message)),
  });
  const client = instrumentAnthropic(new Anthropic({ apiKey: "sk-ant-test", fetch, maxRetries: 0 }));

  const created = await client.messages.create({ model: "claude-sonnet-5", max_tokens: 100, system: "be kind", messages: [{ role: "user", content: "hello" }] });
  assert.equal(created.content[0].text, "Hi there");

  const stream = await client.messages.create({ model: "claude-sonnet-5", max_tokens: 100, messages: [], stream: true });
  const types = [];
  for await (const event of stream) types.push(event.type);
  assert.equal(types.at(-1), "message_stop");

  const helper = client.messages.stream({ model: "claude-sonnet-5", max_tokens: 100, messages: [{ role: "user", content: "hi" }] });
  const final = await helper.finalMessage();
  assert.equal(final.stop_reason, "tool_use");

  const [plain, streamed, fromHelper] = await spans();
  assert.equal(plain.attributes["gen_ai.provider.name"], "anthropic");
  assert.equal(plain.attributes["gen_ai.usage.input_tokens"], 1070);
  assert.equal(plain.attributes["gen_ai.usage.cache_read.input_tokens"], 1000);
  assert.equal(plain.attributes["gen_ai.usage.cache_write.input_tokens"], 50);
  assert.equal(plain.attributes["gen_ai.system_instructions"], "be kind");
  assert.deepEqual(plain.attributes["gen_ai.response.finish_reasons"], ["end_turn"]);

  assert.equal(streamed.attributes["gen_ai.request.stream"], true);
  assert.equal(streamed.attributes["gen_ai.usage.output_tokens"], 6);
  const [output] = JSON.parse(streamed.attributes["gen_ai.output.messages"]);
  assert.deepEqual(output.content, [{ type: "text", text: "Hi there" }, { type: "tool_use", id: "tu_1", name: "search", input: { q: "docs" } }]);

  assert.equal(fromHelper.attributes["gen_ai.usage.input_tokens"], 1070);
  assert.deepEqual(fromHelper.attributes["gen_ai.response.finish_reasons"], ["tool_use"]);
});
