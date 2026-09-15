// Run an experiment over a dataset stored in AgentMesh and grade it with built-in evaluators
// plus an LLM judge.
//
//   agentmesh datasets create capitals
//   agentmesh datasets add capitals --input '{"country": "France"}' --expected Paris
//   agentmesh datasets add capitals --input '{"country": "Japan"}' --expected Tokyo
//   node examples/experiment.mjs
import { contains, exactMatch, flush, init, llmJudge, runExperiment } from "agentmesh-sdk";

init({ serviceName: "ts-experiments" });

const capitals = { France: "Paris", Japan: "Kyoto" };

// Replace with a real model call, e.g. with the OpenAI SDK:
//   judge: async (prompt) => (await openai.responses.create({ model: "gpt-5-mini", input: prompt })).output_text
const judge = llmJudge({
  criteria: "correctness",
  judge: async (prompt) => (prompt.includes("Actual output:\nParis") ? '{"score": 1, "reason": "correct"}' : '{"score": 0, "reason": "wrong city"}'),
});

const result = await runExperiment({
  dataset: process.argv[2] ?? "capitals",
  name: process.argv[3] ?? "lookup-table-v1",
  task: async (input) => capitals[input.country] ?? "unknown",
  evaluators: [exactMatch(), contains(), judge],
});

await flush();
console.log(JSON.stringify({ experimentId: result.experimentId, summary: result.summary, url: result.url }, null, 2));
