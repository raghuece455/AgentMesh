import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

import agentmesh
from agentmesh import InMemoryExporter, PolicyViolation
from agentmesh.access import call_hosts, host_of, hosts_in
from agentmesh.dashboard import create_app
from agentmesh.mcp_server import AgentMeshMCPServer
from agentmesh.otlp import decode_json
from agentmesh.policy import ActionContext, Policy, PolicyEngine, RunState
from agentmesh.stores import create_store
from tests.test_swarm import agent, attr, otel_span, payload

TRACE_ID = "d" * 32

ALLOWLIST = """
name: egress
mode: enforce
rules:
  - name: approved-domains-only
    match: {kind: tool, host: "*"}
    except: {host: ["*.mycompany.com", "duckduckgo.com"]}
    action: deny
    reason: That domain is not on the allowlist.
"""


def seed_access(store, capture_content=True):
    """One agent that calls two hosts, reads an index and a table, and fails a request."""
    event = {
        "name": "agentmesh.resource.access",
        "timeUnixNano": "1780000000000000000",
        "attributes": [
            attr("agentmesh.access.target", "customers.invoices"),
            attr("agentmesh.access.kind", "db"),
            attr("agentmesh.access.operation", "read"),
            attr("agentmesh.access.detail", "200 rows"),
        ],
    }
    spans = [
        agent(TRACE_ID, "d1" * 8, "analyst", events=[event]),
        otel_span(TRACE_ID, "d2" * 8, "GET api.weather.gov", parent="d1" * 8, attributes=[
            ("http.request.method", "GET"),
            ("url.full", "https://api.weather.gov/points/40,-75"),
            ("server.address", "api.weather.gov"),
        ]),
        otel_span(TRACE_ID, "d3" * 8, "execute_tool fetch_page", parent="d1" * 8, attributes=[
            ("gen_ai.operation.name", "execute_tool"),
            ("gen_ai.tool.name", "fetch_page"),
            ("gen_ai.tool.call.arguments", json.dumps({"url": "https://blog.example.com/post/1"})),
        ]),
        otel_span(TRACE_ID, "d4" * 8, "retrieval", parent="d1" * 8, attributes=[
            ("gen_ai.operation.name", "retrieval"),
            ("gen_ai.data_source.id", "policies-index"),
            ("gen_ai.retrieval.query.text", "refund window"),
        ]),
        otel_span(TRACE_ID, "d5" * 8, "GET pastebin.com", parent="d1" * 8, error=True, attributes=[
            ("url.full", "https://pastebin.com/raw/abc"),
        ]),
    ]
    store.ingest_spans(decode_json(payload(spans, service="analyst-app")), capture_content=capture_content)


def test_host_parsing():
    assert host_of("https://API.Example.com:8443/path") == "api.example.com"
    assert host_of("example.com") == "example.com" and host_of("https://example.com.") == "example.com"
    assert host_of("") is None and host_of(None) is None and host_of(42) is None
    assert hosts_in({"url": "https://a.test/x", "nested": ["see http://b.test/y", 7]}) == ["a.test", "b.test"]
    assert hosts_in("no links here") == []
    assert hosts_in({"host": "c.test"}) == ["c.test"]  # named keys count even without a scheme
    assert call_hosts({"q": "x"}, {"server.address": "d.test"}) == ["d.test"]
    assert call_hosts(None, None) == []
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": "https://too.deep/"}}}}}}}
    assert hosts_in(deep) == []  # bounded walk
    assert len(hosts_in([f"https://host{index}.test/" for index in range(50)])) == 20  # bounded count


def test_records_from_spans(db_url):
    store = create_store(db_url)
    seed_access(store)
    rows = {(row["kind"], row["target"]): row for row in store.list_access(trace_id=TRACE_ID)}
    assert set(rows) == {
        ("network", "api.weather.gov"),
        ("network", "blog.example.com"),
        ("network", "pastebin.com"),
        ("retrieval", "policies-index"),
        ("db", "customers.invoices"),
    }
    assert rows[("network", "api.weather.gov")]["detail"] == "/points/40,-75"
    assert rows[("network", "api.weather.gov")]["agent"] == "analyst"
    assert rows[("network", "api.weather.gov")]["service"] == "analyst-app"
    assert rows[("db", "customers.invoices")]["detail"] == "200 rows"
    assert rows[("db", "customers.invoices")]["operation"] == "read"
    assert rows[("network", "pastebin.com")]["status"] == "failed"

    summary = {item["target"]: item for item in store.access_summary()}
    assert summary["api.weather.gov"]["calls"] == 1 and summary["api.weather.gov"]["agents"] == 1
    assert summary["pastebin.com"]["errors"] == 1

    seed_access(store)  # re-ingesting the same spans does not duplicate records
    assert len(store.list_access(trace_id=TRACE_ID)) == 5
    store.close()


