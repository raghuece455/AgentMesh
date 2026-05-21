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
    RetrievalEngine,
    SQLiteStore,
    SQLiteVectorStore,
    Task,
    ToolCallRequest,
    ToolRegistry,
    Workflow,
    tool,
)
from agentmesh.dashboard import create_app
from agentmesh.demo import seed_demo_data
from agentmesh.memory import SQLiteMemoryStore
from agentmesh.pricing import estimate_model_cost
from agentmesh.otel_export import export_otel_json
from agentmesh.types import REDACTED, redact_secrets
from agentmesh.validation import validate_traces


async def _run_context_rich_workflow(store: SQLiteStore):
    retriever = RetrievalEngine(SQLiteVectorStore(store), top_k=1)
    await retriever.ingest({"agentmesh.md": "AgentMesh traces model calls, tools, approvals, memory, and RAG retrievals."})

    @tool(
        "governed_context",
        "Read approved context, retrieve a document, and write memory",
        permission=PermissionLevel.SENSITIVE,
        requires_approval=True,
    )
    async def governed_context(arguments, context):
        results = await retriever.retrieve(str(arguments["query"]), context)
        version = context.store.save_memory(context.agent_name, "workflow", "last_query", arguments["query"], context.trace_id)
        context.recorder.event(
            context.trace_id,
            "memory.write",
            context.agent_name,
            {
                "memory_type": "workflow state",
                "operation": "write",
                "key": "last_query",
                "value": arguments["query"],
                "version": version,
            },
            parent_span_id=context.parent_span_id,
        )
        return {"documents": [result.to_json() for result in results], "memory_version": version}

    async def approve(_definition, _arguments, _context):
        return True

    agent = Agent(
        "observer",
        "Observer",
        "Use approved context and answer.",
        MockModelProvider(["context captured"]),
        ToolRegistry([governed_context]),
        {PermissionLevel.READ, PermissionLevel.SENSITIVE},
    )
    workflow = Workflow("hardening-context-rich", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "observer",
        Task("Inspect traceability", tool_calls=[ToolCallRequest("governed_context", {"query": "trace approvals memory"})]),
    )
    return await workflow.run({"environment": "local"}, approval_callback=approve)


def test_real_runtime_records_observability_and_validates(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    result = asyncio.run(_run_context_rich_workflow(store))

    assert store.list_observable_traces(10, {"is_demo": False})[0]["trace_id"] == result.trace_id
    assert store.list_model_calls(result.trace_id)
    assert store.list_tool_calls(result.trace_id)
    assert store.list_rag_retrievals(result.trace_id)
    assert store.list_memory_operations(result.trace_id)
    assert store.list_approvals(limit=10)[0]["status"] == "approved"
    assert store.cost_summary()["cost_status_counts"]["local/free"] >= 1
    assert validate_traces(store)["status"] == "ok"


def test_demo_and_real_runs_are_filterable_through_api(tmp_path):
    db_path = tmp_path / "agentmesh.db"
    seed_demo_data(db_path)
    store = SQLiteStore(db_path)
    asyncio.run(_run_context_rich_workflow(store))
    client = TestClient(create_app(db_path))

    demo = client.get("/api/traces", params={"is_demo": "true"}).json()
    real = client.get("/api/traces", params={"is_demo": "false"}).json()

    assert demo
    assert real
    assert all(item["is_demo"] is True for item in demo)
    assert all(item["is_demo"] is False for item in real)


def test_secret_redaction_applies_to_persistence_and_export(tmp_path):
    secret = "sk-test_abcdefghijklmnopqrstuvwxyz"
    store = SQLiteStore(tmp_path / "agentmesh.db")
    workflow = Workflow("secret-redaction", store=store)
    workflow.add_agent(Agent("redactor", "Redactor", "Never expose secrets.", MockModelProvider(["redacted"])))
    workflow.add_step("redactor", "handle secret")

    result = asyncio.run(workflow.run({"api_key": secret, "authorization": f"Bearer {secret}", "environment": "local"}))
    exported = store.export_trace(result.trace_id)
    otel_exported = export_otel_json(exported)
    rendered = json.dumps(exported)
    otel_rendered = json.dumps(otel_exported)

    assert secret not in rendered
    assert secret not in otel_rendered
    assert REDACTED in rendered
    assert REDACTED in otel_rendered
    assert any(log["action"] == "secret.redacted" for log in store.list_audit_logs(result.trace_id))
    assert redact_secrets({"database_url": "postgres://user:pass@example.com/db"})["database_url"] == REDACTED


def test_otel_export_maps_failed_spans_to_error_status(tmp_path):
    db_path = tmp_path / "agentmesh.db"
    seed = seed_demo_data(db_path)
    store = SQLiteStore(db_path)
    failed_trace_id = next(item["trace_id"] for item in store.list_observable_traces(20) if item["status"] == "failed")

    payload = export_otel_json(store.export_trace(failed_trace_id))
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]

    assert seed["trace_ids"]
    assert any(span["status"]["code"] == "STATUS_CODE_ERROR" for span in spans)


def test_pricing_statuses_are_explicit():
    openai = estimate_model_cost("openai-compatible", "gpt-4.1-mini", 1000, 500)
    ollama = estimate_model_cost("ollama", "llama3.1", 1000, 500)
    unknown = estimate_model_cost("unknown-provider", "unknown-model", 1000, 500)

    assert openai.status == "estimated"
    assert openai.cost_usd > 0
    assert ollama.status == "local/free"
    assert ollama.cost_usd == 0
    assert unknown.status == "unknown"


def test_cli_trace_validation_command(tmp_path):
    db_path = tmp_path / "agentmesh.db"
    store = SQLiteStore(db_path)
    asyncio.run(_run_context_rich_workflow(store))
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}

    completed = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db_path), "traces", "validate"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert json.loads(completed.stdout)["status"] == "ok"
