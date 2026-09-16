import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import agentmesh
from agentmesh import AgentHalted
from agentmesh.dashboard import create_app
from agentmesh.otlp import decode_json
from agentmesh.policy import Policy, PolicyError
from agentmesh.stores import create_store
from agentmesh.swarm_limits import applies_to, breaches, check_swarm_limits, swarm_usage
from tests.test_swarm import agent, llm, otel_span, payload, tool

SWARM_ID = "swarm_fleet"

LIMITS = """
name: swarm-safety
mode: enforce
swarm:
  max_agents: 4
  max_cost_usd: 1
  max_spawn_rate_per_minute: 10
"""


def seed_fleet(store, agents=6, now=None, service="crawler-fleet"):
    """One coordinator plus ``agents`` crawlers, started a few seconds ago."""
    moment = now or datetime.now(UTC)
    trace_id = "c" * 32

    def at(offset):
        return str(int((moment - timedelta(seconds=30 - offset)).timestamp() * 1_000_000_000))

    spans = [
        {**otel_span(trace_id, "c0" * 8, "web crawl"), "startTimeUnixNano": at(0), "endTimeUnixNano": None},
        {**agent(trace_id, "c1" * 8, "coordinator", parent="c0" * 8), "startTimeUnixNano": at(0), "endTimeUnixNano": None},
    ]
    for index in range(agents):
        span_id = f"{index + 16:02x}aa" * 4
        crawler = {**agent(trace_id, span_id, "crawler", parent="c1" * 8), "startTimeUnixNano": at(1 + index)}
        crawler["endTimeUnixNano"] = None if index >= agents - 2 else at(2 + index)
        if index >= agents - 2:
            crawler["status"] = {"code": 0}
        spans.append(crawler)
        spans.append({**llm(trace_id, f"{index + 16:02x}bb" * 4, span_id, 0.25), "startTimeUnixNano": at(1 + index), "endTimeUnixNano": at(2 + index)})
        spans.append({**tool(trace_id, f"{index + 16:02x}cc" * 4, span_id), "startTimeUnixNano": at(1 + index), "endTimeUnixNano": at(2 + index)})
    for span in spans:
        if span.get("endTimeUnixNano") is None:
            span.pop("endTimeUnixNano")
    store.ingest_spans(decode_json(payload(spans, swarm_id=SWARM_ID, service=service)))
    return trace_id


def test_swarm_usage_counts_agents_concurrency_spend_and_rate(db_url):
    store = create_store(db_url)
    seed_fleet(store, agents=6)
    usage = store._read(swarm_usage, [SWARM_ID])[SWARM_ID]  # noqa: SLF001 - the store's read helper
    assert usage["agents"] == 7 and usage["concurrent_agents"] == 3  # coordinator plus two crawlers
    assert usage["cost_usd"] == pytest.approx(1.5) and usage["tokens"] == 6 * 1100
    assert usage["spawn_rate_per_minute"] == 7 and usage["running_traces"] == 1
    assert usage["duration_minutes"] > 0
    store.close()


