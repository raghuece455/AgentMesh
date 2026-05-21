from __future__ import annotations

from datetime import datetime

from agentmesh.storage import SQLiteStore
from agentmesh.types import JsonObject


VALID_STATUSES = {"running", "succeeded", "failed", "cancelled", "retry", "event"}


def validate_traces(store: SQLiteStore, limit: int = 200) -> JsonObject:
    issues: list[JsonObject] = []
    traces = store.list_observable_traces(limit)
    invalid_trace_ids: set[str] = set()
    counters: dict[str, int] = {
        "orphan_spans": 0,
        "missing_root_spans": 0,
        "multiple_root_spans": 0,
        "missing_parent_spans": 0,
        "invalid_timestamps": 0,
        "negative_durations": 0,
        "failed_spans_without_errors": 0,
        "model_calls_without_spans": 0,
        "tool_calls_without_spans": 0,
        "memory_ops_without_spans": 0,
        "cost_records_without_references": 0,
        "broken_replay_checkpoints": 0,
    }
    for trace in traces:
        trace_id = str(trace["trace_id"])
        spans = store.list_spans(trace_id)
        span_ids = {str(span["span_id"]) for span in spans}
        roots = [span for span in spans if not span.get("parent_span_id")]
        if not trace_id:
            _add_issue(issues, counters, invalid_trace_ids, trace_id, "missing_trace_id", "Trace is missing trace_id.")
        if len(roots) == 0:
            _add_issue(issues, counters, invalid_trace_ids, trace_id, "missing_root_spans", "Trace has no root span.")
        if len(roots) > 1:
            _add_issue(issues, counters, invalid_trace_ids, trace_id, "multiple_root_spans", f"Expected one root span, found {len(roots)}.")
        for span in spans:
            span_id = str(span["span_id"])
            parent = span.get("parent_span_id")
            if parent and str(parent) not in span_ids:
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "orphan_spans", f"Span {span_id} references missing parent {parent}.", span_id)
                counters["missing_parent_spans"] += 1
            status = str(span.get("status"))
            if status not in VALID_STATUSES:
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "invalid_status", f"Span {span_id} has invalid status {status}.", span_id)
            if _timestamp_invalid(span):
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "invalid_timestamps", f"Span {span_id} has invalid timestamps.", span_id)
            if _duration_negative(span):
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "negative_durations", f"Span {span_id} has negative duration.", span_id)
            if status == "failed" and not (span.get("error_type") or span.get("error_message")):
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "failed_spans_without_errors", f"Failed span {span_id} has no error fields.", span_id)
        for call in store.list_model_calls(trace_id):
            if call.get("span_id") not in span_ids:
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "model_calls_without_spans", "Model call does not link to an existing span.", str(call.get("span_id")))
            if not call.get("provider") or not call.get("model"):
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "missing_model_metadata", "Model call is missing provider or model.", str(call.get("span_id")))
        for call in store.list_tool_calls(trace_id):
            if call.get("span_id") not in span_ids:
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "tool_calls_without_spans", "Tool call does not link to an existing span.", str(call.get("span_id")))
        for operation in store.list_memory_operations(trace_id):
            if operation.get("span_id") not in span_ids:
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "memory_ops_without_spans", "Memory operation does not link to an existing span.", str(operation.get("span_id")))
        for checkpoint in store.list_checkpoints(trace_id):
            if not checkpoint.get("state"):
                _add_issue(issues, counters, invalid_trace_ids, trace_id, "broken_replay_checkpoints", "Replay checkpoint has empty state.", str(checkpoint.get("checkpoint_id")))
        _validate_cost_records(store, trace_id, span_ids, issues, counters, invalid_trace_ids)
    return {
        "status": "ok" if not issues else "issues_found",
        "trace_count": len(traces),
        "total_traces_checked": len(traces),
        "valid_traces": len(traces) - len(invalid_trace_ids),
        "invalid_traces": len(invalid_trace_ids),
        "issue_count": len(issues),
        **counters,
        "issues": issues,
    }


def _issue(trace_id: str, kind: str, message: str, span_id: str | None = None) -> JsonObject:
    return {"trace_id": trace_id, "span_id": span_id, "kind": kind, "message": message}


def _add_issue(
    issues: list[JsonObject],
    counters: dict[str, int],
    invalid_trace_ids: set[str],
    trace_id: str,
    kind: str,
    message: str,
    span_id: str | None = None,
) -> None:
    issues.append(_issue(trace_id, kind, message, span_id))
    if kind in counters:
        counters[kind] += 1
    invalid_trace_ids.add(trace_id)


def _timestamp_invalid(span: JsonObject) -> bool:
    started = span.get("started_at")
    ended = span.get("ended_at")
    if not isinstance(started, str):
        return True
    try:
        datetime.fromisoformat(started)
    except ValueError:
        return True
    if isinstance(ended, str):
        try:
            datetime.fromisoformat(ended)
        except ValueError:
            return True
    return False


def _duration_negative(span: JsonObject) -> bool:
    duration = span.get("duration_ms")
    if duration is not None:
        try:
            return float(duration) < 0
        except (TypeError, ValueError):
            return True
    started = span.get("started_at")
    ended = span.get("ended_at")
    if isinstance(started, str) and isinstance(ended, str):
        try:
            return datetime.fromisoformat(ended) < datetime.fromisoformat(started)
        except ValueError:
            return True
    return False


def _validate_cost_records(
    store: SQLiteStore,
    trace_id: str,
    span_ids: set[str],
    issues: list[JsonObject],
    counters: dict[str, int],
    invalid_trace_ids: set[str],
) -> None:
    conn = getattr(store, "_conn", None)
    if conn is None:
        return
    rows = conn.execute(
        "select cost_record_id, metadata_json from cost_records where trace_id = ?",
        (trace_id,),
    ).fetchall()
    for row in rows:
        metadata = row["metadata_json"] or ""
        if "model_call_id" not in metadata and "span_id" not in metadata and not span_ids:
            _add_issue(
                issues,
                counters,
                invalid_trace_ids,
                trace_id,
                "cost_records_without_references",
                "Cost record does not expose a model call or span reference in metadata.",
                str(row["cost_record_id"]),
            )