def test_content_capture_off_keeps_attributes_but_not_arguments(tmp_path):
    store = create_store(str(tmp_path / "private.db"))
    seed_access(store, capture_content=False)
    targets = {(row["kind"], row["target"]) for row in store.list_access()}
    assert ("network", "api.weather.gov") in targets  # from span attributes
    assert ("network", "blog.example.com") not in targets  # the URL was inside captured content
    assert all(row["detail"] is None for row in store.list_access())
    store.close()


def test_new_destinations_are_flagged(tmp_path):
    from datetime import UTC, datetime, timedelta

    store = create_store(str(tmp_path / "new.db"))
    seed_access(store)
    since = (datetime.now(UTC) - timedelta(days=365 * 60)).isoformat()  # the fixture's spans are from 2026
    summary = {item["target"]: item for item in store.access_summary(since=since)}
    assert all(item["is_new"] for item in summary.values())
    later = {item["target"]: item for item in store.access_summary(since="2099-01-01T00:00:00+00:00")}
    assert later == {}
    assert all(not item["is_new"] for item in store.access_summary())
    store.close()


def test_host_rules_block_calls_before_they_run():
    engine = PolicyEngine([Policy.from_spec(ALLOWLIST)])
    state = RunState()

    def call(**kwargs):
        return ActionContext(kind="tool", name="fetch", trace_id="t", **kwargs)

    assert engine.evaluate(call(arguments={"url": "https://docs.mycompany.com/x"}), state) == []
    assert engine.evaluate(call(arguments={"query": "no url here"}), state) == []  # not a network call
    blocked = engine.evaluate(call(arguments={"url": "https://evil.test/steal"}), state)
    assert [decision.rule for decision in blocked] == ["approved-domains-only"]
    assert engine.evaluate(call(arguments={}, attributes={"server.address": "evil.test"}), state)
    assert engine.evaluate(ActionContext(kind="llm", name="chat", trace_id="t", arguments={"url": "https://evil.test"}), state) == []


def test_sdk_blocks_a_call_to_an_unapproved_host(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTMESH_GUARDRAILS_REFRESH_SECONDS", "0")
    db = str(tmp_path / "egress.db")
    store = create_store(db)
    store.create_policy({"text": ALLOWLIST})
    agentmesh.init(db_path=db, service_name="analyst-app", flush_interval=0.05)
    try:
        calls = []

        @agentmesh.observe(kind="tool")
        def fetch_page(url: str) -> str:
            calls.append(url)
            return "ok"

        with agentmesh.trace("browsing"):
            assert fetch_page("https://duckduckgo.com/?q=weather") == "ok"
            with pytest.raises(PolicyViolation, match="not on the allowlist"):
                fetch_page("https://evil.test/steal")
        agentmesh.flush()
    finally:
        agentmesh.shutdown()
    assert calls == ["https://duckduckgo.com/?q=weather"]
    # The blocked call is still recorded as a destination the agent tried to reach.
    assert {row["target"] for row in store.list_access()} == {"duckduckgo.com", "evil.test"}
    assert [row["status"] for row in store.list_access(target="evil.test")] == ["failed"]
    store.close()


def test_record_access_from_the_sdk(tmp_path):
    exporter = InMemoryExporter()
    agentmesh.init(exporter=exporter)
    try:
        with agentmesh.trace("run"):
            agentmesh.record_access("customers.invoices", kind="db", operation="read", detail="200 rows")
            agentmesh.record_access("secrets.env", kind="nonsense", operation="nonsense")
        agentmesh.record_access("outside", kind="file")  # no span: nothing to record on
        agentmesh.flush()
    finally:
        agentmesh.shutdown()
    events = exporter.spans[0].events
    assert [event["attributes"]["agentmesh.access.target"] for event in events] == ["customers.invoices", "secrets.env"]
    assert events[0]["attributes"]["agentmesh.access.detail"] == "200 rows"
    assert events[1]["attributes"]["agentmesh.access.kind"] == "other" and events[1]["attributes"]["agentmesh.access.operation"] == "read"


def test_access_api_cli_and_mcp(db_url):
    store = create_store(db_url)
    seed_access(store)
    client = TestClient(create_app(db_url))

    assert len(client.get("/api/access").json()) == 5
    assert {item["target"] for item in client.get("/api/access", params={"kind": "network"}).json()} == {"api.weather.gov", "blog.example.com", "pastebin.com"}
    assert [item["target"] for item in client.get("/api/access", params={"target": "weather"}).json()] == ["api.weather.gov"]
    assert client.get("/api/access", params={"agent": "nobody"}).json() == []
    assert client.get("/api/access", params={"kind": "network", "hours": 1}).json() == []  # fixture spans are older
    summary = client.get("/api/access/summary").json()
    assert {item["target"] for item in summary} == {"api.weather.gov", "blog.example.com", "pastebin.com", "policies-index", "customers.invoices"}

    detail = client.get(f"/api/traces/{TRACE_ID}").json()
    assert len(detail["access"]) == 5
    server = AgentMeshMCPServer(store)
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_access", "arguments": {"kind": "network"}}})
    assert {item["target"] for item in json.loads(response["result"]["content"][0]["text"])["destinations"]} == {"api.weather.gov", "blog.example.com", "pastebin.com"}

    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "agentmesh.cli", "--db", str(db_url), *args], capture_output=True, text=True, env=env, check=False)

    listed = cli("access", "summary", "--kind", "db")
    assert listed.returncode == 0, listed.stderr
    assert [item["target"] for item in json.loads(listed.stdout)] == ["customers.invoices"]
    records = json.loads(cli("access", "list", "--target", "pastebin", "--limit", "5").stdout)
    assert [item["status"] for item in records] == ["failed"]
    store.close()


