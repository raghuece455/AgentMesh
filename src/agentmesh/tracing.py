from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agentmesh.storage import EventRecord, SQLiteStore
from agentmesh.telemetry import DEFAULT_METRICS, MetricsRegistry, configure_json_logging
from agentmesh.types import JsonObject, JsonValue, new_id, safe_json, utc_now


@dataclass(slots=True)
class TraceRecorder:
    store: SQLiteStore
    metrics: MetricsRegistry = field(default_factory=lambda: DEFAULT_METRICS)
    logger: logging.Logger = field(default_factory=configure_json_logging)
    otel: object | None = None
    root_spans: dict[str, str] = field(default_factory=dict)

    def start_workflow(self, name: str, input_value: JsonValue, trace_id: str | None = None) -> str:
        resolved_trace_id = trace_id or new_id("trace")
        self.store.create_workflow(resolved_trace_id, name, input_value)
        root_span_id = self.event(resolved_trace_id, "workflow.started", "workflow", {"name": name, "input": safe_json(input_value)})
        self.root_spans[resolved_trace_id] = root_span_id
        self.metrics.increment("agentmesh_workflows_started_total", labels={"workflow": name})
        return resolved_trace_id

    def finish_workflow(
        self,
        trace_id: str,
        status: str,
        output_value: JsonValue | None = None,
        error_value: JsonValue | None = None,
    ) -> None:
        self.store.finish_workflow(trace_id, status, output_value, error_value)
        self.event(
            trace_id,
            "workflow.finished",
            "workflow",
            {"status": status, "output": safe_json(output_value), "error": safe_json(error_value)},
            parent_span_id=self.root_spans.get(trace_id),
        )
        self.metrics.increment("agentmesh_workflows_finished_total", labels={"status": status})

    def root_span_id(self, trace_id: str) -> str | None:
        return self.root_spans.get(trace_id)

    def event(
        self,
        trace_id: str,
        event_type: str,
        actor: str,
        payload: JsonObject | None = None,
        parent_span_id: str | None = None,
        span_id: str | None = None,
    ) -> str:
        resolved_span_id = span_id or new_id("span")
        resolved_parent_span_id = parent_span_id
        if resolved_parent_span_id is None and event_type != "workflow.started":
            resolved_parent_span_id = self.root_spans.get(trace_id)
        event = EventRecord(
            event_id=new_id("evt"),
            trace_id=trace_id,
            span_id=resolved_span_id,
            parent_span_id=resolved_parent_span_id,
            timestamp=utc_now(),
            event_type=event_type,
            actor=actor,
            payload=payload or {},
        )
        self.store.record_event(event)
        if self.otel is not None:
            self.otel.record_event(
                trace_id=trace_id,
                span_id=resolved_span_id,
                event_type=event_type,
                actor=actor,
                payload=payload or {},
                parent_span_id=resolved_parent_span_id,
            )
        self.metrics.increment("agentmesh_events_total", labels={"event_type": event_type})
        self.logger.info(
            event_type,
            extra={"agentmesh": {"trace_id": trace_id, "span_id": resolved_span_id, "actor": actor, "payload": payload or {}}},
        )
        return resolved_span_id

    def timeline(self, trace_id: str) -> list[JsonObject]:
        return self.store.list_events(trace_id)


class TraceReplayer:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def replay(self, trace_id: str) -> JsonObject:
        from agentmesh.debug import ReplayEngine

        return ReplayEngine(self.store).replay(trace_id)
