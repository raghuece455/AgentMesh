import asyncio
import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient

from agentmesh import (
    Agent,
    MockModelProvider,
    PermissionLevel,
    SQLiteMemoryStore,
    SQLiteStore,
    Task,
    ToolCallRequest,
    ToolRegistry,
    Workflow,
    tool,
)
from agentmesh.dashboard import create_app
from agentmesh.demo import seed_demo_data


async def _run_observed_workflow(store: SQLiteStore):
    @tool("release_gate", "Approve release", permission=PermissionLevel.SENSITIVE, requires_approval=True)
    def release_gate(arguments, context):
        return {"approved": arguments["ticket"] == "AM-1"}

    async def approve(_definition, _arguments, _context):
        return True

    provider = MockModelProvider(["release noted"])
    agent = Agent(
        "operator",
        "Operator",
        "Run the gated action.",
        provider,
        ToolRegistry([release_gate]),
        {PermissionLevel.READ, PermissionLevel.SENSITIVE},
    )
    workflow = Workflow("production-surface", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "operator",
        Task(
            "ship",
            tool_calls=[ToolCallRequest("release_gate", {"ticket": "AM-1"})],
            metadata={"idempotent": True},
        ),
    )
    result = await workflow.run(approval_callback=approve)
    SQLiteMemoryStore(store, workflow.recorder).put("operator", "profile", "last_release", {"ticket": "AM-1"}, result.trace_id)
    return result


