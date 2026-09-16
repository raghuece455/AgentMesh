import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agentmesh.alerts import MAX_KEY_CHARS, _offender_key, render_payload
from agentmesh.dashboard import create_app
from agentmesh.otlp import decode_json
from agentmesh.stores import create_store
from tests.test_swarm import agent, attr, otel_span, payload
from tests.test_swarm_limits import SWARM_ID, seed_fleet


def at(seconds_ago: float) -> str:
    """A span timestamp that far in the past, so alert windows measured from now include it."""
    return str(int((datetime.now(UTC) - timedelta(seconds=seconds_ago)).timestamp() * 1_000_000_000))


def fetch(trace_id, span_id, agent_span, host, seconds_ago):
    span = otel_span(trace_id, span_id, "execute_tool fetch_page", parent=agent_span, attributes=[
        ("gen_ai.operation.name", "execute_tool"),
        ("gen_ai.tool.name", "fetch_page"),
        ("gen_ai.tool.call.arguments", json.dumps({"url": f"https://{host}/page"})),
    ])
    span["startTimeUnixNano"] = at(seconds_ago)
    span["endTimeUnixNano"] = at(seconds_ago - 1)
    return span


def seed_hosts(store, hosts, prefix="e", seconds_ago=20, swarm_id=None):
    """One researcher agent that fetches each host. ``prefix`` (one hex digit) keeps span ids unique."""
    trace_id = prefix * 32
    agent_span = f"{prefix}1" * 8
    spans = [{**agent(trace_id, agent_span, "researcher"), "startTimeUnixNano": at(seconds_ago + 1), "endTimeUnixNano": at(seconds_ago - 2)}]
    for index, host in enumerate(hosts):
        spans.append(fetch(trace_id, f"{prefix}{index + 2:x}" * 8, agent_span, host, seconds_ago))
    store.ingest_spans(decode_json(payload(spans, swarm_id=swarm_id)))


def message(to, agent_name, seconds_ago):
    return {
        "name": "agentmesh.agent.message",
        "timeUnixNano": at(seconds_ago),
        "attributes": [attr("agentmesh.message.to", to), attr("agentmesh.message.from", agent_name)],
    }


def seed_conversation(store, rounds, swarm_id="swarm_talk", one_way=False):
    """Two agents passing work to each other ``rounds`` times (or one of them talking into the void)."""
    trace_id = "f" * 32
    planner_events = [message("writer", "planner", 30 - index) for index in range(rounds)]
    writer_events = [] if one_way else [message("planner", "writer", 30 - index) for index in range(rounds)]
    spans = [
        {**otel_span(trace_id, "f0" * 8, "loop"), "startTimeUnixNano": at(31), "endTimeUnixNano": at(1)},
        {**agent(trace_id, "f1" * 8, "planner", parent="f0" * 8, events=planner_events), "startTimeUnixNano": at(31), "endTimeUnixNano": at(1)},
        {**agent(trace_id, "f2" * 8, "writer", parent="f0" * 8, events=writer_events), "startTimeUnixNano": at(31), "endTimeUnixNano": at(1)},
    ]
    store.ingest_spans(decode_json(payload(spans, swarm_id=swarm_id)))
    return trace_id


def seed_failing_swarm(store, failures=3, swarm_id="swarm_broken"):
    """Several worker traces in one swarm, most of which fail."""
    for index in range(failures + 1):
        trace_id = f"{index + 160:032x}"
        failed = index < failures
        root = {**otel_span(trace_id, f"{index + 160:02x}" * 8, "worker", error=failed), "startTimeUnixNano": at(25), "endTimeUnixNano": at(20)}
        store.ingest_spans(decode_json(payload([root], swarm_id=swarm_id)))


def rule(store, name, kind, threshold, **extra):
    filters = extra.pop("filters", {})
    return store.create_alert_rule({
        "name": name, "kind": kind, "threshold": threshold,
        "window": extra.pop("window", "15m"), "cooldown": extra.pop("cooldown", "1m"), "filters": filters, **extra,
    })


def fire(store, later=0):
    """Check every rule, optionally pretending it is ``later`` minutes from now (to clear a cooldown)."""
    now = datetime.now(UTC) + timedelta(minutes=later)
    return [event for event in store.check_alerts(deliver=False, now=now) if event["status"] == "firing"]


# -- new destinations ---------------------------------------------------------------------


