import assert from "node:assert/strict";
import test from "node:test";

import { callHosts, evaluate, globMatch, matches, RunState, shortName, verdict } from "../dist/esm/policy.js";

/** The same policy the Python engine is tested against, as the server would send it. */
const PROD_GUARD = [
  {
    policy_id: "policy_1",
    spec: {
      name: "prod-guard",
      limits: { max_repeated_calls: 2, max_cost_usd: 1 },
      rules: [
        {
          name: "no-prod-deletes",
          match: { tool: ["delete_*", "drop_*"], arguments: { environment: "production" } },
          action: "deny",
          reason: "Deleting production data needs a person.",
        },
        { name: "refunds", match: { tool: "issue_refund" }, action: "require_approval" },
        { name: "trusted-lookup", match: { tool: "lookup" }, action: "allow" },
        { name: "approved-models", match: { kind: "llm" }, except: { model: ["gpt-4.1*", "claude-*"] }, action: "deny" },
      ],
    },
  },
];

const tool = (name, args, extra = {}) => ({ kind: "tool", name, traceId: "t1", arguments: args, ...extra });
const llm = (model) => ({ kind: "llm", name: "chat", traceId: "t1", model });

test("rules match tools, arguments and models, and the first match wins", () => {
  const state = new RunState();

  const denied = verdict(evaluate(PROD_GUARD, tool("DELETE_user", { environment: "Production" }), state));
  assert.equal(denied.action, "deny");
  assert.equal(denied.rule, "no-prod-deletes");
  assert.equal(denied.reason, "Deleting production data needs a person.");

  assert.deepEqual(evaluate(PROD_GUARD, tool("delete_user", { environment: "staging" }), state), []);
  // No arguments at all: the argument condition cannot hold.
  assert.deepEqual(evaluate(PROD_GUARD, tool("delete_user"), state), []);

  assert.equal(verdict(evaluate(PROD_GUARD, tool("issue_refund", { amount: 5 }), state)).action, "require_approval");

  const blockedModel = verdict(evaluate(PROD_GUARD, llm("gpt-3.5-turbo"), state));
  assert.equal(blockedModel.target, "gpt-3.5-turbo");
  assert.match(blockedModel.reason, /blocked by rule 'approved-models'/);
  assert.deepEqual(evaluate(PROD_GUARD, llm("claude-sonnet-5"), state), []);
  // A tool never matches a model rule.
  assert.deepEqual(evaluate(PROD_GUARD, tool("gpt-3.5-turbo"), state), []);
});

test("a name derived from a function matches by its bare name", () => {
  const policies = [
    {
      spec: {
        name: "names",
        rules: [
          { name: "deletes", match: { tool: "delete_*" }, action: "deny" },
          { name: "agent", match: { agent: "planner" }, action: "warn" },
        ],
      },
    },
  ];
  const state = new RunState();
  assert.equal(evaluate(policies, tool("Tools.delete_user"), state)[0].rule, "deletes");
  assert.equal(evaluate(policies, tool("main.<locals>.delete_user"), state)[0].rule, "deletes");
  assert.equal(evaluate(policies, tool("search", undefined, { agent: "Crew.planner" }), state)[0].rule, "agent");
  // "v2" is the bare name, not a delete.
  assert.deepEqual(evaluate(policies, tool("undelete_user.v2"), state), []);
  assert.equal(shortName("Tools.delete_user"), "delete_user");
  assert.equal(shortName("api.example.com"), "com");
});

test("nested arguments, lists and input_regex", () => {
  const policies = [
    {
      spec: {
        name: "content",
        rules: [
          { name: "wire", match: { tool: "pay", arguments: { "payee.country": ["KP", "IR"] } }, action: "deny" },
          { name: "secrets", match: { kind: "any", input_regex: "sk-[a-z0-9]{8}" }, action: "warn" },
          { name: "agent", match: { agent: "research*", service: "bot" }, action: "require_approval" },
        ],
      },
    },
  ];
  const state = new RunState();
  assert.equal(evaluate(policies, tool("pay", { payee: { country: "IR" } }), state)[0].rule, "wire");
  assert.deepEqual(evaluate(policies, tool("pay", { payee: { country: "FR" } }), state), []);

  const warned = evaluate(policies, tool("post", { body: "key SK-abcd1234" }), state);
  assert.deepEqual(warned.map((decision) => decision.action), ["warn"]);
  assert.equal(verdict(warned), undefined, "warnings never stop a call");

  const scoped = evaluate(policies, tool("search", undefined, { agent: "research-bot", service: "bot" }), state);
  assert.equal(scoped[0].rule, "agent");
  assert.deepEqual(evaluate(policies, tool("search", undefined, { agent: "research-bot", service: "other" }), state), []);
});

