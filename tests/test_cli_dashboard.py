from fastapi.testclient import TestClient

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow
from agentmesh.dashboard import create_app
from agentmesh.tracing import TraceReplayer


def test_dashboard_api_returns_traces(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    workflow = Workflow("dashboard-api-test", store=store)
    workflow.add_agent(Agent("agent", "Agent", "Return ok.", MockModelProvider(["ok"])))
    workflow.add_step("agent", "run")

    import asyncio

    result = asyncio.run(workflow.run())
    client = TestClient(create_app(tmp_path / "agentmesh.db"))

    traces = client.get("/api/traces").json()
    detail = client.get(f"/api/traces/{result.trace_id}").json()
    costs = client.get(f"/api/traces/{result.trace_id}/costs").json()
    replay = client.get(f"/api/traces/{result.trace_id}/replay").json()
    checkpoints = client.get(f"/api/traces/{result.trace_id}/checkpoints").json()

    assert traces[0]["trace_id"] == result.trace_id
    assert detail["trace"]["status"] == "succeeded"
    assert detail["events"]
    assert costs["model_calls"] == 1
    assert replay["found"] is True
    assert checkpoints


def test_trace_replayer_returns_recorded_io(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    workflow = Workflow("replay-test", store=store)
    workflow.add_agent(Agent("agent", "Agent", "Return ok.", MockModelProvider(["ok"])))
    workflow.add_step("agent", "run")

    import asyncio

    result = asyncio.run(workflow.run())
    replay = TraceReplayer(store).replay(result.trace_id)

    assert replay["found"] is True
    assert replay["mode"] == "deterministic"
    assert replay["side_effects_disabled"] is True
    assert replay["events"]
