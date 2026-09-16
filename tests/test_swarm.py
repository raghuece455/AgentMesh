import asyncio
import json
import os
import subprocess
import sys
import threading

import pytest
from fastapi.testclient import TestClient

import agentmesh
from agentmesh import AgentHalted, InMemoryExporter
from agentmesh.dashboard import create_app
from agentmesh.mcp_server import AgentMeshMCPServer
from agentmesh.otlp import decode_json, encode_json
from agentmesh.stores import create_store
from agentmesh.swarms import analyze_swarm

BASE_NS = 1_780_000_000_000_000_000


def attr(key, value):
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": value}}


def otel_span(trace_id, span_id, name, *, parent=None, start=0, end=1, attributes=(), events=(), links=(), error=False):
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(BASE_NS + start * 1_000_000_000),
        "endTimeUnixNano": str(BASE_NS + end * 1_000_000_000),
        "attributes": [attr(key, value) for key, value in attributes],
        "events": list(events),
        "links": list(links),
        "status": {"code": 2 if error else 1},
    }
    if parent:
        span["parentSpanId"] = parent
    return span


def agent(trace_id, span_id, name, **kwargs):
    attributes = [("gen_ai.operation.name", "invoke_agent"), ("gen_ai.agent.name", name), *kwargs.pop("attributes", ())]
    return otel_span(trace_id, span_id, f"invoke_agent {name}", attributes=attributes, **kwargs)


def llm(trace_id, span_id, parent, cost, start=0):
    return otel_span(
        trace_id,
        span_id,
        "chat gpt-4.1",
        parent=parent,
        start=start,
        end=start + 1,
        attributes=[
            ("gen_ai.operation.name", "chat"),
            ("gen_ai.provider.name", "openai"),
            ("gen_ai.request.model", "gpt-4.1"),
            ("gen_ai.usage.input_tokens", 1000),
            ("gen_ai.usage.output_tokens", 100),
            ("agentmesh.cost_usd", cost),
        ],
    )


def tool(trace_id, span_id, parent, name="search", start=0, error=False):
    return otel_span(
        trace_id, span_id, f"execute_tool {name}", parent=parent, start=start, end=start + 1, error=error,
        attributes=[("gen_ai.operation.name", "execute_tool"), ("gen_ai.tool.name", name)],
    )


def payload(spans, swarm_id=None, service="research-swarm"):
    resource = [attr("service.name", service), attr("deployment.environment.name", "production")]
    if swarm_id:
        resource += [attr("agentmesh.swarm.id", swarm_id), attr("agentmesh.swarm.name", "market research")]
    return {"resourceSpans": [{"resource": {"attributes": resource}, "scopeSpans": [{"scope": {"name": "test"}, "spans": spans}]}]}


ORCH = "a" * 32
PLANNER = "a1" * 8
WORKER_TRACES = [f"{index:032x}" for index in range(1, 7)]


def seed_otel_swarm(store):
    """An orchestrator trace plus six worker traces in other processes, linked to the planner span."""
    message = {"name": "agentmesh.agent.message", "timeUnixNano": str(BASE_NS + 2_000_000_000), "attributes": [attr("agentmesh.message.to", "writer"), attr("agentmesh.message.content", "draft outline")]}
    handoff = {"name": "agentmesh.agent.message", "timeUnixNano": str(BASE_NS + 30_000_000_000), "attributes": [attr("agentmesh.message.to", "reviewer"), attr("agentmesh.message.kind", "handoff")]}
    store.ingest_spans(decode_json(payload([
        otel_span(ORCH, "a0" * 8, "market research", start=0, end=40),
        agent(ORCH, PLANNER, "planner", parent="a0" * 8, start=0, end=20, events=[message]),
        llm(ORCH, "a2" * 8, PLANNER, 0.02, start=1),
        agent(ORCH, "a3" * 8, "writer", parent="a0" * 8, start=21, end=35, events=[handoff]),
        llm(ORCH, "a4" * 8, "a3" * 8, 0.05, start=22),
    ], swarm_id="swarm_market")))
    for index, trace_id in enumerate(WORKER_TRACES):
        root = f"{index + 1:02x}" * 8
        researcher = f"{index + 1:02x}ee" * 4
        spans = [
            # The worker's resource carries no swarm id: it joins through the span link.
            otel_span(trace_id, root, f"worker {index}", start=3, end=15, links=[{"traceId": ORCH, "spanId": PLANNER, "attributes": [attr("agentmesh.link.type", "spawned_by")]}]),
            agent(trace_id, researcher, "researcher", parent=root, start=3, end=14, error=index == 5),
            llm(trace_id, f"{index + 1:02x}cc" * 4, researcher, 0.01, start=4),
            tool(trace_id, f"{index + 1:02x}dd" * 4, researcher, start=5, error=index == 5),
        ]
        store.ingest_spans(decode_json(payload(spans, swarm_id=None)))