test("limits stop loops and spend, and an allow rule exempts a call from them", () => {
  const state = new RunState();
  for (let i = 0; i < 2; i += 1) {
    const search = tool("search", { q: "same" });
    assert.deepEqual(evaluate(PROD_GUARD, search, state), []);
    state.record(search);
  }
  const loop = verdict(evaluate(PROD_GUARD, tool("search", { q: "same" }), state));
  assert.equal(loop.rule, "limit:max_repeated_calls");
  assert.match(loop.reason, /stopping a likely loop/);
  assert.equal(loop.details.used, 3);
  assert.deepEqual(evaluate(PROD_GUARD, tool("search", { q: "different" }), state), []);

  state.addUsage(1000, 1.0);
  const rules = new Set(evaluate(PROD_GUARD, tool("search", { q: "same" }), state).map((d) => d.rule));
  assert.deepEqual([...rules].sort(), ["limit:max_cost_usd", "limit:max_repeated_calls"], "every breach is reported");

  // "lookup" is explicitly allowed, which exempts it from the policy's limits too.
  for (let i = 0; i < 3; i += 1) state.record(tool("lookup", { id: 1 }));
  assert.deepEqual(evaluate(PROD_GUARD, tool("lookup", { id: 1 }), state), []);
});

test("count, duration and agent-nesting limits", () => {
  let now = 100;
  const state = new RunState(() => now);
  const policies = [
    {
      spec: {
        name: "limits",
        limits: {
          max_tool_calls: 2,
          max_llm_calls: 1,
          max_duration_seconds: 60,
          max_agent_depth: 2,
          max_child_agents: 1,
        },
      },
    },
  ];
  for (let i = 0; i < 2; i += 1) state.record(tool("a", { i }));
  assert.equal(evaluate(policies, tool("a", { i: 9 }), state)[0].rule, "limit:max_tool_calls");
  state.record(llm("gpt-4.1"));
  assert.equal(evaluate(policies, llm("gpt-4.1"), state)[0].rule, "limit:max_llm_calls");

  const root = { kind: "agent", name: "planner", traceId: "t1", spanId: "s1" };
  assert.deepEqual(evaluate(policies, root, state), []);
  state.record(root);
  const child = { kind: "agent", name: "worker", traceId: "t1", spanId: "s2", parentSpanId: "s1" };
  assert.deepEqual(evaluate(policies, child, state), []);
  state.record(child);
  const secondChild = { kind: "agent", name: "worker-2", traceId: "t1", spanId: "s3", parentSpanId: "s1" };
  assert.deepEqual(evaluate(policies, secondChild, state).map((d) => d.rule), ["limit:max_child_agents"]);

  // A tool span under an agent keeps that agent's depth, so an agent beneath it nests one deeper.
  state.registerSpan("s2-tool", "s2", false);
  const grandchild = { kind: "agent", name: "deep", traceId: "t1", spanId: "s4", parentSpanId: "s2-tool" };
  assert.deepEqual(evaluate(policies, grandchild, state).map((d) => d.rule), ["limit:max_agent_depth"]);

  now = 161;
  assert.ok(new Set(evaluate(policies, llm("x"), state).map((d) => d.rule)).has("limit:max_duration_seconds"));
});

test("monitor mode records without enforcing, and the strictest enforced verdict wins", () => {
  const monitor = { spec: { name: "watch", mode: "monitor", rules: [{ name: "all-tools", match: { kind: "tool" }, action: "deny" }] } };
  const approve = { spec: { name: "approve", rules: [{ name: "refund", match: { tool: "refund" }, action: "require_approval" }] } };
  const warn = { spec: { name: "warn", rules: [{ name: "refund-warn", match: { tool: "refund" }, action: "warn" }] } };
  const state = new RunState();

  const monitored = evaluate([monitor], tool("refund"), state);
  assert.equal(monitored[0].action, "deny");
  assert.equal(monitored[0].enforced, false);
  assert.equal(verdict(monitored), undefined, "monitor mode stops nothing");

  const governing = verdict(evaluate([monitor, approve, warn], tool("refund"), state));
  assert.equal(governing.action, "require_approval");
  assert.equal(governing.policyName, "approve");
});

test("host matching reads the hosts a call would reach", () => {
  const allowlist = [
    {
      spec: {
        name: "egress",
        rules: [
          {
            name: "approved-domains-only",
            match: { kind: "tool", host: "*" },
            except: { host: ["*.mycompany.com", "api.openai.com"] },
            action: "deny",
          },
        ],
      },
    },
  ];
  const state = new RunState();
  assert.equal(evaluate(allowlist, tool("fetch", { url: "https://pastebin.com/raw/x" }), state)[0].rule, "approved-domains-only");
  assert.deepEqual(evaluate(allowlist, tool("fetch", { url: "https://files.mycompany.com/a" }), state), []);
  // A call that reaches nowhere never matches a host rule, so a calculator is left alone.
  assert.deepEqual(evaluate(allowlist, tool("add", { a: 1, b: 2 }), state), []);

  assert.deepEqual(callHosts(tool("fetch", { url: "https://API.Example.com/path" })), ["api.example.com"]);
  assert.deepEqual(callHosts({ kind: "tool", name: "t", traceId: "t1", attributes: { "server.address": "db.internal" } }), [
    "db.internal",
  ]);
});

test("glob matching is case-insensitive and anchored", () => {
  assert.ok(globMatch("Delete_User", "delete_*"));
  assert.ok(globMatch("x", ["a", "x"]));
  assert.ok(!globMatch("predelete_user", "delete_*"), "patterns are anchored at both ends");
  assert.ok(!globMatch(undefined, "*"), "a missing value matches nothing, even a wildcard");
  assert.ok(matches({}, tool("anything")), "an empty match matches everything");
});
