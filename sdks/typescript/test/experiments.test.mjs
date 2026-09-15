import assert from "node:assert/strict";
import { createServer } from "node:http";
import { afterEach, test } from "node:test";

import { contains, exactMatch, InMemoryExporter, init, inlineItemId, llmJudge, runEvaluator, runExperiment, shutdown, span } from "../dist/esm/index.js";

afterEach(async () => {
  await shutdown();
});

const CAPITALS = [
  { item_id: "fr", input: { country: "France" }, expected: "Paris" },
  { item_id: "jp", input: { country: "Japan" }, expected: "Tokyo" },
  { item_id: "pe", input: { country: "Peru" }, expected: "Lima" },
];

test("runExperiment scores inline items, traces each one, and survives task errors", async () => {
  const exporter = new InMemoryExporter();
  init({ exporter, flushIntervalMs: 10 });
  const judge = llmJudge({
    criteria: "correctness",
    judge: async (prompt) => (prompt.split("Actual output:")[1].includes("Paris") ? '{"score": 1, "reason": "right"}' : "Score: 0.25"),
  });
  const shortAnswer = Object.assign(({ output }) => String(output).length < 10, { evaluatorName: "short_answer" });

  const result = await runExperiment({
    dataset: CAPITALS,
    name: "v1",
    maxConcurrency: 2,
    evaluators: [exactMatch(), contains(), judge, shortAnswer],
    task: async (input) => {
      if (input.country === "Peru") throw new RangeError("no data for Peru");
      return span("lookup", { kind: "tool", input }, () => ({ France: "Paris", Japan: "Kyoto" })[input.country]);
    },
  });

  assert.equal(result.persisted, false);
  assert.equal(result.summary.items, 3);
  assert.equal(result.summary.errors, 1);
  assert.equal(result.score("exact_match"), 0.5);
  assert.equal(result.summary.scores.correctness.pass_rate, 0.5);
  assert.equal(result.summary.scores.short_answer.mean, 1);
  const byItem = Object.fromEntries(result.results.map((item) => [item.item_id, item]));
  assert.equal(byItem.pe.error, "RangeError: no data for Peru");
  assert.equal(byItem.pe.scores.length, 0);
  assert.equal(byItem.jp.scores.find((item) => item.name === "correctness").score, 0.25);

  await (await import("../dist/esm/index.js")).flush();
  const roots = exporter.spans.filter((item) => item.name === "experiment:v1");
  assert.equal(roots.length, 3);
  assert.ok(roots.every((item) => item.attributes["tag.tags"][0] === "experiment"));
  assert.equal(roots.find((item) => item.traceId === byItem.pe.trace_id).status, "error");
  const lookup = exporter.spans.find((item) => item.name === "lookup" && item.traceId === byItem.fr.trace_id);
  assert.equal(lookup.parentSpanId, roots.find((item) => item.traceId === byItem.fr.trace_id).spanId);
  const scores = exporter.scores.filter((item) => item.trace_id === byItem.jp.trace_id);
  assert.deepEqual(scores.map((item) => item.name).sort(), ["contains", "correctness", "exact_match", "short_answer"]);
  assert.equal(scores[0].source, "experiment");
  assert.equal(scores[0].metadata.item_id, "jp");
});

