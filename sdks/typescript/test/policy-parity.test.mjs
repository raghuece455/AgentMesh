/**
 * The TypeScript policy engine has to decide exactly what the Python one decides, or the same
 * policy stops a Python agent and lets a Node one through.
 *
 * Both sides run the cases in `fixtures/policy-cases.json` and compare against
 * `fixtures/policy-expected.json`, which Python produces. Neither language needs the other
 * installed to run its half, and a divergence in either fails here or in `tests/test_policy_parity.py`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { evaluate, RunState } from "../dist/esm/policy.js";

const fixtures = join(dirname(fileURLToPath(import.meta.url)), "fixtures");
const cases = JSON.parse(readFileSync(join(fixtures, "policy-cases.json"), "utf8"));
const expected = JSON.parse(readFileSync(join(fixtures, "policy-expected.json"), "utf8"));

/** The fixtures use the Python field names, so the context is translated once here. */
function toContext(raw) {
  return {
    kind: raw.kind,
    name: raw.name,
    traceId: "t1",
    spanId: raw.span_id,
    parentSpanId: raw.parent_span_id,
    agent: raw.agent,
    model: raw.model,
    provider: raw.provider,
    service: raw.service,
    environment: raw.environment,
    arguments: raw.arguments,
    attributes: raw.attributes,
  };
}

function run(kase) {
  const state = new RunState();
  const results = [];
  for (const step of kase.steps) {
    if (step.usage) {
      state.addUsage(step.usage.tokens ?? 0, step.usage.cost_usd ?? 0);
      continue;
    }
    if (step.register) {
      state.registerSpan(step.register.span_id, step.register.parent_span_id, step.register.is_agent);
      continue;
    }
    const context = toContext(step.context);
    results.push(
      evaluate(kase.policies, context, state).map((decision) => ({
        action: decision.action,
        enforced: decision.enforced,
        rule: decision.rule,
        reason: decision.reason,
        target: decision.target,
        policy: decision.policyName ?? null,
        details: decision.details ?? {},
      })),
    );
    if (step.record) state.record(context);
  }
  return results;
}

test("the TypeScript engine decides what the Python engine decides", () => {
  assert.equal(cases.length, expected.length, "a case was added without regenerating the expectations");
  let compared = 0;
  for (const [index, kase] of cases.entries()) {
    assert.equal(kase.name, expected[index].name);
    const results = run(kase);
    assert.equal(results.length, expected[index].results.length, `${kase.name}: step count`);
    for (const [step, decisions] of results.entries()) {
      assert.deepEqual(decisions, expected[index].results[step], `${kase.name}, step ${step}`);
      compared += 1;
    }
  }
  assert.ok(compared >= 30, `expected real coverage, compared only ${compared} decisions`);
});