def test_breaches_are_reported_halt_once_and_stop_agents(db_url):
    store = create_store(db_url)
    store.create_policy({"text": LIMITS})
    seed_fleet(store, agents=6)

    reported = store.check_swarm_limits()
    rules = {item["rule"]: item for item in reported}
    assert set(rules) == {"swarm_limit:max_agents", "swarm_limit:max_cost_usd"}
    assert rules["swarm_limit:max_agents"]["used"] == 7 and rules["swarm_limit:max_agents"]["max"] == 4
    assert "past its limit of 4" in rules["swarm_limit:max_agents"]["reason"]
    assert sum(item["halted"] for item in reported) == 1  # one halt for the swarm, not one per limit

    halts = store.list_halts()
    assert [(halt["scope"], halt["value"], halt["created_by"]) for halt in halts] == [("swarm", SWARM_ID, "policy:swarm-safety")]
    decisions = store.list_policy_decisions()
    assert {item["rule"] for item in decisions} == set(rules)
    assert all(item["kind"] == "swarm" and item["enforced"] for item in decisions)

    # Running again neither halts twice nor duplicates decisions.
    again = store.check_swarm_limits()
    assert [item["halted"] for item in again] == [False, False] and [item["already_halted"] for item in again] == [True, True]
    assert len(store.list_halts()) == 1 and len(store.list_policy_decisions()) == 2

    # An agent that rejoins the swarm is stopped, wherever it runs.
    agentmesh.init(db_path=str(db_url), service_name="crawler-fleet", flush_interval=0.05)
    try:
        @agentmesh.observe(kind="agent")
        def crawler() -> str:
            return "page"

        agentmesh.get_client().guardrails.refresh_seconds = 0
        # A swarm halt stops the worker's trace before any agent in it starts.
        with pytest.raises(AgentHalted, match="past its limit of 4"), agentmesh.swarm(swarm_id=SWARM_ID), agentmesh.trace("another worker"):
            crawler()
    finally:
        agentmesh.shutdown()
    store.close()


def test_monitor_mode_records_without_halting(db_url):
    store = create_store(db_url)
    store.create_policy({"text": LIMITS.replace("mode: enforce", "mode: monitor")})
    seed_fleet(store, agents=6)
    reported = store.check_swarm_limits()
    assert reported and not any(item["halted"] for item in reported)
    assert store.list_halts() == []
    assert all(not item["enforced"] for item in store.list_policy_decisions())
    assert store.list_policy_decisions(action="would_block")
    store.close()


def test_enforce_false_is_a_dry_run(tmp_path):
    """A preview writes nothing: no halt, no decisions, and the first real breach still halts."""
    store = create_store(str(tmp_path / "dry.db"))
    store.create_policy({"text": LIMITS})
    seed_fleet(store, agents=6)
    assert store.check_swarm_limits(enforce=False)
    assert store.list_halts() == [] and store.list_policy_decisions() == []
    assert any(item["halted"] for item in store.check_swarm_limits())
    store.close()


def test_limits_apply_only_to_matching_swarms(tmp_path):
    store = create_store(str(tmp_path / "match.db"))
    store.create_policy({"text": LIMITS + "  match: {service: research-*}\n"})
    seed_fleet(store, agents=6, service="crawler-fleet")
    assert store.check_swarm_limits() == []
    assert store.list_halts() == []

    policy = Policy.from_spec({"name": "p", "swarm": {"max_agents": 1, "match": {"service": "crawler-*", "environment": "prod*"}}})
    assert applies_to(policy, {"swarm_id": "s", "service_name": "crawler-fleet", "environment": "production"})
    assert not applies_to(policy, {"swarm_id": "s", "service_name": "other", "environment": "production"})
    assert not applies_to(policy, {"swarm_id": "s", "service_name": "crawler-fleet", "environment": None})
    store.close()


def test_idle_swarms_are_left_alone(tmp_path):
    store = create_store(str(tmp_path / "idle.db"))
    store.create_policy({"text": LIMITS})
    old = datetime.now(UTC) - timedelta(days=2)
    seed_fleet(store, agents=6, now=old)
    store._write(lambda conn: conn.execute("update workflow_runs set status = 'succeeded' where trace_id = ?", ("c" * 32,)))
    assert store.check_swarm_limits() == []
    store.close()


def test_swarm_limit_thresholds():
    policy = Policy.from_spec({"name": "p", "swarm": {"max_agents": 3, "max_cost_usd": 5, "max_duration_minutes": 10}})
    swarm = {"swarm_id": "s", "name": "s"}
    # Counts must be exceeded; spend and time are reached.
    assert [item["rule"] for item in breaches([policy], swarm, {"agents": 3, "cost_usd": 4.99, "duration_minutes": 9})] == []
    broken = {item["limit"] for item in breaches([policy], swarm, {"agents": 4, "cost_usd": 5.0, "duration_minutes": 10})}
    assert broken == {"max_agents", "max_cost_usd", "max_duration_minutes"}
    assert breaches([Policy.from_spec({"name": "rules-only", "limits": {"max_steps": 1}})], swarm, {"agents": 99}) == []


