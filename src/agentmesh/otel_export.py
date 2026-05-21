from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from agentmesh.types import JsonObject, JsonValue, redact_secrets, safe_json


def export_otel_json(trace_export: JsonObject, version: str = "0.3.0-alpha") -> JsonObject:
    """Convert an AgentMesh trace export into OpenTelemetry-compatible JSON.

    This intentionally produces collector-shaped JSON but does not push to an
    OTLP collector. The transport/exporter remains a separate integration.
    """

    safe_export = redact_secrets(safe_json(trace_export))
    if not isinstance(safe_export, dict):
        safe_export = {}
    trace = _object(safe_export.get("observable_trace")) or _object(safe_export.get("trace"))
    trace_id = str(safe_export.get("trace_id") or trace.get("trace_id") or "")
    spans = [_object(item) for item in _list(safe_export.get("spans")) if isinstance(item, dict)]
    events = [_object(item) for item in _list(safe_export.get("events")) if isinstance(item, dict)]
    model_calls = [_object(item) for item in _list(safe_export.get("model_calls")) if isinstance(item, dict)]
    tool_calls = [_object(item) for item in _list(safe_export.get("tool_calls")) if isinstance(item, dict)]
    memory_operations = [_object(item) for item in _list(safe_export.get("memory_operations")) if isinstance(item, dict)]
    rag_retrievals = [_object(item) for item in _list(safe_export.get("rag_retrievals")) if isinstance(item, dict)]
    approvals = [_object(item) for item in _list(safe_export.get("approvals")) if isinstance(item, dict)]

    otel_trace_id = _hex_id(trace_id or "missing-trace", 32)
    span_events = _events_by_span(events, model_calls, tool_calls, memory_operations, rag_retrievals, approvals)
    root_start = str(trace.get("started_at") or _first_timestamp(spans) or datetime.now(UTC).isoformat())
    root_end = str(trace.get("ended_at") or trace.get("started_at") or root_start)

    otel_spans = [_span_to_otel(otel_trace_id, span, span_events.get(str(span.get("span_id")), []), trace) for span in spans]
    if not otel_spans:
        otel_spans.append(
            {
                "traceId": otel_trace_id,
                "spanId": _hex_id(trace_id or "root", 16),
                "parentSpanId": "",
                "name": str(trace.get("workflow_name") or trace.get("name") or "agentmesh.workflow"),
                "kind": "SPAN_KIND_INTERNAL",
                "startTimeUnixNano": _unix_nano(root_start),
                "endTimeUnixNano": _unix_nano(root_end),
                "attributes": _attributes(
                    {
                        "agentmesh.trace_id": trace_id,
                        "agentmesh.workflow_id": trace.get("workflow_id"),
                        "agentmesh.workflow_name": trace.get("workflow_name") or trace.get("name"),
                        "agentmesh.run_id": trace.get("run_id"),
                        "agentmesh.environment": trace.get("environment"),
                        "agentmesh.is_demo": trace.get("is_demo"),
                    }
                ),
                "events": [],
                "status": _status(trace.get("status"), trace.get("error_message") or trace.get("error")),
            }
        )

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _attributes(
                        {
                            "service.name": "agentmesh",
                            "service.version": version,
                            "agentmesh.trace_id": trace_id,
                            "agentmesh.environment": trace.get("environment"),
                            "agentmesh.is_demo": trace.get("is_demo"),
                        }
                    )
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "agentmesh.otel_export", "version": version},
                        "spans": otel_spans,
                    }
                ],
            }
        ]
    }


def _span_to_otel(otel_trace_id: str, span: JsonObject, events: list[JsonObject], trace: JsonObject) -> JsonObject:
    span_id = str(span.get("span_id") or "span")
    status = str(span.get("status") or "unknown")
    start = str(span.get("started_at") or trace.get("started_at") or datetime.now(UTC).isoformat())
    end = str(span.get("ended_at") or span.get("started_at") or trace.get("ended_at") or start)
    parent = str(span.get("parent_span_id") or "")
    attrs = {
        "agentmesh.trace_id": span.get("trace_id") or trace.get("trace_id"),
        "agentmesh.workflow_id": span.get("workflow_id") or trace.get("workflow_id"),
        "agentmesh.workflow_name": span.get("workflow_name") or trace.get("workflow_name") or trace.get("name"),
        "agentmesh.run_id": span.get("run_id") or trace.get("run_id"),
        "agentmesh.agent_id": span.get("agent_id"),
        "agentmesh.agent_name": span.get("agent_name"),
        "agentmesh.task_id": span.get("task_id"),
        "agentmesh.task_name": span.get("task_name"),
        "agentmesh.event_type": span.get("event_type"),
        "agentmesh.provider": span.get("provider"),
        "agentmesh.model": span.get("model"),
        "agentmesh.prompt_tokens": span.get("prompt_tokens"),
        "agentmesh.completion_tokens": span.get("completion_tokens"),
        "agentmesh.total_tokens": span.get("total_tokens"),
        "agentmesh.estimated_cost": span.get("estimated_cost"),
        "agentmesh.cost_status": _cost_status(span),
        "agentmesh.environment": span.get("environment") or trace.get("environment"),
        "agentmesh.is_demo": span.get("is_demo") if span.get("is_demo") is not None else trace.get("is_demo"),
        "agentmesh.retry_count": span.get("retry_count"),
        "agentmesh.tool_name": span.get("tool_name"),
        "agentmesh.error_type": span.get("error_type"),
    }
    return {
        "traceId": otel_trace_id,
        "spanId": _hex_id(span_id, 16),
        "parentSpanId": _hex_id(parent, 16) if parent else "",
        "name": str(span.get("event_type") or span.get("task_name") or "agentmesh.span"),
        "kind": _kind(span),
        "startTimeUnixNano": _unix_nano(start),
        "endTimeUnixNano": max(_unix_nano(end), _unix_nano(start)),
        "attributes": _attributes(attrs),
        "events": [_otel_event(event) for event in events],
        "status": _status(status, span.get("error_message")),
    }