def test_otlp_links_membership_graph_and_insights(db_url):
    store = create_store(db_url)
    seed_otel_swarm(store)

    listed = store.list_swarms()
    assert [item["swarm_id"] for item in listed] == ["swarm_market"]
    row = listed[0]
    assert row["name"] == "market research" and row["traces"] == 7 and row["agents"] == 8
    assert row["failed_agents"] == 1 and row["llm_calls"] == 8 and row["tool_calls"] == 6
    assert row["cost"] == pytest.approx(0.13) and row["status"] == "succeeded"

    detail = store.get_swarm("swarm_market")
    summary = detail["summary"]
    assert summary["agents"] == 8 and summary["traces"] == 7 and summary["max_depth"] == 2
    assert summary["max_fan_out"] == 6 and summary["failed_agents"] == 1
    assert summary["messages"] == 1 and summary["handoffs"] == 1
    names = {node["key"]: node["name"] for node in detail["nodes"]}
    # Worker traces that only wrap one agent are folded into that agent.
    assert sorted(names.values()) == ["market research", "planner", "researcher", "researcher", "researcher", "researcher", "researcher", "researcher", "writer"]
    researchers = [node for node in detail["nodes"] if node["name"] == "researcher"]
    assert all(names[node["parent_key"]] == "planner" and node["depth"] == 2 for node in researchers)
    assert all(node["llm_calls"] == 1 and node["tool_calls"] == 1 and node["tools"] == ["search"] for node in researchers)
    assert {node["trace_id"] for node in researchers} == set(WORKER_TRACES)
    edges = {(names[edge["source"]], names[edge["target"]], edge["kind"]) for edge in detail["edges"]}
    assert ("planner", "researcher", "spawn") in edges and ("planner", "writer", "message") in edges
    assert ("market research", "writer", "spawn") in edges
    roles = {role["name"]: role for role in detail["roles"]["nodes"]}
    assert roles["researcher"]["instances"] == 6 and roles["researcher"]["failed"] == 1
    assert {"source": "planner", "target": "researcher", "kind": "spawn", "count": 6} in detail["roles"]["edges"]
    assert [message["content"] for message in detail["messages"] if message["kind"] == "message"] == ["draft outline"]
    kinds = {insight["kind"] for insight in detail["insights"]}
    assert {"failed_agents", "fan_out", "unknown_recipients"} <= kinds
    assert len(detail["timeline"]) == 60 and max(bucket["active"] for bucket in detail["timeline"]) >= 6
    assert store.get_swarm("swarm_missing") is None

    # Re-ingesting the same spans changes nothing.
    seed_otel_swarm(store)
    assert store.get_swarm("swarm_market")["summary"]["agents"] == 8
    store.close()


def test_spans_arriving_before_their_parents_still_build_the_graph(tmp_path):
    store = create_store(str(tmp_path / "order.db"))
    trace_id = "b" * 32
    store.ingest_spans(decode_json(payload([tool(trace_id, "b2" * 8, "b1" * 8), llm(trace_id, "b3" * 8, "b1" * 8, 0.5)], swarm_id="swarm_order")))
    store.ingest_spans(decode_json(payload([agent(trace_id, "b1" * 8, "solo", end=5)], swarm_id="swarm_order")))
    node = next(node for node in store.get_swarm("swarm_order")["nodes"] if node["name"] == "solo")
    assert node["llm_calls"] == 1 and node["tool_calls"] == 1 and node["cost"] == pytest.approx(0.5)
    store.close()


