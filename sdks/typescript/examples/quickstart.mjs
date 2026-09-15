// Trace a small agent with the AgentMesh TypeScript SDK.
//
//   agentmesh dashboard                 # in another terminal (pip install agentmesh-ai)
//   node examples/quickstart.mjs
//
// Then open http://127.0.0.1:8787 -> Trace Explorer or Sessions.
import { flush, init, observe, score, trace } from "agentmesh-sdk";

init({ serviceName: "ts-quickstart", environment: "dev" });

const searchDocs = observe(
  async (query) => {
    await new Promise((resolve) => setTimeout(resolve, 40));
    return [`Refunds are processed within 5 business days (${query})`];
  },
  { name: "search_docs", kind: "tool" },
);

const answer = observe(
  async (question) => {
    const docs = await searchDocs(question);
    // With a real model: instrumentOpenAI(new OpenAI()) or instrumentAnthropic(new Anthropic()) records the LLM call.
    return `According to our policy: ${docs[0]}`;
  },
  { name: "support_agent", kind: "agent" },
);

for (const [turn, question] of ["How long do refunds take?", "Can I speed it up?"].entries()) {
  await trace(`support turn ${turn + 1}`, { sessionId: "ts-chat-1", userId: "customer-7", tags: ["quickstart"], input: question }, async (root) => {
    const reply = await answer(question);
    root.setOutput(reply);
    score("helpfulness", turn === 0 ? 1 : 0.5, { comment: "demo score" });
    return reply;
  });
}

await flush();
console.log("Sent 2 traces in session ts-chat-1");
