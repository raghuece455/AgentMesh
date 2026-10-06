"""The Python engine's half of the cross-language policy check.

The TypeScript SDK evaluates policies itself rather than asking the server per call, so the two
engines have to agree: otherwise the same policy stops a Python agent and lets a Node one through.
Both sides run the cases in ``sdks/typescript/test/fixtures/policy-cases.json`` and compare against
``policy-expected.json``, which this side produces.

Regenerate the expectations with::

    python -m tests.test_policy_parity

Neither language needs the other installed to run its half; the fixture is the contract.
"""

import json
from pathlib import Path

from agentmesh.policy import ActionContext, Policy, PolicyEngine, RunState

FIXTURES = Path(__file__).resolve().parent.parent / "sdks" / "typescript" / "test" / "fixtures"
CASES = FIXTURES / "policy-cases.json"
EXPECTED = FIXTURES / "policy-expected.json"


def _decisions(case: dict) -> list[list[dict]]:
    engine = PolicyEngine([Policy.from_spec(item["spec"], item.get("policy_id")) for item in case["policies"]])
    state = RunState()
    results: list[list[dict]] = []
    for step in case["steps"]:
        if "usage" in step:
            state.add_usage(**step["usage"])
            continue
        if "register" in step:
            register = step["register"]
            state.register_span(register["span_id"], register.get("parent_span_id"), register["is_agent"])
            continue
        context = ActionContext(trace_id="t1", **step["context"])
        results.append([
            {
                "action": decision.action,
                "enforced": decision.enforced,
                "rule": decision.rule,
                "reason": decision.reason,
                "target": decision.target,
                "policy": decision.policy_name,
                "details": decision.details,
            }
            for decision in engine.evaluate(context, state)
        ])
        if step.get("record"):
            state.record(context)
    return results


def _run_all() -> list[dict]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    return [{"name": case["name"], "results": _decisions(case)} for case in cases]


def test_the_shared_cases_still_produce_the_expected_decisions():
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    actual = _run_all()
    assert [case["name"] for case in actual] == [case["name"] for case in expected]
    for produced, wanted in zip(actual, expected, strict=True):
        assert produced["results"] == wanted["results"], produced["name"]
    assert sum(len(case["results"]) for case in actual) >= 30, "the fixture should cover real ground"


def test_the_cases_exercise_rules_limits_monitor_mode_and_hosts():
    """A parity fixture that only covered one path would pass while the engines diverged."""
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    rules = {decision["rule"] for case in expected for step in case["results"] for decision in step}
    assert {"no-prod-deletes", "refunds", "approved-models", "approved-domains-only"} <= rules
    assert {"limit:max_repeated_calls", "limit:max_cost_usd", "limit:max_tool_calls", "limit:max_agent_depth"} <= rules
    actions = {decision["action"] for case in expected for step in case["results"] for decision in step}
    assert {"deny", "warn", "require_approval"} <= actions
    assert any(
        not decision["enforced"] for case in expected for step in case["results"] for decision in step
    ), "monitor mode has to be covered"


if __name__ == "__main__":  # regenerate the expectations after changing the cases
    EXPECTED.write_text(json.dumps(_run_all(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {EXPECTED}")
