from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from agentmesh.costs import CostTracker
from agentmesh.debug import FailedRunDiagnosis, ReplayEngine, TimeTravelDebugger
from agentmesh.evaluation import RunComparator
from agentmesh.otel_export import export_otel_json
from agentmesh.types import JsonObject, JsonValue, new_id, utc_now


@dataclass(slots=True)
class TraceService:
    store: object

    def list_traces(
        self,
        limit: int = 100,
        filters: dict[str, object] | None = None,
        offset: int = 0,
    ) -> list[JsonObject]:
        if hasattr(self.store, "list_observable_traces"):
            return self.store.list_observable_traces(limit, filters, offset)
        return [trace.to_json() for trace in self.store.list_traces(limit)]

    def get_trace_detail(self, trace_id: str) -> JsonObject:
        trace = self.store.get_observable_trace(trace_id) if hasattr(self.store, "get_observable_trace") else self.store.get_trace(trace_id)
        events = self.store.list_events(trace_id)
        spans = self.store.list_spans(trace_id) if hasattr(self.store, "list_spans") else []
        task_graph = [
            {
                "event": event["event_type"],
                "actor": event["actor"],
                "span_id": event["span_id"],
                "parent_span_id": event["parent_span_id"],
            }
            for event in events
            if str(event["event_type"]).startswith(("task.", "agent.", "tool.", "model.", "rag.", "memory.", "approval."))
        ]
        # Only run failure diagnosis for traces that actually failed — it scans
        # the full event list and is the most expensive sub-call for healthy runs.
        trace_status = trace.get("status") if isinstance(trace, dict) else None
        diagnosis = self.diagnose(trace_id) if trace_status in ("failed", "cancelled") else {"trace_id": trace_id, "found": True, "findings": []}
        return {
            "trace": trace,
            "events": events,
            "spans": spans,
            "task_graph": task_graph,
            "model_calls": self.model_calls(trace_id),
            "tool_calls": self.tool_calls(trace_id),
            "memory_operations": self.memory_operations(trace_id),
            "rag_retrievals": self.rag_retrievals(trace_id),
            "prompt_versions": self.prompt_versions(trace_id),
            "checkpoints": self.checkpoints(trace_id),
            "costs": self.costs(trace_id),
            "diagnosis": diagnosis,
        }

    def spans(self, trace_id: str) -> list[JsonObject]:
        return self.store.list_spans(trace_id) if hasattr(self.store, "list_spans") else []

    def events(self, trace_id: str) -> list[JsonObject]:
        return self.store.list_events(trace_id)

    def model_calls(self, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
        return self.store.list_model_calls(trace_id, limit) if hasattr(self.store, "list_model_calls") else []

    def tool_calls(self, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
        return self.store.list_tool_calls(trace_id, limit) if hasattr(self.store, "list_tool_calls") else []

    def tool_call(self, tool_call_id: str) -> JsonObject | None:
        return self.store.get_tool_call(tool_call_id) if hasattr(self.store, "get_tool_call") else None

    def memory_operations(self, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
        return self.store.list_memory_operations(trace_id, limit) if hasattr(self.store, "list_memory_operations") else []

    def rag_retrievals(self, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
        return self.store.list_rag_retrievals(trace_id, limit) if hasattr(self.store, "list_rag_retrievals") else []

    def rag_retrieval(self, retrieval_id: str) -> JsonObject | None:
        return self.store.get_rag_retrieval(retrieval_id) if hasattr(self.store, "get_rag_retrieval") else None

    def replay(self, trace_id: str) -> JsonObject:
        return ReplayEngine(self.store).replay(trace_id)

    def create_replay(self, trace_id: str, span_id: str | None = None, mode: str = "deterministic") -> JsonObject:
        replay = self.replay(trace_id)
        if hasattr(self.store, "create_replay"):
            return self.store.create_replay(trace_id, span_id, mode, replay)
        return replay

    def replay_runs(self) -> list[JsonObject]:
        return self.store.list_replay_runs() if hasattr(self.store, "list_replay_runs") else []

    def replay_run(self, replay_id: str) -> JsonObject | None:
        return self.store.get_replay_run(replay_id) if hasattr(self.store, "get_replay_run") else None

    def costs(self, trace_id: str | None = None) -> JsonObject:
        return CostTracker(self.store).summarize(trace_id).to_json()

    def cost_summary(self) -> JsonObject:
        return self.store.cost_summary() if hasattr(self.store, "cost_summary") else self.costs()

    def cost_by_dimension(self, dimension: str) -> list[JsonObject]:
        return self.store.cost_by_dimension(dimension) if hasattr(self.store, "cost_by_dimension") else []

    def cost_by_failed_run(self) -> list[JsonObject]:
        return self.store.cost_by_failed_run() if hasattr(self.store, "cost_by_failed_run") else []

    def checkpoints(self, trace_id: str) -> list[JsonObject]:
        return self.store.list_checkpoints(trace_id)

    def checkpoint(self, checkpoint_id: str) -> JsonObject | None:
        return TimeTravelDebugger(self.store).inspect(checkpoint_id)

    def prompt_versions(self, trace_id: str | None = None) -> list[JsonObject]:
        if not hasattr(self.store, "list_prompt_versions"):
            return []
        return self.store.list_prompt_versions(trace_id)

    def export_trace(self, trace_id: str) -> JsonObject:
        return ReplayEngine(self.store).export_json(trace_id)

    def export_trace_otel_json(self, trace_id: str) -> JsonObject:
        from agentmesh import __version__

        payload = ReplayEngine(self.store).export_json(trace_id)
        if hasattr(self.store, "audit"):
            self.store.audit(trace_id, "system", "trace.exported", trace_id, {"format": "otel-json"})
        return export_otel_json(payload, version=__version__)

    def import_trace(self, payload: JsonObject) -> JsonObject:
        trace_id = ReplayEngine(self.store).import_json(payload)
        return {"trace_id": trace_id, "imported": True}

    def compare(self, left_trace_id: str, right_trace_id: str) -> JsonObject:
        left = self.store.list_events(left_trace_id)
        right = self.store.list_events(right_trace_id)
        result = RunComparator().compare(left, right)
        result["left_trace_id"] = left_trace_id
        result["right_trace_id"] = right_trace_id
        return result

    def diagnose(self, trace_id: str) -> JsonObject:
        return FailedRunDiagnosis(self.store).diagnose(trace_id)

    def overview(self) -> JsonObject:
        return self.store.overview() if hasattr(self.store, "overview") else {"recent_traces": self.list_traces()}

    def overview_timeseries(self) -> JsonObject:
        return self.store.overview_timeseries() if hasattr(self.store, "overview_timeseries") else {"points": []}

    def workflows(self) -> list[JsonObject]:
        return self.store.list_workflows() if hasattr(self.store, "list_workflows") else []

    def workflow(self, workflow_id: str) -> JsonObject | None:
        return self.store.get_workflow(workflow_id) if hasattr(self.store, "get_workflow") else None

    def workflow_runs(self, workflow_id: str) -> list[JsonObject]:
        return self.store.list_workflow_runs(workflow_id) if hasattr(self.store, "list_workflow_runs") else []

    def workflow_graph(self, workflow_id: str) -> JsonObject:
        return self.store.workflow_graph(workflow_id) if hasattr(self.store, "workflow_graph") else {"nodes": [], "edges": []}

    def agents(self) -> list[JsonObject]:
        return self.store.list_agents() if hasattr(self.store, "list_agents") else []

    def agent(self, agent_id: str) -> JsonObject | None:
        return self.store.get_agent(agent_id) if hasattr(self.store, "get_agent") else None

    def agent_runs(self, agent_id: str) -> list[JsonObject]:
        return self.store.list_agent_runs(agent_id) if hasattr(self.store, "list_agent_runs") else []

    def agent_messages(self, agent_id: str) -> list[JsonObject]:
        return self.store.list_agent_messages(agent_id) if hasattr(self.store, "list_agent_messages") else []

    def models(self) -> list[JsonObject]:
        return self.store.list_models() if hasattr(self.store, "list_models") else []

    def provider_health(self) -> list[JsonObject]:
        return self.store.list_provider_health() if hasattr(self.store, "list_provider_health") else []

    def prompts(self) -> list[JsonObject]:
        return self.store.list_prompts() if hasattr(self.store, "list_prompts") else []

    def prompt_versions_for_prompt(self, prompt_id: str) -> list[JsonObject]:
        return self.store.prompt_versions_for_prompt(prompt_id) if hasattr(self.store, "prompt_versions_for_prompt") else []

    def compare_prompts(self, left: str, right: str) -> JsonObject:
        return self.store.compare_prompts(left, right) if hasattr(self.store, "compare_prompts") else {}

    def evaluations(self) -> list[JsonObject]:
        return self.store.list_evaluations() if hasattr(self.store, "list_evaluations") else []

    def evaluation_summary(self) -> JsonObject:
        return self.store.evaluation_summary() if hasattr(self.store, "evaluation_summary") else {}

    def run_evaluation(self, payload: JsonObject) -> JsonObject:
        return self.store.save_evaluation(payload) if hasattr(self.store, "save_evaluation") else {"created": False}


@dataclass(slots=True)
class MemoryService:
    store: object

    def list_memories(self, agent: str | None = None, namespace: str | None = None, limit: int = 100) -> list[JsonObject]:
        if not hasattr(self.store, "list_memories"):
            return []
        return self.store.list_memories(agent=agent, namespace=namespace, limit=limit)

    def audit_logs(self, trace_id: str | None = None, limit: int = 100) -> list[JsonObject]:
        return self.store.list_audit_logs(trace_id, limit)


@dataclass(slots=True)
class ApprovalService:
    store: object

    def list(self, status: str | None = None, limit: int = 100) -> list[JsonObject]:
        if not hasattr(self.store, "list_approvals"):
            return []
        return self.store.list_approvals(status=status, limit=limit)

    def resolve(self, approval_id: str, approved: bool, reason: str | None = None) -> JsonObject:
        if not hasattr(self.store, "resolve_approval"):
            return {"approval_id": approval_id, "resolved": False, "reason": "Approval store is unavailable"}
        self.store.resolve_approval(approval_id, approved, reason)
        return {"approval_id": approval_id, "resolved": True, "approved": approved}


@dataclass(slots=True)
class BackgroundJobService:
    _jobs: dict[str, JsonObject] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def create(self, kind: str, payload: JsonValue | None = None) -> str:
        job_id = new_id("job")
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "kind": kind,
                "payload": payload,
                "status": "queued",
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        return job_id

    def mark(self, job_id: str, status: str, result: JsonValue | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = status
            job["result"] = result
            job["updated_at"] = utc_now()

    def list(self) -> list[JsonObject]:
        with self._lock:
            return list(self._jobs.values())