test("evaluators match the Python SDK", async () => {
  const run = (evaluator, args) => runEvaluator(evaluator, { input: null, expected: null, metadata: {}, ...args });
  assert.equal((await run(exactMatch(), { output: "  Paris ", expected: "paris" })).passed, true);
  assert.equal((await run(exactMatch(), { output: { a: 1 }, expected: { a: 1 } })).score, 1);
  assert.equal((await run(exactMatch(), { output: "x" })).label, "no_expected");
  const partial = await run(contains(), { output: "Paris and Lyon", expected: ["paris", "Nice"] });
  assert.equal(partial.score, 0.5);
  assert.equal(partial.comment, "missing: Nice");
  const broken = await run(() => {
    throw new Error("boom");
  }, { output: "x" });
  assert.equal(broken.label, "error");

  const judge = llmJudge({ criteria: "helpfulness", judge: () => "```json\n{\"score\": 4, \"reason\": \"useful\"}\n```", scale: [1, 5], threshold: 0.7 });
  const graded = await run(judge, { input: "q", output: "a" });
  assert.equal(graded.name, "helpfulness");
  assert.equal(graded.score, 0.75);
  assert.equal(graded.passed, true);
  assert.equal(graded.comment, "useful");
  assert.equal((await run(llmJudge({ criteria: "Is it polite?", judge: () => "no idea" }), { output: "a" })).label, "unparseable");
  const prompt = judge.buildPrompt({ input: { q: "$& {output}" }, output: "Paris", expected: null });
  assert.ok(prompt.includes('"$& {output}"') && prompt.includes("(none)") && prompt.includes('{"score"'));

  // Inline item ids are computed exactly like agentmesh.datasets.inline_item_id in Python.
  assert.equal(inlineItemId({ country: "France", nested: { b: [1, 2.5, null, true], a: "café" } }), "item_05686513f436d005");
  assert.equal(inlineItemId("hello"), "item_a1f2fbfe2c4ad817");
  // Python escapes DEL and every non-ASCII code unit (U+2028, astral characters as surrogate pairs).
  const text = `a${String.fromCharCode(0x7f)}b${String.fromCharCode(0x2028)}c`;
  assert.equal(inlineItemId(text), "item_0d99fe278c3a075e");
  assert.equal(inlineItemId({ emoji: String.fromCodePoint(0x1f600), n: [1, -2, true, null] }), "item_da035ca430cb2249");
});

test("runExperiment loads a dataset from the server and stores the experiment there", async () => {
  const requests = [];
  const server = createServer((request, response) => {
    let body = "";
    request.on("data", (chunk) => (body += chunk));
    request.on("end", () => {
      requests.push({ method: request.method, path: request.url, body: body ? JSON.parse(body) : null });
      const send = (status, payload) => response.writeHead(status, { "content-type": "application/json" }).end(JSON.stringify(payload));
      const url = new URL(request.url, "http://stub");
      if (request.method === "GET" && url.pathname === "/api/datasets/math%20set") {
        // One item per page regardless of the requested limit, so the SDK has to page with offset.
        const all = [{ item_id: "two", input: 2, expected: 4 }, { item_id: "three", input: 3, expected: 6 }];
        const offset = Number(url.searchParams.get("offset") ?? 0);
        return send(200, { dataset_id: "ds_1", name: "math set", item_count: all.length, items: all.slice(offset, offset + 1) });
      }
      if (request.method === "GET") return send(404, { detail: { error: "dataset_not_found" } });
      if (request.url === "/api/experiments") {
        return send(200, { summary: { items: requests.filter((item) => item.path === "/api/experiments").length, errors: 0, error_rate: 0, avg_latency_ms: 1, scores: { exact_match: { mean: 1, pass_rate: 1, count: 1, min: 1, max: 1 } } } });
      }
      return send(200, {});
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    init({ endpoint: `http://127.0.0.1:${port}`, flushIntervalMs: 10 });
    const result = await runExperiment({ dataset: "math set", task: (value) => value * 2, evaluators: [exactMatch()], name: "double" });
    assert.equal(result.persisted, true);
    assert.deepEqual(result.results.map((item) => item.output), [4, 6]);
    assert.deepEqual(
      requests.filter((item) => item.method === "GET" && item.path.startsWith("/api/datasets/math")).map((item) => new URL(item.path, "http://stub").searchParams.get("offset")),
      ["0", "1"],
    );
    assert.equal(result.score("exact_match"), 1);
    assert.ok(result.url.endsWith(`experiment=${result.experimentId}`));
    await assert.rejects(runExperiment({ dataset: "missing", task: (value) => value }), /HTTP 404/);

    const posts = requests.filter((item) => item.path === "/api/experiments");
    assert.equal(posts[0].body.status, "running");
    assert.equal(posts[0].body.dataset, "ds_1");
    assert.equal(posts.at(-1).body.status, "completed");
    assert.equal(posts.at(-1).body.results[0].item_id, "two");
    assert.ok(requests.some((item) => item.path === "/v1/traces"));
    const scorePost = requests.find((item) => item.path === "/api/scores");
    assert.equal(scorePost.body.passed, true);
    assert.equal(scorePost.body.trace_id, result.results[0].trace_id);
  } finally {
    server.close();
  }
});