def test_new_destination_fires_once_per_host(db_url):
    store = create_store(db_url)
    seed_hosts(store, ["api.weather.gov", "pastebin.com"])
    rule(store, "New destination", "new_destination", 1)

    fired = fire(store)
    assert len(fired) == 1
    targets = {item["target"] for item in fired[0]["details"]["items"]}
    assert targets == {"api.weather.gov", "pastebin.com"}
    assert fired[0]["value"] == 2
    assert "reached for the first time" in fired[0]["message"]

    assert fire(store) == []  # the same hosts are no longer new to the rule

    seed_hosts(store, ["transfer.sh"], prefix="b", seconds_ago=10)
    again = fire(store, later=2)  # past the rule's cooldown
    assert [item["target"] for item in again[0]["details"]["items"]] == ["transfer.sh"]
    store.close()


def test_new_destination_waits_for_the_threshold_and_respects_kind(db_url):
    store = create_store(db_url)
    seed_hosts(store, ["once.example.com"])
    rule(store, "Repeated new host", "new_destination", 2, filters={"access_kind": "network"})
    assert fire(store) == []  # reached once; the rule wants two accesses before it is worth a page

    seed_hosts(store, ["once.example.com"], prefix="b", seconds_ago=15)
    fired = fire(store)
    assert [item["target"] for item in fired[0]["details"]["items"]] == ["once.example.com"]
    assert fired[0]["details"]["items"][0]["accesses"] == 2
    store.close()


def test_a_host_seen_before_the_window_is_not_new(db_url):
    store = create_store(db_url)
    seed_hosts(store, ["api.weather.gov"], seconds_ago=3600)
    seed_hosts(store, ["api.weather.gov", "pastebin.com"], prefix="b", seconds_ago=20)
    rule(store, "Only genuinely new", "new_destination", 1, window="10m")
    fired = fire(store)
    assert [item["target"] for item in fired[0]["details"]["items"]] == ["pastebin.com"]
    store.close()


def test_new_destination_can_be_scoped_to_one_swarm(db_url):
    store = create_store(db_url)
    seed_hosts(store, ["inside.example.com"], swarm_id="swarm_scoped")
    seed_hosts(store, ["outside.example.com"], prefix="b")
    rule(store, "Swarm egress", "new_destination", 1, filters={"swarm": "swarm_scope*"})
    fired = fire(store)
    assert [item["target"] for item in fired[0]["details"]["items"]] == ["inside.example.com"]
    store.close()


# -- swarm anomalies ----------------------------------------------------------------------


def test_swarm_growth_alerts_once_and_names_the_swarm(db_url):
    store = create_store(db_url)
    seed_fleet(store, agents=6)
    rule(store, "Swarm too big", "swarm_agents", 4)

    fired = fire(store)
    assert len(fired) == 1 and fired[0]["value"] == 7
    item = fired[0]["details"]["items"][0]
    assert item["swarm_id"] == SWARM_ID and item["swarm_name"] == "market research"
    assert "has started 7 agents" in fired[0]["message"]
    assert fire(store) == []  # the same swarm is not reported again
    store.close()


def test_swarm_spawn_rate_and_cost(db_url):
    store = create_store(db_url)
    seed_fleet(store, agents=6)
    rule(store, "Spawn spike", "swarm_spawn_rate", 5)
    rule(store, "Swarm spend", "swarm_cost", 1)
    fired = {event["rule_name"]: event for event in fire(store)}
    assert fired["Spawn spike"]["value"] == 7
    assert fired["Swarm spend"]["value"] == pytest.approx(1.5)
    assert "$1.5000" in fired["Swarm spend"]["message"]
    store.close()


def test_swarm_filters_narrow_by_service_and_name(db_url):
    store = create_store(db_url)
    seed_fleet(store, agents=6)
    rule(store, "Other service", "swarm_agents", 1, filters={"service": "billing"})
    rule(store, "Other swarm", "swarm_agents", 1, filters={"swarm": "swarm_other*"})
    rule(store, "This one", "swarm_agents", 1, filters={"service": "crawler-fleet", "swarm": "market*"})
    assert [event["rule_name"] for event in fire(store)] == ["This one"]
    store.close()


def test_swarm_failures(db_url):
    store = create_store(db_url)
    seed_failing_swarm(store, failures=3)
    rule(store, "Swarm failing", "swarm_errors", 3)
    fired = fire(store)
    assert fired[0]["value"] == 3
    assert "3 failed traces out of 4" in fired[0]["message"]
    store.close()


