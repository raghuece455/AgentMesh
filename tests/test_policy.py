import pytest

from agentmesh.policy import ActionContext, Policy, PolicyEngine, PolicyError, RunState, simulate, span_action

POLICY = """
name: prod-guard
limits:
  max_repeated_calls: 2
  max_cost_usd: 1
rules:
  - name: no-prod-deletes
    match: {tool: ["delete_*", "drop_*"], arguments: {environment: production}}
    action: deny
    reason: Deleting production data needs a person.
  - name: refunds
    match: {tool: issue_refund}
    action: require_approval
  - name: trusted-lookup
    match: {tool: lookup}
    action: allow
  - name: approved-models
    match: {kind: llm}
    except: {model: ["gpt-4.1*", "claude-*"]}
    action: deny
"""


def tool(name, arguments=None, **extra):
    return ActionContext(kind="tool", name=name, trace_id="t1", arguments=arguments, **extra)


def llm(model):
    return ActionContext(kind="llm", name="chat", trace_id="t1", model=model)


def test_policy_parses_yaml_json_and_round_trips():
    policy = Policy.from_spec(POLICY)
    assert policy.name == "prod-guard" and policy.mode == "enforce"
    assert [rule.name for rule in policy.rules] == ["no-prod-deletes", "refunds", "trusted-lookup", "approved-models"]
    assert policy.limits == {"max_repeated_calls": 2.0, "max_cost_usd": 1.0}
    again = Policy.from_spec(policy.to_spec())
    assert again.to_spec() == policy.to_spec()
    assert Policy.from_spec('{"name": "json", "limits": {"max_steps": 5}}').limits == {"max_steps": 5.0}


def test_policy_validation_reports_every_problem():
    with pytest.raises(PolicyError) as caught:
        Policy.from_spec(
            {
                "mode": "strict",
                "extra": 1,
                "limits": {"max_widgets": 3, "max_cost_usd": -1, "max_repeated_calls": 0},
                "rules": [
                    {"name": "a", "action": "block", "match": {"colour": "red"}},
                    {"name": "a", "action": "deny", "match": {"input_regex": "("}},
                    {"action": "deny", "match": {"arguments": {}}},
                ],
                "approval": {"timeout_seconds": 0},
            }
        )
    errors = " | ".join(caught.value.errors)
    for expected in (
        "unknown top-level keys: extra",
        "name is required",
        "mode must be one of",
        "unknown limit 'max_widgets'",
        "limits.max_cost_usd must be a non-negative number",
        "max_repeated_calls must be at least 1",
        "action must be one of",
        "unknown key 'colour'",
        "duplicate rule name 'a'",
        "input_regex is not a valid regular expression",
        "arguments must be a non-empty mapping",
        "approval.timeout_seconds must be a positive number",
    ):
        assert expected in errors, expected
    with pytest.raises(PolicyError, match="at least one rule or limit"):
        Policy.from_spec({"name": "empty"})
    with pytest.raises(PolicyError, match="invalid YAML"):
        Policy.from_spec("name: [unclosed")
    with pytest.raises(PolicyError, match="policy is empty"):
        Policy.from_spec("   ")
    with pytest.raises(PolicyError, match="cannot contain '/'"):
        Policy.from_spec({"name": "team/prod", "limits": {"max_steps": 1}})
    with pytest.raises(PolicyError, match="quote it"):
        Policy.from_spec({"name": False, "limits": {"max_steps": 1}})  # what YAML makes of `name: off`


def test_rules_match_tools_arguments_models_and_first_match_wins():
    engine = PolicyEngine([Policy.from_spec(POLICY)])
    state = RunState()

    denied = PolicyEngine.verdict(engine.evaluate(tool("DELETE_user", {"environment": "Production"}), state))
    assert denied is not None and denied.action == "deny" and denied.rule == "no-prod-deletes"
    assert denied.reason == "Deleting production data needs a person."
    assert engine.evaluate(tool("delete_user", {"environment": "staging"}), state) == []
    assert engine.evaluate(tool("delete_user"), state) == []  # no arguments: the argument condition cannot hold

    approval = PolicyEngine.verdict(engine.evaluate(tool("issue_refund", {"amount": 5}), state))
    assert approval is not None and approval.needs_approval

    blocked_model = PolicyEngine.verdict(engine.evaluate(llm("gpt-3.5-turbo"), state))
    assert blocked_model is not None and blocked_model.target == "gpt-3.5-turbo"
    assert "blocked by rule 'approved-models'" in blocked_model.reason
    assert engine.evaluate(llm("claude-sonnet-5"), state) == []
    # a tool never matches a model rule, even with kind "any" style matching on names
    assert engine.evaluate(tool("gpt-3.5-turbo"), state) == []