def test_sdk_swarm_across_threads_with_messages_and_links(tmp_path):
    db = str(tmp_path / "sdk.db")
    agentmesh.init(db_path=db, service_name="swarm-app", flush_interval=0.05)
    try:
        @agentmesh.observe(kind="agent")
        def researcher(topic: str) -> str:
            with agentmesh.span("chat gpt-4.1", kind="llm", attributes={"gen_ai.request.model": "gpt-4.1"}) as call:
                call.set_attribute("agentmesh.cost_usd", 0.01)
            agentmesh.send_message("writer", {"topic": topic})
            return topic

        def worker(topic, context):
            # A fresh trace (as in another process), joined to the swarm and linked to the planner.
            with agentmesh.trace(f"worker {topic}", spawned_by=context):
                researcher(topic)

        @agentmesh.observe(kind="agent")
        def planner() -> None:
            context = agentmesh.swarm_context()
            threads = [threading.Thread(target=worker, args=(topic, context)) for topic in ("gpus", "power", "cooling")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        @agentmesh.observe(kind="agent")
        def writer() -> None:
            agentmesh.handoff("reviewer", "draft ready")

        with agentmesh.swarm("datacenter research") as swarm:
            assert agentmesh.swarm_context()["swarm_id"] == swarm.id
            with agentmesh.trace("orchestrator") as root:
                planner()
                writer()
        with agentmesh.trace("unrelated") as outside:
            pass
        agentmesh.flush()
    finally:
        agentmesh.shutdown()

    store = create_store(db)
    detail = store.get_swarm(swarm.id)
    assert detail["name"] == "datacenter research" and detail["summary"]["traces"] == 4
    names = {node["key"]: node for node in detail["nodes"]}
    researchers = [node for node in detail["nodes"] if node["name"] == "researcher"]
    assert len(researchers) == 3 and all(names[node["parent_key"]]["name"] == "planner" for node in researchers)
    assert len({node["trace_id"] for node in researchers}) == 3 and root.trace_id not in {node["trace_id"] for node in researchers}
    message_edges = [edge for edge in detail["edges"] if edge["kind"] == "message"]
    assert len(message_edges) == 3 and all(names[edge["target"]]["name"] == "writer" for edge in message_edges)
    assert detail["summary"]["handoffs"] == 1 and detail["summary"]["cost"] == pytest.approx(0.03)
    assert outside.trace_id not in {trace["trace_id"] for trace in detail["traces"]}
    assert [item["swarm_id"] for item in store.list_swarms()] == [swarm.id]
    store.close()


def test_sdk_swarm_attributes_links_and_process_swarm(monkeypatch):
    exporter = InMemoryExporter()
    monkeypatch.setenv("AGENTMESH_SWARM_ID", "swarm_from_env")
    monkeypatch.setenv("AGENTMESH_SWARM_NAME", "batch")
    agentmesh.init(exporter=exporter)
    try:
        with agentmesh.trace("env worker"):
            with agentmesh.swarm("inner", swarm_id="swarm_inner"):
                with agentmesh.span("nested") as nested:
                    agentmesh.send_message("peer", "secret plan", to_context={"trace_id": "c" * 32, "span_id": "c" * 16})
        with agentmesh.trace("spawned", spawned_by={"swarm_id": "swarm_parent", "trace_id": "d" * 32, "span_id": "d" * 16}) as spawned:
            pass
        agentmesh.flush()
    finally:
        agentmesh.shutdown()
    spans = {span.name: span for span in exporter.spans}
    assert spans["env worker"].attributes["agentmesh.swarm.id"] == "swarm_from_env"
    assert spans["env worker"].attributes["agentmesh.swarm.name"] == "batch"
    assert spans["nested"].attributes["agentmesh.swarm.id"] == "swarm_inner"
    message = spans["nested"].events[0]
    assert message["name"] == "agentmesh.agent.message" and message["attributes"]["agentmesh.message.to_span_id"] == "c" * 16
    assert spans["spawned"].attributes["agentmesh.swarm.id"] == "swarm_parent" and spawned.parent_span_id is None
    assert spans["spawned"].links == [{"trace_id": "d" * 32, "span_id": "d" * 16, "attributes": {"agentmesh.link.type": "spawned_by"}}]
    encoded = encode_json([spans["spawned"]])["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert decode_json({"resourceSpans": [{"resource": {}, "scopeSpans": [{"spans": [encoded]}]}]})[0].links == spans["spawned"].links
    assert nested.trace_id == spans["env worker"].trace_id


def test_message_content_respects_capture(tmp_path, monkeypatch):
    store = create_store(str(tmp_path / "private.db"))
    trace_id = "e" * 32
    event = {"name": "agentmesh.agent.message", "timeUnixNano": str(BASE_NS), "attributes": [attr("agentmesh.message.to", "b"), attr("agentmesh.message.content", "customer SSN 123")]}
    store.ingest_spans(decode_json(payload([agent(trace_id, "e1" * 8, "a", events=[event])], swarm_id="swarm_private")), capture_content=False)
    assert store.get_swarm("swarm_private")["messages"][0]["content"] is None
    store.close()


def test_protobuf_links_decode():
    pytest.importorskip("opentelemetry.proto")
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
    from opentelemetry.proto.trace.v1.trace_pb2 import Span

    from agentmesh.otlp import decode_protobuf

    request = ExportTraceServiceRequest()
    scope = request.resource_spans.add().scope_spans.add()
    span = scope.spans.add(trace_id=bytes.fromhex("f" * 32), span_id=bytes.fromhex("f1" * 8), name="worker", start_time_unix_nano=BASE_NS, end_time_unix_nano=BASE_NS + 1)
    span.links.append(Span.Link(trace_id=bytes.fromhex("a" * 32), span_id=bytes.fromhex("a1" * 8), attributes=[KeyValue(key="agentmesh.link.type", value=AnyValue(string_value="spawned_by"))]))
    decoded = decode_protobuf(request.SerializeToString())
    assert decoded[0].links == [{"trace_id": "a" * 32, "span_id": "a1" * 8, "attributes": {"agentmesh.link.type": "spawned_by"}}]


def test_analysis_depth_and_cost_insights():
    trace = {"trace_id": "t", "workflow_name": "deep", "status": "running"}
    spans = [{"span_id": "root", "trace_id": "t", "parent_span_id": None, "event_type": "agent.invoke", "agent_name": "a0", "status": "succeeded", "started_at": "2026-01-01T00:00:00+00:00"}]
    parent = "root"
    for depth in range(1, 6):
        spans.append({"span_id": f"s{depth}", "trace_id": "t", "parent_span_id": parent, "event_type": "agent.invoke", "agent_name": f"a{depth}", "status": "running" if depth == 5 else "succeeded", "started_at": f"2026-01-01T00:00:0{depth}+00:00"})
        parent = f"s{depth}"
    spans.append({"span_id": "m", "trace_id": "t", "parent_span_id": "s5", "event_type": "model.chat", "estimated_cost": 2.0, "total_tokens": 10, "status": "succeeded", "started_at": "2026-01-01T00:00:09+00:00"})
    report = analyze_swarm([trace], spans, [], [])
    assert report["summary"]["max_depth"] == 5 and report["summary"]["status"] == "running" and report["summary"]["running_agents"] == 1
    kinds = {insight["kind"] for insight in report["insights"]}
    assert {"depth", "cost_hotspot"} <= kinds
    assert analyze_swarm([], [], [], [])["summary"]["agents"] == 0


def test_swarm_halt_stops_every_agent_in_the_swarm(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTMESH_GUARDRAILS_REFRESH_SECONDS", "0")
    db = str(tmp_path / "halt.db")
    agentmesh.init(db_path=db, service_name="swarm-app", flush_interval=0.05)
    store = create_store(db)
    try:
        @agentmesh.observe(kind="agent")
        def worker() -> str:
            return "ok"

        with agentmesh.swarm("runaway", swarm_id="swarm_runaway"):
            with agentmesh.trace("before"):
                assert worker() == "ok"
            store.create_halt({"scope": "swarm", "value": "swarm_runaway", "reason": "fan-out spike"})
            with pytest.raises(AgentHalted, match="fan-out spike"), agentmesh.trace("after"):
                worker()
        with agentmesh.trace("another swarm"):
            assert worker() == "ok"
    finally:
        agentmesh.shutdown()
        store.close()


def test_swarm_api_cli_and_mcp(db_url):
    store = create_store(db_url)
    seed_otel_swarm(store)
    client = TestClient(create_app(db_url))
    listed = client.get("/api/swarms").json()
    assert [item["swarm_id"] for item in listed] == ["swarm_market"]
    assert client.get("/api/swarms", params={"q": "market"}).json()[0]["agents"] == 8
    assert client.get("/api/swarms", params={"q": "nothing"}).json() == []
    assert client.get("/api/swarms", params={"hours": 1}).json() == []  # the fixture's spans are old
    detail = client.get("/api/swarms/swarm_market").json()
    assert detail["summary"]["max_fan_out"] == 6 and detail["roles"]["nodes"]
    assert client.get("/api/swarms/swarm_missing").status_code == 404
    assert client.get(f"/api/traces/{WORKER_TRACES[0]}").json()["swarms"] == [{"swarm_id": "swarm_market", "name": "market research"}]
    halt = client.post("/api/halts", json={"scope": "swarm", "value": "swarm_market"})
    assert halt.status_code == 201 and halt.json()["scope"] == "swarm"

    server = AgentMeshMCPServer(store)
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_swarm", "arguments": {"swarm_id": "swarm_market", "include_agents": True}}})
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["summary"]["agents"] == 8 and len(result["agents"]) == 9
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_swarms", "arguments": {}}})
    assert json.loads(response["result"]["content"][0]["text"])[0]["swarm_id"] == "swarm_market"
    store.close()


def test_swarm_cli(tmp_path):
    db = tmp_path / "cli.db"
    store = create_store(str(db))
    seed_otel_swarm(store)
    store.close()
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "agentmesh.cli", "--db", str(db), *args], capture_output=True, text=True, env=env, check=False)

    listed = cli("swarms", "list")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)[0]["name"] == "market research"
    shown = json.loads(cli("swarms", "show", "swarm_market").stdout)
    assert set(shown) == {"swarm_id", "name", "service_name", "summary", "roles", "insights"}
    assert "nodes" in json.loads(cli("swarms", "show", "swarm_market", "--full").stdout)
    assert cli("swarms", "show", "nope").returncode != 0
    halted = cli("halt", "create", "--swarm", "swarm_market")
    assert halted.returncode == 0 and json.loads(halted.stdout)["scope"] == "swarm"