def test_swarm_loop_needs_work_coming_back(db_url):
    store = create_store(db_url)
    seed_conversation(store, rounds=4, one_way=True)
    rule(store, "Delegation loop", "swarm_loop", 4)
    assert fire(store) == []  # a one-way fan-out is delegation, not a loop

    seed_conversation(store, rounds=4, swarm_id="swarm_pingpong")
    fired = fire(store)
    assert len(fired) == 1 and fired[0]["value"] == 8
    assert fired[0]["details"]["items"][0]["between"] == ["planner", "writer"]
    assert "planner and writer exchanged 8 messages" in fired[0]["message"]
    store.close()


def test_swarm_alerts_link_to_the_swarm_page(db_url, monkeypatch):
    store = create_store(db_url)
    monkeypatch.setenv("AGENTMESH_PUBLIC_URL", "https://mesh.example.com/")
    seed_fleet(store, agents=6)
    rule(store, "Swarm too big", "swarm_agents", 4, channel={"url": "https://hooks.slack.com/services/x/y/z"})
    fired = fire(store)
    body = render_payload({**fired[0], "rule": {"name": "Swarm too big"}}, "json")
    assert body["links"] == [f"https://mesh.example.com/?page=swarms&swarm={SWARM_ID}"]
    store.close()


# -- validation, API, and CLI -------------------------------------------------------------


def test_long_targets_stay_short_and_distinct_in_rule_state():
    # Every key a rule has seen is stored on the rule, so a 500-character file path must not grow it,
    # and two long paths that share a prefix must not be mistaken for the same destination.
    base = "file:" + "a" * 400
    first, second = _offender_key({"key": base + "one"}), _offender_key({"key": base + "two"})
    assert len(first) <= MAX_KEY_CHARS and first != second
    assert _offender_key({"trace_id": "0af7651916cd43dd8448eb211c80319c"}) == "0af7651916cd43dd8448eb211c80319c"


def test_filters_are_rejected_when_they_cannot_apply(db_url):
    store = create_store(db_url)
    with pytest.raises(ValueError, match="cannot filter by workflow"):
        rule(store, "bad scope", "swarm_agents", 5, filters={"workflow": "checkout"})
    with pytest.raises(ValueError, match="only applies to new_destination"):
        rule(store, "bad kind", "swarm_agents", 5, filters={"access_kind": "network"})
    with pytest.raises(ValueError, match="cannot filter by swarm"):
        rule(store, "bad swarm", "failure_count", 5, filters={"swarm": "swarm_x"})
    with pytest.raises(ValueError, match="access_kind must be one of"):
        rule(store, "bad access kind", "new_destination", 1, filters={"access_kind": "smtp"})
    with pytest.raises(ValueError, match="at least 2"):
        rule(store, "tiny loop", "swarm_loop", 1)
    store.close()


def test_swarm_alert_kinds_over_the_api(db_url):
    store = create_store(db_url)
    seed_fleet(store, agents=6)
    with TestClient(create_app(db_url)) as client:
        meta = client.get("/api/alerts/kinds").json()
        assert meta["groups"]["swarm_agents"] == "Swarms" and meta["groups"]["new_destination"] == "Access"
        created = client.post("/api/alerts/rules", json={"name": "Swarm growth", "kind": "swarm_agents", "threshold": 4, "filters": {"swarm": "market*"}})
        assert created.status_code == 201, created.text
        assert created.json()["filters"] == {"swarm": "market*"}
        rejected = client.post("/api/alerts/rules", json={"name": "Nope", "kind": "swarm_cost", "threshold": 1, "filters": {"workflow": "checkout"}})
        assert rejected.status_code == 422 and "cannot filter by workflow" in rejected.text
        fired = client.post("/api/alerts/check?deliver=false").json()["fired"]
        assert [event["rule_name"] for event in fired] == ["Swarm growth"]
    store.close()


def test_swarm_alert_from_the_cli(db_url):
    store = create_store(db_url)
    seed_fleet(store, agents=6)
    store.close()
    environment = {**os.environ, "PYTHONPATH": os.path.abspath("src")}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "agentmesh.cli", "--db", str(db_url), *args], capture_output=True, text=True, env=environment, check=False)

    add = cli("alerts", "add", "--name", "growth", "--kind", "swarm_agents", "--threshold", "4", "--swarm", "market*")
    assert add.returncode == 0, add.stderr
    assert json.loads(add.stdout)["filters"] == {"swarm": "market*"}
    checked = cli("alerts", "check", "--no-deliver")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["fired"][0]["kind"] == "swarm_agents"