def test_python_qualified_names_match_by_bare_name():
    engine = PolicyEngine([Policy.from_spec({"name": "names", "rules": [{"name": "deletes", "match": {"tool": "delete_*"}, "action": "deny"}, {"name": "agent", "match": {"agent": "planner"}, "action": "warn"}]})])
    state = RunState()
    assert engine.evaluate(tool("Tools.delete_user"), state)[0].rule == "deletes"
    assert engine.evaluate(tool("main.<locals>.delete_user"), state)[0].rule == "deletes"
    assert engine.evaluate(tool("search", agent="Crew.planner"), state)[0].rule == "agent"
    assert engine.evaluate(tool("undelete_user.v2"), state) == []  # "v2" is the bare name, not a delete


def test_nested_arguments_lists_and_input_regex():
    policy = Policy.from_spec(
        {
            "name": "content",
            "rules": [
                {"name": "wire", "match": {"tool": "pay", "arguments": {"payee.country": ["KP", "IR"]}}, "action": "deny"},
                {"name": "secrets", "match": {"kind": "any", "input_regex": r"sk-[a-z0-9]{8}"}, "action": "warn"},
                {"name": "agent", "match": {"agent": "research*", "service": "bot"}, "action": "require_approval"},
            ],
        }
    )
    engine = PolicyEngine([policy])
    state = RunState()
    assert engine.evaluate(tool("pay", {"payee": {"country": "IR"}}), state)[0].rule == "wire"
    assert engine.evaluate(tool("pay", {"payee": {"country": "FR"}}), state) == []
    warned = engine.evaluate(tool("post", {"body": "key SK-abcd1234"}), state)
    assert [decision.action for decision in warned] == ["warn"]
    assert PolicyEngine.verdict(warned) is None  # warnings never stop a call
    scoped = engine.evaluate(tool("search", agent="research-bot", service="bot"), state)
    assert scoped[0].rule == "agent"
    assert engine.evaluate(tool("search", agent="research-bot", service="other"), state) == []


def test_limits_stop_loops_spend_and_an_allow_rule_exempts_calls():
    engine = PolicyEngine([Policy.from_spec(POLICY)])
    state = RunState()
    for _ in range(2):
        search = tool("search", {"q": "same"})
        assert engine.evaluate(search, state) == []
        state.record(search)
    loop = PolicyEngine.verdict(engine.evaluate(tool("search", {"q": "same"}), state))
    assert loop is not None and loop.rule == "limit:max_repeated_calls"
    assert "stopping a likely loop" in loop.reason and loop.details["used"] == 3
    assert engine.evaluate(tool("search", {"q": "different"}), state) == []

    state.add_usage(tokens=1000, cost_usd=1.0)
    rules = {decision.rule for decision in engine.evaluate(tool("search", {"q": "same"}), state)}
    assert rules == {"limit:max_cost_usd", "limit:max_repeated_calls"}  # every breach is reported
    for _ in range(3):
        state.record(tool("lookup", {"id": 1}))
    assert engine.evaluate(tool("lookup", {"id": 1}), state) == []


def test_count_duration_and_agent_limits():
    now = [100.0]
    state = RunState(clock=lambda: now[0])
    engine = PolicyEngine(
        [
            Policy.from_spec(
                {
                    "name": "limits",
                    "limits": {"max_tool_calls": 2, "max_llm_calls": 1, "max_duration_seconds": 60, "max_agent_depth": 2, "max_child_agents": 1},
                }
            )
        ]
    )
    for index in range(2):
        state.record(tool("a", {"i": index}))
    assert engine.evaluate(tool("a", {"i": 9}), state)[0].rule == "limit:max_tool_calls"
    state.record(llm("gpt-4.1"))
    assert engine.evaluate(llm("gpt-4.1"), state)[0].rule == "limit:max_llm_calls"

    root = ActionContext(kind="agent", name="planner", trace_id="t1", span_id="s1")
    assert engine.evaluate(root, state) == []
    state.record(root)
    child = ActionContext(kind="agent", name="worker", trace_id="t1", span_id="s2", parent_span_id="s1")
    assert engine.evaluate(child, state) == []
    state.record(child)
    second_child = ActionContext(kind="agent", name="worker-2", trace_id="t1", span_id="s3", parent_span_id="s1")
    assert [decision.rule for decision in engine.evaluate(second_child, state)] == ["limit:max_child_agents"]
    state.register_span("s2-tool", "s2", is_agent=False)
    grandchild = ActionContext(kind="agent", name="deep", trace_id="t1", span_id="s4", parent_span_id="s2-tool")
    assert [decision.rule for decision in engine.evaluate(grandchild, state)] == ["limit:max_agent_depth"]

    now[0] = 161.0
    assert "limit:max_duration_seconds" in {decision.rule for decision in engine.evaluate(llm("x"), state)}