def test_swarm_status_follows_the_traces_that_started_it():
    from collections import Counter

    from agentmesh.swarms import _swarm_status

    assert _swarm_status(Counter({"succeeded": 6, "failed": 1}), Counter({"succeeded": 1})) == "succeeded"
    assert _swarm_status(Counter({"succeeded": 6, "failed": 1}), Counter({"failed": 1})) == "failed"
    assert _swarm_status(Counter({"running": 1, "succeeded": 2}), Counter({"succeeded": 1})) == "running"
    assert _swarm_status(Counter({"failed": 1}), Counter()) == "failed"
    assert _swarm_status(Counter()) == "unknown"


async def test_one_swarm_object_can_be_entered_from_many_threads_and_tasks():
    """Workers commonly share the Swarm object; entering it per thread or task must not break."""
    exporter = InMemoryExporter()
    agentmesh.init(exporter=exporter, service_name="fleet")
    try:
        swarm = agentmesh.swarm("fleet", swarm_id="swarm_fleet")

        def in_thread(index):
            with swarm, agentmesh.trace(f"thread {index}"):
                pass

        threads = [threading.Thread(target=in_thread, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        async def in_task(index):
            async with swarm:
                async with agentmesh.trace(f"task {index}"):
                    await asyncio.sleep(0.01)

        await asyncio.gather(*(in_task(index) for index in range(4)))
        agentmesh.flush()
        assert {span.attributes.get("agentmesh.swarm.id") for span in exporter.spans} == {"swarm_fleet"}
        assert len(exporter.spans) == 8
        assert agentmesh.swarm_context()["swarm_id"] is None  # left cleanly in every context
    finally:
        agentmesh.shutdown()


def test_long_message_content_is_truncated(tmp_path):
    exporter = InMemoryExporter()
    agentmesh.init(exporter=exporter)
    try:
        with agentmesh.trace("long"):
            agentmesh.send_message("writer", "x" * 5_000)
        agentmesh.flush()
        content = exporter.spans[0].events[0]["attributes"]["agentmesh.message.content"]
        assert len(content) == 2_001 and content.endswith("…")
    finally:
        agentmesh.shutdown()


def test_pruning_traces_removes_their_swarms_links_and_messages(tmp_path):
    store = create_store(str(tmp_path / "prune.db"))
    seed_otel_swarm(store)
    assert store.list_swarms() and store.get_swarm("swarm_market")["summary"]["agents"] == 8
    pruned = store.prune_traces("2099-01-01T00:00:00+00:00")
    assert pruned["traces"] == 7 and pruned["deleted_rows"]["swarm_traces"] == 7
    assert pruned["deleted_rows"]["span_links"] == 6 and pruned["deleted_rows"]["agent_messages_log"] == 2
    assert store.list_swarms() == [] and store.get_swarm("swarm_market") is None
    store.close()