def _events_by_span(
    events: list[JsonObject],
    model_calls: list[JsonObject],
    tool_calls: list[JsonObject],
    memory_operations: list[JsonObject],
    rag_retrievals: list[JsonObject],
    approvals: list[JsonObject],
) -> dict[str, list[JsonObject]]:
    grouped: dict[str, list[JsonObject]] = {}
    for event in events:
        span_id = str(event.get("span_id") or "")
        if span_id:
            grouped.setdefault(span_id, []).append(
                {
                    "name": str(event.get("event_type") or "event"),
                    "time": event.get("timestamp"),
                    "attributes": {
                        "agentmesh.event_id": event.get("event_id"),
                        "agentmesh.actor": event.get("actor"),
                        "agentmesh.payload": event.get("payload"),
                    },
                }
            )
    for call in model_calls:
        _append_record(grouped, call, "model.call", "started_at", {"agentmesh.model_call_id": call.get("model_call_id")})
    for call in tool_calls:
        _append_record(grouped, call, "tool.call", "started_at", {"agentmesh.tool_call_id": call.get("tool_call_id")})
    for operation in memory_operations:
        _append_record(grouped, operation, "memory.operation", "timestamp", {"agentmesh.operation_id": operation.get("operation_id")})
    for retrieval in rag_retrievals:
        _append_record(grouped, retrieval, "rag.retrieval", "timestamp", {"agentmesh.retrieval_id": retrieval.get("retrieval_id")})
    for approval in approvals:
        _append_record(grouped, approval, "approval.request", "created_at", {"agentmesh.approval_id": approval.get("approval_id")})
    return grouped


def _append_record(grouped: dict[str, list[JsonObject]], record: JsonObject, name: str, timestamp_key: str, extra: JsonObject) -> None:
    span_id = str(record.get("span_id") or "")
    if not span_id:
        return
    grouped.setdefault(span_id, []).append({"name": name, "time": record.get(timestamp_key), "attributes": {**extra, **record}})


def _otel_event(event: JsonObject) -> JsonObject:
    return {
        "name": str(event.get("name") or "event"),
        "timeUnixNano": _unix_nano(str(event.get("time") or datetime.now(UTC).isoformat())),
        "attributes": _attributes(_object(event.get("attributes"))),
    }


def _attributes(values: dict[str, Any]) -> list[JsonObject]:
    attrs: list[JsonObject] = []
    for key, value in values.items():
        if value is None:
            continue
        attrs.append({"key": key, "value": _otel_value(redact_secrets(safe_json(value)))})
    return attrs


def _otel_value(value: JsonValue) -> JsonObject:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_otel_value(item) for item in value]}}
    if isinstance(value, dict):
        return {"stringValue": str(value)}
    return {"stringValue": "" if value is None else str(value)}


def _status(status: Any, error: Any = None) -> JsonObject:
    normalized = str(status or "").lower()
    if normalized in {"failed", "error", "rejected"} or error:
        payload: JsonObject = {"code": "STATUS_CODE_ERROR"}
        if error:
            payload["message"] = str(error)
        return payload
    if normalized in {"succeeded", "approved", "healthy"}:
        return {"code": "STATUS_CODE_OK"}
    return {"code": "STATUS_CODE_UNSET"}


def _kind(span: JsonObject) -> str:
    event_type = str(span.get("event_type") or "")
    if event_type.startswith("model."):
        return "SPAN_KIND_CLIENT"
    if event_type.startswith("tool."):
        return "SPAN_KIND_CLIENT"
    return "SPAN_KIND_INTERNAL"


def _cost_status(span: JsonObject) -> str:
    metadata = _object(span.get("metadata"))
    status = metadata.get("cost_status")
    if status:
        return str(status)
    provider = str(span.get("provider") or "")
    cost = float(span.get("estimated_cost") or 0)
    if provider == "ollama" or provider == "mock":
        return "local/free"
    return "estimated" if cost else "unknown"


def _unix_nano(value: str) -> int:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000)


def _hex_id(value: str, length: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _object(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_timestamp(spans: list[JsonObject]) -> str | None:
    for span in spans:
        value = span.get("started_at")
        if isinstance(value, str):
            return value
    return None