def test_swarm_limits_validation():
    with pytest.raises(PolicyError) as caught:
        Policy.from_spec({"name": "bad", "swarm": {"max_robots": 1, "max_agents": 0, "match": {"colour": "red"}}})
    errors = " | ".join(caught.value.errors)
    assert "unknown swarm limit 'max_robots'" in errors and "swarm.max_agents must be a positive number" in errors
    assert "swarm.match: unknown key 'colour'" in errors
    with pytest.raises(PolicyError, match="swarm must be a mapping"):
        Policy.from_spec({"name": "bad", "swarm": [1]})
    policy = Policy.from_spec({"name": "ok", "swarm": {"max_agents": 500, "match": {"name": "research*"}}})
    assert Policy.from_spec(policy.to_spec()).swarm_limits == {"max_agents": 500.0}
    assert Policy.from_spec(policy.to_spec()).swarm_match == {"name": "research*"}


def test_swarm_limits_api_and_cli(db_url, tmp_path):
    store = create_store(db_url)
    store.create_policy({"text": LIMITS})
    seed_fleet(store, agents=6)
    client = TestClient(create_app(db_url))

    dry = client.post("/api/swarms/check", params={"enforce": False}).json()
    assert len(dry["breaches"]) == 2 and dry["halted"] == []
    checked = client.post("/api/swarms/check").json()
    assert checked["halted"] == [SWARM_ID]

    detail = client.get(f"/api/swarms/{SWARM_ID}").json()
    assert detail["halt"]["created_by"] == "policy:swarm-safety"
    assert detail["usage"]["agents"] == 7
    limits = {item["limit"]: item for item in detail["limits"]}
    assert limits["max_agents"]["breached"] and limits["max_agents"]["max"] == 4
    assert not limits["max_spawn_rate_per_minute"]["breached"]
    assert limits["max_cost_usd"]["label"] == "Spend across the swarm, in USD"
    assert [item["limit"] for item in detail["limits"]][:2] == ["max_agents", "max_cost_usd"]  # breached first

    released = client.post(f"/api/halts/{detail['halt']['halt_id']}/release")
    assert released.status_code == 200
    assert client.get(f"/api/swarms/{SWARM_ID}").json()["halt"] is None
    store.close()

    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}
    result = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db_url), "swarms", "check", "--no-enforce"],
        capture_output=True, text=True, env=env, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert {item["rule"] for item in json.loads(result.stdout)} == {"swarm_limit:max_agents", "swarm_limit:max_cost_usd"}


def test_no_swarm_policies_means_no_work(tmp_path):
    store = create_store(str(tmp_path / "none.db"))
    store.create_policy({"spec": {"name": "per-trace", "limits": {"max_steps": 5}}})
    seed_fleet(store, agents=6)
    assert store.check_swarm_limits() == []
    assert check_swarm_limits.__doc__
    store.close()


def test_a_released_halt_is_not_reapplied(tmp_path):
    """Releasing a policy halt is a person's decision: the same limit does not halt again."""
    store = create_store(str(tmp_path / "released.db"))
    store.create_policy({"text": LIMITS})
    seed_fleet(store, agents=6)
    halt = store.check_swarm_limits()[0]
    assert halt["halted"]
    store.release_halt(store.list_halts()[0]["halt_id"], "someone")

    again = store.check_swarm_limits()
    assert again and not any(item["halted"] for item in again)
    assert all(item["released"] for item in again)
    assert store.list_halts() == []

    # A different limit breaking later still halts the swarm.
    store.update_policy("swarm-safety", {"text": LIMITS + "  max_tokens: 100\n"})
    tokens = [item for item in store.check_swarm_limits() if item["limit"] == "max_tokens"]
    assert tokens and tokens[0]["halted"] and len(store.list_halts()) == 1
    store.close()