def test_production_dashboard_endpoints(tmp_path):
    db_path = tmp_path / "agentmesh.db"
    store = SQLiteStore(db_path)
    result = asyncio.run(_run_observed_workflow(store))
    client = TestClient(create_app(db_path))

    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json()["status"] == "ready"
    assert client.get(f"/api/traces/{result.trace_id}/prompts").json()
    assert client.get("/api/memory").json()[0]["key"] == "last_release"
    assert client.get("/api/approvals").json()[0]["status"] == "approved"
    assert client.get(f"/api/traces/{result.trace_id}/diagnose").json()["found"] is True

    exported = client.get(f"/api/traces/{result.trace_id}/export").json()
    otel_exported = client.get(f"/api/traces/{result.trace_id}/export", params={"format": "otel-json"}).json()
    imported = client.post("/api/traces/import", json={"payload": exported}).json()
    compared = client.get(f"/api/compare?left={result.trace_id}&right={imported['trace_id']}").json()

    assert exported["found"] is True
    assert otel_exported["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert client.get(f"/api/traces/{result.trace_id}/export/otel-json").json() == otel_exported
    assert imported["imported"] is True
    assert compared["left_event_count"] == compared["right_event_count"]


def test_api_key_auth_mode_protects_sensitive_endpoints(tmp_path, monkeypatch):
    db_path = tmp_path / "agentmesh.db"
    store = SQLiteStore(db_path)
    result = asyncio.run(_run_observed_workflow(store))
    monkeypatch.setenv("AGENTMESH_AUTH_MODE", "api_key")
    monkeypatch.setenv("AGENTMESH_API_KEY", "test-api-key")
    client = TestClient(create_app(db_path))

    assert client.get("/api/overview").status_code == 401
    assert client.get(f"/api/traces/{result.trace_id}/export").status_code == 401
    authorized = client.get(
        f"/api/traces/{result.trace_id}/export",
        headers={"Authorization": "Bearer test-api-key"},
    )

    assert authorized.status_code == 200
    assert authorized.json()["found"] is True


def test_otel_export_maps_span_hierarchy_and_failed_status(tmp_path):
    db_path = tmp_path / "agentmesh.db"
    store = SQLiteStore(db_path)
    result = asyncio.run(_run_observed_workflow(store))
    client = TestClient(create_app(db_path))

    payload = client.get(f"/api/traces/{result.trace_id}/export", params={"format": "otel-json"}).json()
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    span_by_name = {span["name"]: span for span in spans}

    assert spans
    assert any(span["parentSpanId"] for span in spans)
    assert any(event["name"] == "model.call" for span in spans for event in span["events"])
    assert any(event["name"] == "tool.call" for span in spans for event in span["events"])
    assert span_by_name["workflow.started"]["status"]["code"] in {"STATUS_CODE_OK", "STATUS_CODE_UNSET"}


def test_observability_demo_endpoints_are_connected(tmp_path):
    from agentmesh.demo import seed_demo_data

    db_path = tmp_path / "agentmesh.db"
    seed = seed_demo_data(db_path)
    client = TestClient(create_app(db_path))
    trace_id = seed["trace_ids"][0]

    endpoints = [
        "/api/overview",
        "/api/overview/timeseries",
        "/api/health",
        "/api/workflows",
        "/api/agents",
        "/api/models",
        "/api/providers/health",
        "/api/model-calls",
        "/api/costs/summary",
        "/api/costs/by-workflow",
        "/api/costs/by-agent",
        "/api/costs/by-model",
        "/api/costs/by-provider",
        "/api/costs/by-failed-run",
        "/api/tool-calls",
        "/api/memory/operations",
        "/api/memory/records",
        "/api/rag/retrievals",
        "/api/prompts",
        "/api/replay/checkpoints",
        "/api/evaluations",
        "/api/evaluations/summary",
        "/api/approvals",
        "/api/audit-logs",
        f"/api/traces/{trace_id}/spans",
        f"/api/traces/{trace_id}/events",
    ]

    for endpoint in endpoints:
        assert client.get(endpoint).status_code == 200, endpoint

    detail = client.get(f"/api/traces/{trace_id}").json()
    assert detail["spans"]
    assert detail["model_calls"]


def test_dashboard_list_endpoints_support_pagination_and_filters(tmp_path):
    db_path = tmp_path / "agentmesh.db"
    seed_demo_data(db_path)
    client = TestClient(create_app(db_path))

    openai_calls = client.get("/api/model-calls", params={"provider": "openai-compatible", "limit": 2, "offset": 0}).json()
    tool_calls = client.get("/api/tool-calls", params={"status": "succeeded", "limit": 5}).json()
    memory_ops = client.get("/api/memory/operations", params={"operation": "write", "limit": 5}).json()
    approvals = client.get("/api/approvals", params={"status": "approved", "limit": 5, "offset": 0}).json()
    audit_logs = client.get("/api/audit-logs", params={"limit": 3, "offset": 0}).json()

    assert openai_calls
    assert all(call["provider"] == "openai-compatible" for call in openai_calls)
    assert tool_calls
    assert all(call["status"] == "succeeded" for call in tool_calls)
    assert memory_ops
    assert all(operation["operation"] == "write" for operation in memory_ops)
    assert approvals
    assert all(approval["status"] == "approved" for approval in approvals)
    assert len(audit_logs) <= 3


def test_cli_export_import_doctor_version(tmp_path):
    db_path = tmp_path / "agentmesh.db"
    store = SQLiteStore(db_path)
    result = asyncio.run(_run_observed_workflow(store))
    export_path = tmp_path / "trace.json"
    otel_path = tmp_path / "trace.otel.json"
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}

    export = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db_path), "export", result.trace_id, "--out", str(export_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    imported = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db_path), "import", str(export_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    otel_export = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentmesh.cli",
            "--db",
            str(db_path),
            "traces",
            "export",
            result.trace_id,
            "--format",
            "otel-json",
            "--out",
            str(otel_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    doctor = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db_path), "doctor"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    version = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "version"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert export_path.exists()
    assert otel_path.exists()
    assert str(export_path) in export.stdout
    assert str(otel_path) in otel_export.stdout
    assert json.loads(otel_path.read_text(encoding="utf-8"))["resourceSpans"]
    assert json.loads(imported.stdout)["imported"] is True
    assert json.loads(doctor.stdout)["database_ok"] is True
    assert version.stdout.strip()


def test_cli_validate_json_and_replay_modes(tmp_path):
    db_path = tmp_path / "agentmesh.db"
    store = SQLiteStore(db_path)
    result = asyncio.run(_run_observed_workflow(store))
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}

    validation = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db_path), "validate", "traces", "--json"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    replay = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db_path), "replay", result.trace_id, "--mode", "deterministic"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    live_without_flag = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db_path), "replay", result.trace_id, "--mode", "live"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert json.loads(validation.stdout)["total_traces_checked"] == 1
    assert json.loads(replay.stdout)["mode"] == "deterministic"
    assert live_without_flag.returncode != 0
    assert "--allow-side-effects" in live_without_flag.stderr
