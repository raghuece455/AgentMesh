from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from pydantic import BaseModel

from agentmesh.errors import AgentMeshError
from agentmesh.services import ApprovalService, BackgroundJobService, MemoryService, TraceService
from agentmesh.settings import AgentMeshSettings
from agentmesh.stores import create_store
from agentmesh.telemetry import DEFAULT_METRICS
from agentmesh.types import safe_json


class ResolveApprovalRequest(BaseModel):
    approved: bool
    reason: str | None = None


DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AgentMesh Dashboard</title>
  <style>
    :root { color-scheme: light dark; font-family: Inter, system-ui, sans-serif; }
    body { margin: 0; background: #0f172a; color: #e5e7eb; }
    header { padding: 20px 28px; border-bottom: 1px solid #334155; background: #111827; }
    main { display: grid; grid-template-columns: 340px 1fr; min-height: calc(100vh - 76px); }
    aside { border-right: 1px solid #334155; padding: 16px; overflow: auto; }
    section { padding: 18px 22px; overflow: auto; }
    button { width: 100%; text-align: left; border: 1px solid #334155; background: #1f2937; color: #e5e7eb; padding: 10px; border-radius: 8px; margin-bottom: 8px; cursor: pointer; }
    button:hover { background: #273449; }
    .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #164e63; color: #cffafe; font-size: 12px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 12px; margin-bottom: 18px; }
    .metric { border: 1px solid #334155; border-radius: 8px; padding: 12px; background: #111827; }
    .metric strong { display: block; font-size: 22px; margin-top: 6px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #020617; border: 1px solid #334155; border-radius: 8px; padding: 12px; }
    .event { border-left: 3px solid #38bdf8; padding: 10px 12px; margin-bottom: 10px; background: #111827; }
    .muted { color: #94a3b8; font-size: 13px; }
  </style>
</head>
<body>
  <header>
    <h1>AgentMesh Dashboard</h1>
    <div class="muted">Local workflow traces, task timelines, model usage, tools, retries, and errors.</div>
  </header>
  <main>
    <aside>
      <h2>Traces</h2>
      <div id="traces"></div>
    </aside>
    <section>
      <div class="grid" id="metrics"></div>
      <h2 id="title">Select a trace</h2>
      <div id="detail"></div>
    </section>
  </main>
  <script>
    async function loadTraces() {
      const response = await fetch('/api/traces');
      const traces = await response.json();
      const list = document.getElementById('traces');
      list.innerHTML = '';
      traces.forEach(trace => {
        const item = document.createElement('button');
        item.innerHTML = `<strong>${trace.name}</strong><br><span class="muted">${trace.trace_id}</span><br><span class="pill">${trace.status}</span>`;
        item.onclick = () => loadTrace(trace.trace_id);
        list.appendChild(item);
      });
      renderMetrics(traces);
    }
    function renderMetrics(traces) {
      const counts = traces.reduce((acc, trace) => { acc[trace.status] = (acc[trace.status] || 0) + 1; return acc; }, {});
      document.getElementById('metrics').innerHTML = [
        ['Total traces', traces.length],
        ['Running', counts.running || 0],
        ['Succeeded', counts.succeeded || 0],
        ['Failed', counts.failed || 0],
      ].map(([label, value]) => `<div class="metric">${label}<strong>${value}</strong></div>`).join('');
    }
    async function loadTrace(id) {
      const response = await fetch(`/api/traces/${id}`);
      const data = await response.json();
      document.getElementById('title').textContent = `${data.trace.name} - ${data.trace.status}`;
      document.getElementById('detail').innerHTML = `
        <h3>Task Graph</h3>
        <pre>${JSON.stringify(data.task_graph, null, 2)}</pre>
        <h3>Execution Timeline</h3>
        ${data.events.map(event => `<div class="event"><strong>${event.event_type}</strong> <span class="muted">${event.timestamp} ${event.actor}</span><pre>${JSON.stringify(event.payload, null, 2)}</pre></div>`).join('')}
      `;
    }
    loadTraces();
  </script>
</body>
</html>
"""


def create_app(db_path: str | Path | None = None):
    from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles

    settings = AgentMeshSettings.from_env()
    resolved_db = str(db_path or settings.db_url)
    app = FastAPI(
        title="AgentMesh API",
        version="0.3.0-alpha",
        description="Observable multi-agent runtime APIs for traces, replay, memory, approvals, metrics, and dashboard data.",
    )
    store = create_store(resolved_db)
    trace_service = TraceService(store)
    memory_service = MemoryService(store)
    approval_service = ApprovalService(store)
    job_service = BackgroundJobService()
    dashboard_dist = Path(__file__).resolve().parents[2] / "dashboard" / "dist"
    if dashboard_dist.exists():
        app.mount("/assets", StaticFiles(directory=dashboard_dist / "assets"), name="assets")

    async def require_auth(authorization: str | None = Header(default=None)) -> None:
        auth_mode = os.getenv("AGENTMESH_AUTH_MODE", settings.auth_mode).lower()
        if auth_mode in {"", "none", "off", "disabled"}:
            return
        if auth_mode != "api_key":
            raise HTTPException(status_code=500, detail={"error": "auth_misconfigured", "message": f"Unsupported auth mode: {auth_mode}"})
        expected = os.getenv("AGENTMESH_API_KEY") or settings.api_key
        if not expected:
            raise HTTPException(status_code=500, detail={"error": "auth_misconfigured", "message": "AGENTMESH_API_KEY is required when AGENTMESH_AUTH_MODE=api_key"})
        if authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Invalid AgentMesh API key"})

    @app.exception_handler(AgentMeshError)
    async def agentmesh_error_handler(_request, exc: AgentMeshError):
        return Response(
            json.dumps({"error": exc.kind.value, "message": exc.message, "details": exc.details}),
            status_code=400,
            media_type="application/json",
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(_request, exc: Exception):
        return Response(
            json.dumps({"error": "internal_error", "message": str(exc) or type(exc).__name__}),
            status_code=500,
            media_type="application/json",
        )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        index_file = dashboard_dist / "index.html"
        if index_file.exists():
            return index_file.read_text(encoding="utf-8")
        return DASHBOARD_HTML

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {"status": "ok", "database": resolved_db, "traces": len(store.list_traces(1))}

    @app.get("/readyz")
    def readyz() -> dict[str, object]:
        store.list_traces(1)
        return {"status": "ready"}

    @app.get("/api/health", dependencies=[Depends(require_auth)])
    def api_health() -> dict[str, object]:
        return {"status": "ok", "database": resolved_db, "providers": trace_service.provider_health()}

    @app.get("/api/overview", dependencies=[Depends(require_auth)])
    def overview() -> dict[str, object]:
        return trace_service.overview()

    @app.get("/api/overview/timeseries", dependencies=[Depends(require_auth)])
    def overview_timeseries() -> dict[str, object]:
        return trace_service.overview_timeseries()

    @app.get("/api/traces", dependencies=[Depends(require_auth)])
    def traces(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        q: str | None = None,
        workflow: str | None = None,
        agent: str | None = None,
        task: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        tool: str | None = None,
        status: str | None = None,
        error_type: str | None = None,
        min_cost: float | None = None,
        max_cost: float | None = None,
        min_latency: float | None = None,
        max_latency: float | None = None,
        start: str | None = None,
        end: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        environment: str | None = None,
        is_demo: bool | None = None,
    ) -> list[dict[str, object]]:
        filters = {
            "q": q,
            "workflow": workflow,
            "agent": agent,
            "task": task,
            "model": model,
            "provider": provider,
            "tool": tool,
            "status": status,
            "error_type": error_type,
            "min_cost": min_cost,
            "max_cost": max_cost,
            "min_latency": min_latency,
            "max_latency": max_latency,
            "start": start,
            "end": end,
            "started_after": started_after,
            "started_before": started_before,
            "environment": environment,
            "is_demo": is_demo,
        }
        return trace_service.list_traces(limit, {key: value for key, value in filters.items() if value is not None}, offset)

    @app.get("/api/compare", dependencies=[Depends(require_auth)])
    def compare_runs(left: str = Query(...), right: str = Query(...)) -> dict[str, object]:
        return trace_service.compare(left, right)

    @app.get("/api/traces/{trace_id}", dependencies=[Depends(require_auth)])
    def trace_detail(trace_id: str) -> dict[str, object]:
        return trace_service.get_trace_detail(trace_id)

    @app.get("/api/traces/{trace_id}/spans", dependencies=[Depends(require_auth)])
    def trace_spans(trace_id: str) -> list[dict[str, object]]:
        return trace_service.spans(trace_id)

    @app.get("/api/traces/{trace_id}/events", dependencies=[Depends(require_auth)])
    def trace_events(trace_id: str) -> list[dict[str, object]]:
        return trace_service.events(trace_id)

    @app.get("/api/traces/{trace_id}/replay", dependencies=[Depends(require_auth)])
    def replay(trace_id: str) -> dict[str, object]:
        return trace_service.replay(trace_id)

    @app.get("/api/traces/{trace_id}/costs", dependencies=[Depends(require_auth)])
    def trace_costs(trace_id: str) -> dict[str, object]:
        return trace_service.costs(trace_id)

    @app.get("/api/traces/{trace_id}/checkpoints", dependencies=[Depends(require_auth)])
    def checkpoints(trace_id: str) -> list[dict[str, object]]:
        return trace_service.checkpoints(trace_id)

    @app.get("/api/checkpoints/{checkpoint_id}", dependencies=[Depends(require_auth)])
    def checkpoint(checkpoint_id: str) -> dict[str, object] | None:
        return trace_service.checkpoint(checkpoint_id)

    @app.get("/api/traces/{trace_id}/prompts", dependencies=[Depends(require_auth)])
    def prompt_versions(trace_id: str) -> list[dict[str, object]]:
        return trace_service.prompt_versions(trace_id)

    @app.get("/api/traces/{trace_id}/diagnose", dependencies=[Depends(require_auth)])
    def diagnose(trace_id: str) -> dict[str, object]:
        return trace_service.diagnose(trace_id)

    @app.get("/api/traces/{trace_id}/export", dependencies=[Depends(require_auth)])
    def export_trace(trace_id: str, format: str = Query("json", pattern="^(json|otel-json)$")) -> dict[str, object]:
        if format == "otel-json":
            return trace_service.export_trace_otel_json(trace_id)
        return trace_service.export_trace(trace_id)

    @app.get("/api/traces/{trace_id}/export/otel-json", dependencies=[Depends(require_auth)])
    def export_trace_otel_json(trace_id: str) -> dict[str, object]:
        return trace_service.export_trace_otel_json(trace_id)

    @app.post("/api/traces/import", dependencies=[Depends(require_auth)])
    def import_trace(payload: dict[str, object] = Body(...)) -> dict[str, object]:
        trace_payload = payload.get("payload", payload)
        if not isinstance(trace_payload, dict):
            raise HTTPException(status_code=422, detail={"error": "invalid_trace_export"})
        safe_payload = safe_json(trace_payload)
        if not isinstance(safe_payload, dict):
            raise HTTPException(status_code=422, detail={"error": "invalid_trace_export"})
        return trace_service.import_trace(safe_payload)

    @app.get("/api/workflows/active", dependencies=[Depends(require_auth)])
    def active_workflows() -> list[dict[str, object]]:
        return [trace.to_json() for trace in store.list_traces(100) if trace.status == "running"]

    @app.get("/api/workflows", dependencies=[Depends(require_auth)])
    def workflows() -> list[dict[str, object]]:
        return trace_service.workflows()

    @app.get("/api/workflows/{workflow_id}", dependencies=[Depends(require_auth)])
    def workflow(workflow_id: str) -> dict[str, object]:
        item = trace_service.workflow(workflow_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "workflow_not_found"})
        return item

    @app.get("/api/workflows/{workflow_id}/runs", dependencies=[Depends(require_auth)])
    def workflow_runs(workflow_id: str) -> list[dict[str, object]]:
        return trace_service.workflow_runs(workflow_id)

    @app.get("/api/workflows/{workflow_id}/graph", dependencies=[Depends(require_auth)])
    def workflow_graph(workflow_id: str) -> dict[str, object]:
        return trace_service.workflow_graph(workflow_id)

    @app.get("/api/agents/status", dependencies=[Depends(require_auth)])
    def agent_status() -> dict[str, object]:
        status: dict[str, object] = {}
        for event in store.list_all_events():
            event_type = str(event.get("event_type", ""))
            if not event_type.startswith("agent."):
                continue
            actor = str(event.get("actor", "unknown"))
            status[actor] = {
                "agent": actor,
                "status": event_type.replace("agent.", ""),
                "trace_id": event.get("trace_id"),
                "timestamp": event.get("timestamp"),
            }
        return {"agents": list(status.values())}

    @app.get("/api/agents", dependencies=[Depends(require_auth)])
    def agents() -> list[dict[str, object]]:
        return trace_service.agents()

    @app.get("/api/agents/{agent_id}", dependencies=[Depends(require_auth)])
    def agent(agent_id: str) -> dict[str, object]:
        item = trace_service.agent(agent_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "agent_not_found"})
        return item

    @app.get("/api/agents/{agent_id}/runs", dependencies=[Depends(require_auth)])
    def agent_runs(agent_id: str) -> list[dict[str, object]]:
        return trace_service.agent_runs(agent_id)

    @app.get("/api/agents/{agent_id}/messages", dependencies=[Depends(require_auth)])
    def agent_messages(agent_id: str) -> list[dict[str, object]]:
        return trace_service.agent_messages(agent_id)

    @app.get("/api/models", dependencies=[Depends(require_auth)])
    def models() -> list[dict[str, object]]:
        return trace_service.models()

    @app.get("/api/providers", dependencies=[Depends(require_auth)])
    def providers() -> list[dict[str, object]]:
        return trace_service.provider_health()

    @app.get("/api/providers/health", dependencies=[Depends(require_auth)])
    def providers_health() -> list[dict[str, object]]:
        return trace_service.provider_health()

    @app.get("/api/model-calls", dependencies=[Depends(require_auth)])
    def model_calls(
        trace_id: str | None = None,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        status: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        agent_id: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> list[dict[str, object]]:
        return _filter_records(
            trace_service.model_calls(trace_id, 5000),
            limit=limit,
            offset=offset,
            exact={"status": status, "provider": provider, "model": model, "agent_id": agent_id},
            started_after=started_after,
            started_before=started_before,
        )

    @app.get("/api/costs/summary", dependencies=[Depends(require_auth)])
    def costs_summary() -> dict[str, object]:
        return trace_service.cost_summary()

    @app.get("/api/costs/by-workflow", dependencies=[Depends(require_auth)])
    def costs_by_workflow() -> list[dict[str, object]]:
        return trace_service.cost_by_dimension("workflow")

    @app.get("/api/costs/by-agent", dependencies=[Depends(require_auth)])
    def costs_by_agent() -> list[dict[str, object]]:
        return trace_service.cost_by_dimension("agent")

    @app.get("/api/costs/by-model", dependencies=[Depends(require_auth)])
    def costs_by_model() -> list[dict[str, object]]:
        return trace_service.cost_by_dimension("model")

    @app.get("/api/costs/by-provider", dependencies=[Depends(require_auth)])
    def costs_by_provider() -> list[dict[str, object]]:
        return trace_service.cost_by_dimension("provider")

    @app.get("/api/costs/by-failed-run", dependencies=[Depends(require_auth)])
    def costs_by_failed_run() -> list[dict[str, object]]:
        return trace_service.cost_by_failed_run()

    @app.get("/api/costs/forecast", dependencies=[Depends(require_auth)])
    def costs_forecast() -> dict[str, object]:
        summary = trace_service.cost_summary()
        return {
            "projected_monthly_spend": summary.get("projected_monthly_spend", 0),
            "budget_remaining": summary.get("budget_remaining", 0),
            "budget_used": summary.get("budget_used", 0),
        }

    @app.get("/api/tools", dependencies=[Depends(require_auth)])
    def tools() -> list[dict[str, object]]:
        calls = trace_service.tool_calls(limit=1000)
        seen: dict[str, dict[str, object]] = {}
        for call in calls:
            name = str(call.get("tool_name", "unknown"))
            current = seen.setdefault(name, {"tool_name": name, "calls": 0, "failures": 0, "risk_level": call.get("risk_level")})
            current["calls"] = int(current["calls"]) + 1
            if call.get("status") == "failed":
                current["failures"] = int(current["failures"]) + 1
        return list(seen.values())

    @app.get("/api/tool-calls", dependencies=[Depends(require_auth)])
    def tool_calls(
        trace_id: str | None = None,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        status: str | None = None,
        tool: str | None = None,
        agent_id: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> list[dict[str, object]]:
        return _filter_records(
            trace_service.tool_calls(trace_id, 5000),
            limit=limit,
            offset=offset,
            exact={"status": status, "tool_name": tool, "agent_id": agent_id},
            started_after=started_after,
            started_before=started_before,
        )

    @app.get("/api/tool-calls/{tool_call_id}", dependencies=[Depends(require_auth)])
    def tool_call(tool_call_id: str) -> dict[str, object]:
        item = trace_service.tool_call(tool_call_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "tool_call_not_found"})
        return item

    @app.get("/api/memory", dependencies=[Depends(require_auth)])
    def memory(agent: str | None = None, namespace: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        return memory_service.list_memories(agent=agent, namespace=namespace, limit=limit)

    @app.get("/api/memory/operations", dependencies=[Depends(require_auth)])
    def memory_operations(
        trace_id: str | None = None,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        operation: str | None = None,
        agent_id: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> list[dict[str, object]]:
        return _filter_records(
            trace_service.memory_operations(trace_id, 5000),
            limit=limit,
            offset=offset,
            exact={"operation": operation, "agent_id": agent_id},
            started_after=started_after,
            started_before=started_before,
        )

    @app.get("/api/memory/records", dependencies=[Depends(require_auth)])
    def memory_records(agent: str | None = None, namespace: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        return memory_service.list_memories(agent=agent, namespace=namespace, limit=limit)

    @app.get("/api/rag/retrievals", dependencies=[Depends(require_auth)])
    def rag_retrievals(
        trace_id: str | None = None,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        agent_id: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> list[dict[str, object]]:
        return _filter_records(
            trace_service.rag_retrievals(trace_id, 5000),
            limit=limit,
            offset=offset,
            exact={"agent_id": agent_id},
            started_after=started_after,
            started_before=started_before,
        )

    @app.get("/api/rag/retrievals/{retrieval_id}", dependencies=[Depends(require_auth)])
    def rag_retrieval(retrieval_id: str) -> dict[str, object]:
        item = trace_service.rag_retrieval(retrieval_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "retrieval_not_found"})
        return item

    @app.get("/api/prompts", dependencies=[Depends(require_auth)])
    def prompts() -> list[dict[str, object]]:
        return trace_service.prompts()

    @app.get("/api/prompts/{prompt_id}/versions", dependencies=[Depends(require_auth)])
    def prompt_versions_by_prompt(prompt_id: str) -> list[dict[str, object]]:
        return trace_service.prompt_versions_for_prompt(prompt_id)

    @app.get("/api/prompts/compare", dependencies=[Depends(require_auth)])
    def prompt_compare(left: str, right: str) -> dict[str, object]:
        return trace_service.compare_prompts(left, right)

    @app.get("/api/memory/audit", dependencies=[Depends(require_auth)])
    def memory_audit(trace_id: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        return memory_service.audit_logs(trace_id, limit)

    @app.get("/api/approvals", dependencies=[Depends(require_auth)])
    def approvals(
        status: str | None = None,
        trace_id: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, object]]:
        return _filter_records(approval_service.list(status=status, limit=5000), limit=limit, offset=offset, exact={"trace_id": trace_id})

    @app.post("/api/approvals/{approval_id}/resolve", dependencies=[Depends(require_auth)])
    def resolve_approval(approval_id: str, request: ResolveApprovalRequest) -> dict[str, object]:
        return approval_service.resolve(approval_id, request.approved, request.reason)

    @app.post("/api/approvals/{approval_id}/approve", dependencies=[Depends(require_auth)])
    def approve(approval_id: str, reason: str | None = Body(default=None)) -> dict[str, object]:
        return approval_service.resolve(approval_id, True, reason)

    @app.post("/api/approvals/{approval_id}/reject", dependencies=[Depends(require_auth)])
    def reject(approval_id: str, reason: str | None = Body(default=None)) -> dict[str, object]:
        return approval_service.resolve(approval_id, False, reason)

    @app.get("/api/costs", dependencies=[Depends(require_auth)])
    def costs() -> dict[str, object]:
        return trace_service.costs()

    @app.get("/api/replay/checkpoints", dependencies=[Depends(require_auth)])
    def replay_checkpoints(trace_id: str | None = None) -> list[dict[str, object]]:
        if trace_id:
            return trace_service.checkpoints(trace_id)
        checkpoints: list[dict[str, object]] = []
        for trace in trace_service.list_traces(100):
            checkpoints.extend(trace_service.checkpoints(str(trace["trace_id"])))
        return checkpoints

    @app.post("/api/replay/{trace_id}", dependencies=[Depends(require_auth)])
    def replay_trace(trace_id: str, payload: dict[str, object] | None = Body(default=None)) -> dict[str, object]:
        mode = str((payload or {}).get("mode", "deterministic"))
        _validate_replay_mode(mode, bool((payload or {}).get("allow_side_effects", False)))
        return trace_service.create_replay(trace_id, None, mode)

    @app.post("/api/replay/{trace_id}/from-span/{span_id}", dependencies=[Depends(require_auth)])
    def replay_from_span(trace_id: str, span_id: str, payload: dict[str, object] | None = Body(default=None)) -> dict[str, object]:
        mode = str((payload or {}).get("mode", "deterministic-from-span"))
        _validate_replay_mode(mode, bool((payload or {}).get("allow_side_effects", False)))
        return trace_service.create_replay(trace_id, span_id, mode)

    @app.get("/api/replay/{replay_id}", dependencies=[Depends(require_auth)])
    def replay_result(replay_id: str) -> dict[str, object]:
        item = trace_service.replay_run(replay_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "replay_not_found"})
        return item

    @app.get("/api/evaluations", dependencies=[Depends(require_auth)])
    def evaluations() -> list[dict[str, object]]:
        return trace_service.evaluations()

    @app.get("/api/evaluations/summary", dependencies=[Depends(require_auth)])
    def evaluations_summary() -> dict[str, object]:
        return trace_service.evaluation_summary()

    @app.post("/api/evaluations/run", dependencies=[Depends(require_auth)])
    def evaluations_run(payload: dict[str, object] | None = Body(default=None)) -> dict[str, object]:
        return trace_service.run_evaluation(payload or {})

    @app.get("/api/audit-logs", dependencies=[Depends(require_auth)])
    def audit_logs(
        trace_id: str | None = None,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> list[dict[str, object]]:
        return _filter_records(
            memory_service.audit_logs(trace_id, 5000),
            limit=limit,
            offset=offset,
            started_after=started_after,
            started_before=started_before,
        )

    @app.get("/api/jobs", dependencies=[Depends(require_auth)])
    def jobs() -> list[dict[str, object]]:
        return job_service.list()

    @app.post("/api/jobs/compact", dependencies=[Depends(require_auth)])
    def compact(background_tasks: BackgroundTasks) -> dict[str, object]:
        job_id = job_service.create("compact")

        def run_compact() -> None:
            job_service.mark(job_id, "running")
            job_service.mark(job_id, "succeeded", {"message": "SQLite handles local compaction through VACUUM in user scripts."})

        background_tasks.add_task(run_compact)
        return {"job_id": job_id, "status": "queued"}

    @app.get("/api/events/stream", dependencies=[Depends(require_auth)])
    async def stream_events() -> StreamingResponse:
        async def generator():
            seen: set[str] = set()
            while True:
                events = store.list_all_events(250)
                for event in events:
                    event_id = str(event.get("event_id", ""))
                    if event_id in seen:
                        continue
                    seen.add(event_id)
                    payload = dict(event)
                    event_name = _live_event_name(str(event.get("event_type", "")))
                    payload["live_event"] = event_name
                    encoded = json.dumps(payload)
                    yield f"event: trace_event\ndata: {encoded}\n\n"
                    yield f"event: {event_name}\ndata: {encoded}\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(generator(), media_type="text/event-stream")

    @app.get("/api/events/live", dependencies=[Depends(require_auth)])
    async def live_events() -> StreamingResponse:
        return await stream_events()

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        await websocket.accept()
        seen: set[str] = set()
        try:
            while True:
                events = store.list_all_events(250)
                for event in events:
                    event_id = str(event.get("event_id", ""))
                    if event_id in seen:
                        continue
                    seen.add(event_id)
                    await websocket.send_json(event)
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(DEFAULT_METRICS.prometheus_text(), media_type="text/plain")

    return app


def _live_event_name(event_type: str) -> str:
    return {
        "workflow.started": "workflow_started",
        "workflow.finished": "workflow_completed",
        "workflow.failed": "failure_occurred",
        "task.retry_scheduled": "retry_started",
        "model.call": "model_call_started",
        "model.response": "model_call_completed",
        "model.failed": "failure_occurred",
        "model.error": "failure_occurred",
        "tool.started": "tool_call_started",
        "tool.finished": "tool_call_completed",
        "tool.failed": "failure_occurred",
        "memory.write": "memory_operation_recorded",
        "memory.read": "memory_operation_recorded",
        "rag.retrieval": "rag_retrieval_recorded",
        "approval.requested": "approval_requested",
        "checkpoint.saved": "checkpoint_saved",
    }.get(event_type, "trace_event")


def _filter_records(
    records: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
    exact: dict[str, object | None] | None = None,
    started_after: str | None = None,
    started_before: str | None = None,
) -> list[dict[str, object]]:
    filtered = records
    for key, value in (exact or {}).items():
        if value is None:
            continue
        filtered = [record for record in filtered if str(record.get(key, "")) == str(value)]
    if started_after:
        filtered = [record for record in filtered if _record_time(record) >= started_after]
    if started_before:
        filtered = [record for record in filtered if _record_time(record) <= started_before]
    return filtered[offset: offset + limit]


def _record_time(record: dict[str, object]) -> str:
    return str(record.get("started_at") or record.get("timestamp") or record.get("created_at") or "")


def _validate_replay_mode(mode: str, allow_side_effects: bool) -> None:
    accepted = {"deterministic", "simulated", "live", "deterministic-from-span"}
    if mode not in accepted:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail={"error": "invalid_replay_mode", "accepted": sorted(accepted)})
    if mode == "live" and not allow_side_effects:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail={
                "error": "live_replay_requires_explicit_side_effects",
                "message": "Live replay is non-deterministic and may call external providers. Set allow_side_effects=true to proceed.",
            },
        )
