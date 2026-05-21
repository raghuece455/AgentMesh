from __future__ import annotations

from dataclasses import dataclass

from agentmesh.storage import SQLiteStore
from agentmesh.types import JsonObject, JsonValue, new_id, safe_json


class ReplayEngine:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def replay(self, trace_id: str) -> JsonObject:
        trace = self.store.get_trace(trace_id)
        if trace is None:
            return {"trace_id": trace_id, "found": False, "events": [], "checkpoints": []}
        events = self.store.list_events(trace_id)
        checkpoints = self.store.list_checkpoints(trace_id)
        return {
            "trace_id": trace_id,
            "found": True,
            "mode": "deterministic",
            "side_effects_disabled": True,
            "semantics": "uses recorded model outputs and recorded tool outputs; no external side effects are executed",
            "trace": trace,
            "prompts": _events(events, "model.call"),
            "outputs": _events(events, "model.response"),
            "tool_calls": _events(events, "tool.started") + _events(events, "tool.finished"),
            "agent_interactions": _events(events, "agent.started") + _events(events, "agent.finished"),
            "memory_state": checkpoints,
            "events": events,
            "checkpoints": checkpoints,
        }

    def export_json(self, trace_id: str) -> JsonObject:
        return self.store.export_trace(trace_id)

    def import_json(self, payload: JsonObject) -> str:
        return self.store.import_trace(payload)


@dataclass(slots=True)
class FailedRunDiagnosis:
    store: SQLiteStore

    def diagnose(self, trace_id: str) -> JsonObject:
        trace = self.store.get_trace(trace_id)
        if trace is None:
            return {"trace_id": trace_id, "found": False, "summary": "Trace not found", "findings": []}
        events = self.store.list_events(trace_id)
        failures = [
            event for event in events
            if "failed" in str(event.get("event_type", "")) or "error" in str(event.get("event_type", ""))
        ]
        retries = [event for event in events if "retry" in str(event.get("event_type", ""))]
        budget_events = [
            event for event in failures
            if "budget" in str(event.get("payload", "")).lower()
        ]
        findings: list[JsonObject] = []
        if budget_events:
            findings.append({"kind": "budget", "message": "The run appears to have exceeded a token or cost budget."})
        if retries:
            findings.append({"kind": "retry", "message": f"{len(retries)} retry event(s) were recorded before completion."})
        if failures:
            last_failure = failures[-1]
            findings.append(
                {
                    "kind": "failure",
                    "message": "The last failing event should be inspected first.",
                    "event": last_failure,
                }
            )
        if not findings:
            findings.append({"kind": "healthy", "message": "No failed or error events were found in this trace."})
        return {
            "trace_id": trace_id,
            "found": True,
            "status": trace.get("status"),
            "failure_count": len(failures),
            "retry_count": len(retries),
            "findings": findings,
        }


@dataclass(slots=True)
class TimeTravelDebugger:
    store: SQLiteStore

    def inspect(self, checkpoint_id: str) -> JsonObject | None:
        return self.store.get_checkpoint(checkpoint_id)

    def patch_memory(self, checkpoint_id: str, updates: JsonObject) -> str:
        checkpoint = self.store.get_checkpoint(checkpoint_id)
        if checkpoint is None:
            raise KeyError(checkpoint_id)
        state = checkpoint.get("state", {})
        if not isinstance(state, dict):
            state = {}
        memory = state.setdefault("workflow_memory", {"values": {}})
        if not isinstance(memory, dict):
            memory = {"values": {}}
            state["workflow_memory"] = memory
        values = memory.setdefault("values", {})
        if not isinstance(values, dict):
            values = {}
            memory["values"] = values
        values.update(updates)
        fork_id = new_id("ckpt")
        self.store.save_checkpoint(
            trace_id=str(checkpoint["trace_id"]),
            checkpoint_type="time_travel.patch",
            step_id=str(checkpoint.get("step_id") or ""),
            state=safe_json(state),
            checkpoint_id=fork_id,
        )
        return fork_id


def _events(events: list[JsonObject], event_type: str) -> list[JsonObject]:
    return [event for event in events if event.get("event_type") == event_type]