def test_access_records_are_pruned_with_their_traces(tmp_path):
    store = create_store(str(tmp_path / "prune.db"))
    seed_access(store)
    pruned = store.prune_traces("2099-01-01T00:00:00+00:00")
    assert pruned["deleted_rows"]["resource_access"] == 5
    assert store.list_access() == []
    store.close()


def test_access_for_traces_merges_chunks(tmp_path, monkeypatch):
    """A swarm can have more traces than SQLite allows variables in one statement."""
    from agentmesh import access

    monkeypatch.setattr(access, "CHUNK", 2)
    store = create_store(str(tmp_path / "chunks.db"))
    seed_access(store)
    grouped = {row["target"]: row for row in store._read(access.access_for_traces, [TRACE_ID, "a" * 32, "b" * 32, "c" * 32, "e" * 32])}
    assert grouped["api.weather.gov"]["calls"] == 1 and grouped["pastebin.com"]["errors"] == 1
    assert len(grouped) == 5
    store.close()


def test_unknown_access_kind_is_rejected(db_url):
    client = TestClient(create_app(db_url))
    assert client.get("/api/access", params={"kind": "nonsense"}).status_code == 422
    assert client.get("/api/access/summary", params={"kind": "nonsense"}).status_code == 422
    assert client.get("/api/access", params={"kind": "db"}).status_code == 200


def test_target_search_is_a_substring_unless_exact(tmp_path):
    """Drilling into one destination must not pull in its subdomains."""
    store = create_store(str(tmp_path / "exact.db"))
    seed_access(store)
    store.ingest_spans(decode_json(payload([
        otel_span("f" * 32, "f1" * 8, "GET cdn.blog.example.com", attributes=[("url.full", "https://cdn.blog.example.com/a.js")]),
    ], service="analyst-app")))
    assert {row["target"] for row in store.list_access(target="blog.example.com")} == {"blog.example.com", "cdn.blog.example.com"}
    assert {row["target"] for row in store.list_access(target="blog.example.com", exact=True)} == {"blog.example.com"}
    store.close()


def test_links_in_a_tool_result_are_not_hosts_the_agent_reached(tmp_path):
    """A fetched page is full of links nobody called: only what the tool was asked to reach counts."""
    store = create_store(str(tmp_path / "result.db"))
    store.ingest_spans(decode_json(payload([
        otel_span("a" * 32, "a1" * 8, "execute_tool fetch_page", attributes=[
            ("gen_ai.operation.name", "execute_tool"),
            ("gen_ai.tool.name", "fetch_page"),
            ("gen_ai.tool.call.arguments", json.dumps({"url": "https://news.example.com/today"})),
            ("gen_ai.tool.call.result", "<a href='https://ads.tracker.test/x'>ad</a> <a href='https://other.test'>link</a>"),
        ]),
    ], service="reader")))
    assert {row["target"] for row in store.list_access()} == {"news.example.com"}
    store.close()