def test_monitor_mode_records_but_does_not_enforce_and_strictest_verdict_wins():
    monitor = Policy.from_spec({"name": "watch", "mode": "monitor", "rules": [{"name": "all-tools", "match": {"kind": "tool"}, "action": "deny"}]})
    approve = Policy.from_spec({"name": "approve", "rules": [{"name": "refund", "match": {"tool": "refund"}, "action": "require_approval"}]})
    warn = Policy.from_spec({"name": "warn", "rules": [{"name": "refund-warn", "match": {"tool": "refund"}, "action": "warn"}]})
    engine = PolicyEngine([monitor, warn, approve])
    decisions = engine.evaluate(tool("refund"), RunState())
    assert [(decision.policy_name, decision.enforced) for decision in decisions] == [("approve", True), ("warn", True), ("watch", False)]
    assert PolicyEngine.verdict(decisions).policy_name == "approve"
    assert PolicyEngine.verdict(PolicyEngine([monitor]).evaluate(tool("search"), RunState())) is None


def test_span_action_classifies_recorded_spans():
    assert span_action({"span_id": "a", "tool_name": "search", "event_type": "tool.started"}, "t").kind == "tool"
    assert span_action({"span_id": "b", "event_type": "tool.finished", "tool_name": "search"}, "t") is None
    assert span_action({"span_id": "c", "event_type": "model.call", "model": "gpt"}, "t") is None
    llm_call = span_action({"span_id": "d", "span_kind": "llm", "name": "chat gpt-4.1", "model": "gpt-4.1"}, "t")
    assert llm_call.kind == "llm" and llm_call.model == "gpt-4.1"
    assert span_action({"span_id": "e", "span_kind": "agent", "agent_name": "planner"}, "t").name == "planner"
    assert span_action({"span_id": "f", "span_kind": "chain", "name": "root"}, "t") is None


def test_simulate_reports_what_a_policy_would_have_stopped():
    def span(span_id, started, **fields):
        return {"span_id": span_id, "started_at": f"2026-09-01T10:00:{started:02d}+00:00", **fields}

    looping = (
        {"trace_id": "t-loop", "workflow_name": "support", "status": "succeeded", "started_at": "2026-09-01T10:00:00+00:00"},
        [
            span("root", 0, name="support", span_kind="chain"),
            *[span(f"s{index}", index + 1, parent_span_id="root", tool_name="search", input={"q": "same"}) for index in range(4)],
            span("r", 9, parent_span_id="root", tool_name="issue_refund", input={"amount": 5}),
        ],
    )
    healthy = ({"trace_id": "t-ok", "name": "ok"}, [span("x", 1, tool_name="lookup", input={"id": 1})])
    policy = Policy.from_spec(POLICY.replace("name: prod-guard", "name: prod-guard\nmode: monitor"))
    report = simulate([policy], [looping, healthy])
    assert report["traces_evaluated"] == 2 and report["actions_evaluated"] == 6
    assert report["traces_affected"] == 1
    assert report["blocked_calls"] == 2 and report["approval_calls"] == 1
    assert report["traces"][0]["trace_id"] == "t-loop"
    assert report["traces"][0]["first"]["rule"] == "limit:max_repeated_calls"
    assert report["traces"][0]["first"]["enforced"] is True  # simulation treats monitor policies as enforced
    by_rule = {entry["rule"]: entry for entry in report["rules"]}
    assert by_rule["limit:max_repeated_calls"]["calls"] == 2 and by_rule["refunds"]["traces"] == 1
