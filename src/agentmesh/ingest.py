"""Framework-agnostic span ingestion.

Anything that can describe a finished span -- an OpenTelemetry exporter, the
AgentMesh SDK, a trace file -- is converted to :class:`SpanData` and written
into the same tables the AgentMesh runtime uses, so the dashboard, CLI, replay,
cost analytics, and MCP server work for traces produced by any framework.

Attribute conventions understood (first match wins):

* OpenTelemetry GenAI semantic conventions (``gen_ai.*``, ``mcp.*``)
* OpenInference (Arize Phoenix instrumentations: ``openinference.span.kind``, ``llm.*``)
* OpenLLMetry / Traceloop (``traceloop.*``, ``gen_ai.prompt.N.*``)
* Vercel AI SDK (``ai.*``)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agentmesh.pricing import estimate_model_cost
from agentmesh.types import JsonObject, JsonValue, dumps_json, safe_json

LLM_OPERATIONS = {"chat", "text_completion", "generate_content", "fetch_response"}
MEMORY_OPERATIONS = {
    "create_memory": "write",
    "update_memory": "write",
    "upsert_memory": "write",
    "delete_memory": "delete",
    "search_memory": "read",
    "create_memory_store": "write",
    "delete_memory_store": "delete",
}
CONTENT_KEYS = {
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.system_instructions",
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.result",
    "gen_ai.tool.definitions",
    "gen_ai.retrieval.documents",
    "gen_ai.retrieval.query.text",
    "gen_ai.memory.records",
    "gen_ai.memory.query.text",
    "input.value",
    "output.value",
    "tool.parameters",
    "traceloop.entity.input",
    "traceloop.entity.output",
    "ai.prompt",
    "ai.prompt.messages",
    "ai.response.text",
    "ai.response.toolCalls",
    "ai.toolCall.args",
    "ai.toolCall.result",
    "llm.invocation_parameters",
}
CONTENT_PREFIXES = (
    "llm.input_messages.",
    "llm.output_messages.",
    "gen_ai.prompt.",
    "gen_ai.completion.",
    "retrieval.documents.",
)
TERMINAL = {"succeeded", "failed", "cancelled"}


@dataclass(slots=True)
class SpanData:
    """A finished (or in-flight) span in a transport-neutral shape."""

    trace_id: str
    span_id: str
    name: str
    start_time: str
    end_time: str | None = None
    parent_span_id: str | None = None
    kind: str = "INTERNAL"
    status: str = "unset"
    status_message: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    resource: dict[str, Any] = field(default_factory=dict)
    scope: str | None = None


@dataclass(slots=True)
class NormalizedSpan:
    span: SpanData
    category: str
    operation: str | None
    event_type: str
    status: str
    error_type: str | None = None
    error_message: str | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cost_status: str = "unknown"
    cost_source: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    request_id: str | None = None
    finish_reasons: JsonValue = None
    system: JsonValue = None
    input: JsonValue = None
    output: JsonValue = None
    agent_name: str | None = None
    agent_description: str | None = None
    tool_name: str | None = None
    tool_type: str | None = None
    tool_call_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    tags: list[str] = field(default_factory=list)
    workflow_name: str | None = None
    environment: str | None = None
    service_name: str | None = None
    prompt_version: str | None = None
    retrieval_query: str | None = None
    documents: list[JsonValue] = field(default_factory=list)
    data_source: str | None = None
    memory_store: str | None = None
    memory_key: str | None = None
    mcp: JsonObject = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        return duration_ms(self.span.start_time, self.span.end_time)


def normalize_span(span: SpanData, capture_content: bool | None = None) -> NormalizedSpan:
    capture = content_capture_enabled() if capture_content is None else capture_content
    attrs = span.attributes
    operation = _str(_first(attrs, "gen_ai.operation.name"))
    category = _category(span, operation)
    status, error_type, error_message = _status(span)

    normalized = NormalizedSpan(
        span=span,
        category=category,
        operation=operation,
        event_type=_event_type(category, operation),
        status=status,
        error_type=error_type,
        error_message=error_message,
    )
    normalized.model = _str(
        _first(
            attrs, "gen_ai.response.model", "gen_ai.request.model", "llm.model_name", "ai.response.model", "ai.model.id"
        )
    )
    provider = _str(
        _first(attrs, "gen_ai.provider.name", "gen_ai.system", "llm.provider", "llm.system", "ai.model.provider")
    )
    if (
        provider
        and category in {"llm", "embedding"}
        and "." in provider
        and provider.split(".", 1)[0]
        in {"openai", "anthropic", "google", "mistral", "groq", "cohere", "xai", "deepseek"}
    ):
        provider = provider.split(".", 1)[0]  # Vercel AI SDK: "openai.chat" -> "openai"
    normalized.provider = provider or (_infer_provider(normalized.model) if category in {"llm", "embedding"} else None)

    invocation = _maybe_json(attrs.get("llm.invocation_parameters"))
    invocation = invocation if isinstance(invocation, dict) else {}
    normalized.temperature = _float_or_none(
        _first(attrs, "gen_ai.request.temperature", "ai.settings.temperature") or invocation.get("temperature")
    )
    normalized.top_p = _float_or_none(
        _first(attrs, "gen_ai.request.top_p", "ai.settings.topP") or invocation.get("top_p")
    )
    normalized.max_tokens = _int_or_none(
        _first(attrs, "gen_ai.request.max_tokens", "ai.settings.maxOutputTokens", "ai.settings.maxTokens")
        or invocation.get("max_tokens")
        or invocation.get("max_completion_tokens")
    )
    normalized.request_id = _str(_first(attrs, "gen_ai.response.id", "ai.response.id"))
    normalized.finish_reasons = safe_json(_first(attrs, "gen_ai.response.finish_reasons", "ai.response.finishReason"))

    if category in {"llm", "embedding"}:
        _usage(normalized, attrs)

    normalized.agent_name = _str(_first(attrs, "gen_ai.agent.name", "agent.name", "agentmesh.agent.name"))
    if not normalized.agent_name and category == "agent":
        normalized.agent_name = _str(attrs.get("traceloop.entity.name")) or _strip_operation_prefix(
            span.name, "invoke_agent"
        )
    normalized.agent_description = _str(attrs.get("gen_ai.agent.description"))

    if category == "tool":
        normalized.tool_name = _str(
            _first(attrs, "gen_ai.tool.name", "tool.name", "ai.toolCall.name", "traceloop.entity.name")
        ) or _strip_operation_prefix(_strip_operation_prefix(span.name, "execute_tool"), "tools/call")
        normalized.tool_call_id = _str(_first(attrs, "gen_ai.tool.call.id", "tool_call.id", "ai.toolCall.id"))
        normalized.tool_type = (
            "mcp" if attrs.get("mcp.method.name") else _str(attrs.get("gen_ai.tool.type")) or "function"
        )
    normalized.mcp = {key: safe_json(value) for key, value in attrs.items() if key.startswith("mcp.")}

    normalized.session_id = _str(
        _first(
            attrs,
            "gen_ai.conversation.id",
            "session.id",
            "agentmesh.session_id",
            "langfuse.session.id",
            "ai.telemetry.metadata.sessionId",
            "traceloop.association.properties.session_id",
            "conversation.id",
        )
    )
    normalized.user_id = _str(
        _first(
            attrs,
            "user.id",
            "enduser.id",
            "agentmesh.user_id",
            "langfuse.user.id",
            "ai.telemetry.metadata.userId",
            "traceloop.association.properties.user_id",
        )
    )
    normalized.tags = _tags(_first(attrs, "tag.tags", "agentmesh.tags", "langfuse.trace.tags"))
    normalized.workflow_name = _str(
        _first(attrs, "gen_ai.workflow.name", "agentmesh.workflow.name", "traceloop.workflow.name")
    )
    normalized.environment = _str(
        _first(span.resource, "deployment.environment.name", "deployment.environment")
        or _first(attrs, "agentmesh.environment", "deployment.environment.name")
    )
    normalized.service_name = _str(span.resource.get("service.name"))
    prompt_name = _str(attrs.get("gen_ai.prompt.name"))
    prompt_version = _str(attrs.get("gen_ai.prompt.version"))
    normalized.prompt_version = f"{prompt_name}@{prompt_version}" if prompt_name and prompt_version else prompt_name

    if category == "retrieval":
        normalized.retrieval_query = (
            _str(_first(attrs, "gen_ai.retrieval.query.text", "input.value")) if capture else None
        )
        documents = _maybe_json(attrs.get("gen_ai.retrieval.documents"))
        if not isinstance(documents, list):
            documents = _indexed(attrs, "retrieval.documents")
        normalized.documents = [safe_json(item) for item in documents] if isinstance(documents, list) else []
        normalized.data_source = _str(_first(attrs, "gen_ai.data_source.id", "db.system.name", "db.system"))
    if category == "memory":
        normalized.memory_store = _str(attrs.get("gen_ai.memory.store.id"))
        normalized.memory_key = _str(attrs.get("gen_ai.memory.record.id")) or (
            _str(attrs.get("gen_ai.memory.query.text")) if capture else None
        )

    if capture:
        normalized.system, normalized.input, normalized.output = _content(normalized, attrs)
    else:
        normalized.documents = [
            {"id": doc.get("id")} if isinstance(doc, dict) else None for doc in normalized.documents
        ]

    normalized.metadata = {
        "span_name": span.name,
        "span_kind": span.kind,
        "scope": span.scope,
        "operation": operation,
        "attributes": {
            key: _limit(safe_json(value), 2_000) for key, value in attrs.items() if not _is_content_key(key)
        },
        "resource": {key: _limit(safe_json(value), 500) for key, value in span.resource.items()},
        "events": [
            {"name": event.get("name"), "time": event.get("time")}
            for event in span.events
            if not str(event.get("name", "")).startswith("gen_ai.")
        ][:50],
        "finish_reasons": normalized.finish_reasons,
    }
    if normalized.agent_description:
        normalized.metadata["agent_description"] = normalized.agent_description
    return normalized


def ingest_spans(
    conn: sqlite3.Connection,
    spans: list[SpanData],
    source: str = "otlp",
    capture_content: bool | None = None,
) -> JsonObject:
    """Write spans into the observability tables. Idempotent per span_id."""
    from agentmesh.observability import _workflow_for_trace

    if not spans:
        return {"spans": 0, "traces": 0, "trace_ids": []}
    normalized = [normalize_span(span, capture_content) for span in spans]
    index = {item.span.span_id: item for item in normalized}
    for item in normalized:
        if not item.agent_name:
            item.agent_name = _inherited_agent(conn, item, index)

    by_trace: dict[str, list[NormalizedSpan]] = {}
    for item in normalized:
        by_trace.setdefault(item.span.trace_id, []).append(item)

    # Provider health is aggregated lazily when it is read (list_provider_health),
    # so ingestion cost stays proportional to the batch, not the database.
    for trace_id, items in by_trace.items():
        _upsert_trace(conn, trace_id, items, source)
        workflow = _workflow_for_trace(conn, trace_id)
        for item in items:
            _write_span(conn, item, workflow)
            _write_events(conn, item)
            if item.category in {"llm", "embedding"}:
                _write_model_call(conn, item, workflow)
            elif item.category == "tool":
                _write_tool_call(conn, item)
            elif item.category == "retrieval":
                _write_retrieval(conn, item)
            elif item.category == "memory":
                _write_memory_operation(conn, item)
            if item.agent_name:
                _upsert_agent(conn, item)
            _write_evaluations(conn, item)
            _write_policy_decisions(conn, item)
    return {"spans": len(normalized), "traces": len(by_trace), "trace_ids": list(by_trace)}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _category(span: SpanData, operation: str | None) -> str:
    attrs = span.attributes
    oi_kind = str(attrs.get("openinference.span.kind") or "").upper()
    tl_kind = str(attrs.get("traceloop.span.kind") or "").lower()
    ai_operation = str(attrs.get("ai.operationId") or attrs.get("operation.name") or "")
    if (
        operation in LLM_OPERATIONS
        or oi_kind == "LLM"
        or ai_operation.split(" ")[0].endswith((".doGenerate", ".doStream"))
    ):
        return "llm"
    if (
        operation == "embeddings"
        or oi_kind == "EMBEDDING"
        or ai_operation.startswith(("ai.embed.doEmbed", "ai.embedMany.doEmbed"))
    ):
        return "embedding"
    if (
        operation == "execute_tool"
        or oi_kind == "TOOL"
        or tl_kind == "tool"
        or attrs.get("mcp.method.name") == "tools/call"
        or "ai.toolCall.name" in attrs
    ):
        return "tool"
    if operation in {"invoke_agent", "create_agent"} or oi_kind == "AGENT" or tl_kind == "agent":
        return "agent"
    if operation == "invoke_workflow" or tl_kind == "workflow":
        return "workflow"
    if operation == "retrieval" or oi_kind in {"RETRIEVER", "RERANKER"}:
        return "retrieval"
    if operation in MEMORY_OPERATIONS:
        return "memory"
    if operation == "plan":
        return "plan"
    if oi_kind == "GUARDRAIL":
        return "guardrail"
    if oi_kind == "EVALUATOR":
        return "evaluator"
    if not ai_operation.startswith("ai.") and (
        "gen_ai.request.model" in attrs or "llm.token_count.prompt" in attrs or "gen_ai.usage.input_tokens" in attrs
    ):
        return "llm"
    return "chain"


def _event_type(category: str, operation: str | None) -> str:
    if category in {"llm", "embedding"}:
        return f"model.{operation or ('embeddings' if category == 'embedding' else 'chat')}"
    if category == "memory":
        return f"memory.{MEMORY_OPERATIONS.get(operation or '', 'operation')}"
    return {
        "tool": "tool.execute",
        "agent": "agent.invoke",
        "workflow": "workflow.run",
        "retrieval": "rag.retrieval",
        "plan": "task.plan",
        "guardrail": "guardrail.check",
        "evaluator": "evaluation.run",
    }.get(category, "task.run")


def _status(span: SpanData) -> tuple[str, str | None, str | None]:
    attrs = span.attributes
    exception = next((event for event in span.events if event.get("name") == "exception"), None)
    exception_attrs = exception.get("attributes", {}) if exception else {}
    error_type = _str(attrs.get("error.type")) or _str(exception_attrs.get("exception.type"))
    failed = span.status == "error" or bool(error_type)
    if not failed:
        return ("succeeded" if span.end_time else "running"), None, None
    message = span.status_message or _str(exception_attrs.get("exception.message")) or error_type
    return "failed", error_type or "error", message


def _usage(item: NormalizedSpan, attrs: dict[str, Any]) -> None:
    item.input_tokens = _int(
        _first(
            attrs,
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.prompt_tokens",
            "llm.token_count.prompt",
            "ai.usage.inputTokens",
            "ai.usage.promptTokens",
        )
    )
    item.output_tokens = _int(
        _first(
            attrs,
            "gen_ai.usage.output_tokens",
            "gen_ai.usage.completion_tokens",
            "llm.token_count.completion",
            "ai.usage.outputTokens",
            "ai.usage.completionTokens",
        )
    )
    item.cache_read_tokens = _int(
        _first(
            attrs,
            "gen_ai.usage.cache_read.input_tokens",
            "gen_ai.usage.cache_read_input_tokens",
            "llm.token_count.prompt_details.cache_read",
            "ai.usage.cachedInputTokens",
        )
    )
    item.cache_write_tokens = _int(
        _first(
            attrs,
            "gen_ai.usage.cache_write.input_tokens",
            "gen_ai.usage.cache_creation.input_tokens",
            "gen_ai.usage.cache_creation_input_tokens",
            "llm.token_count.prompt_details.cache_write",
        )
    )
    item.reasoning_tokens = _int(
        _first(
            attrs,
            "gen_ai.usage.reasoning.output_tokens",
            "llm.token_count.completion_details.reasoning",
            "ai.usage.reasoningTokens",
        )
    )
    # The conventions say input_tokens includes cached tokens; some older
    # instrumentations (Anthropic-style usage) report them separately.
    if item.cache_read_tokens + item.cache_write_tokens > item.input_tokens:
        item.input_tokens += item.cache_read_tokens + item.cache_write_tokens
    item.total_tokens = _int(
        _first(
            attrs,
            "llm.token_count.total",
            "gen_ai.usage.total_tokens",
            "llm.usage.total_tokens",
            "ai.usage.totalTokens",
        )
    ) or (item.input_tokens + item.output_tokens)
    reported = _float_or_none(_first(attrs, "agentmesh.cost_usd", "gen_ai.usage.cost", "llm.cost.total"))
    if reported is not None:
        item.cost_usd, item.cost_status, item.cost_source = reported, "exact", "instrumentation"
        return
    estimate = estimate_model_cost(
        item.provider,
        item.model,
        item.input_tokens,
        item.output_tokens,
        item.cache_read_tokens,
        item.reasoning_tokens,
        item.cache_write_tokens,
    )
    item.cost_usd, item.cost_status, item.cost_source = estimate.cost_usd, estimate.status, estimate.source


def _content(item: NormalizedSpan, attrs: dict[str, Any]) -> tuple[JsonValue, JsonValue, JsonValue]:
    system = _maybe_json(attrs.get("gen_ai.system_instructions"))
    event_system, event_input, event_output = _messages_from_events(item.span.events)
    if item.category in {"llm", "embedding"}:
        inputs = (
            _maybe_json(attrs.get("gen_ai.input.messages"))
            or _indexed(attrs, "llm.input_messages")
            or _indexed(attrs, "gen_ai.prompt")
            or _maybe_json(_first(attrs, "ai.prompt.messages", "ai.prompt"))
            or event_input
            or _maybe_json(attrs.get("input.value"))
        )
        outputs = (
            _maybe_json(attrs.get("gen_ai.output.messages"))
            or _indexed(attrs, "llm.output_messages")
            or _indexed(attrs, "gen_ai.completion")
            or _maybe_json(_first(attrs, "ai.response.text", "ai.response.toolCalls"))
            or event_output
            or _maybe_json(attrs.get("output.value"))
        )
    elif item.category == "tool":
        inputs = _maybe_json(
            _first(
                attrs,
                "gen_ai.tool.call.arguments",
                "tool.parameters",
                "ai.toolCall.args",
                "input.value",
                "traceloop.entity.input",
            )
        )
        outputs = _maybe_json(
            _first(attrs, "gen_ai.tool.call.result", "ai.toolCall.result", "output.value", "traceloop.entity.output")
        )
    else:
        inputs = (
            _maybe_json(
                _first(
                    attrs, "input.value", "traceloop.entity.input", "gen_ai.input.messages", "gen_ai.memory.query.text"
                )
            )
            or event_input
        )
        outputs = (
            _maybe_json(
                _first(
                    attrs, "output.value", "traceloop.entity.output", "gen_ai.output.messages", "gen_ai.memory.records"
                )
            )
            or event_output
        )
    return _limit(safe_json(system or event_system)), _limit(safe_json(inputs)), _limit(safe_json(outputs))


def _messages_from_events(events: list[dict[str, Any]]) -> tuple[JsonValue, list[JsonValue], list[JsonValue]]:
    system: JsonValue = None
    inputs: list[JsonValue] = []
    outputs: list[JsonValue] = []
    for event in events:
        name = str(event.get("name") or "")
        attrs = event.get("attributes") or {}
        if name == "gen_ai.client.inference.operation.details":
            system = _maybe_json(attrs.get("gen_ai.system_instructions")) or system
            value = _maybe_json(attrs.get("gen_ai.input.messages"))
            inputs.extend(value if isinstance(value, list) else [value] if value else [])
            value = _maybe_json(attrs.get("gen_ai.output.messages"))
            outputs.extend(value if isinstance(value, list) else [value] if value else [])
        elif name == "gen_ai.system.message":
            system = _maybe_json(attrs.get("content")) or system
        elif name in {"gen_ai.user.message", "gen_ai.assistant.message", "gen_ai.tool.message"}:
            inputs.append({"role": name.split(".")[1], "content": _maybe_json(attrs.get("content"))})
        elif name == "gen_ai.choice":
            outputs.append(_maybe_json(attrs.get("message")) or safe_json(attrs))
        elif name == "gen_ai.content.prompt":
            inputs.append(_maybe_json(attrs.get("gen_ai.prompt")))
        elif name == "gen_ai.content.completion":
            outputs.append(_maybe_json(attrs.get("gen_ai.completion")))
    return system, inputs, outputs


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _upsert_trace(conn: sqlite3.Connection, trace_id: str, items: list[NormalizedSpan], source: str) -> None:
    from agentmesh.observability import _workflow_id

    root = next((item for item in items if not item.span.parent_span_id), None)
    batch_start = min(item.span.start_time for item in items)
    session_id = next((item.session_id for item in items if item.session_id), None)
    user_id = next((item.user_id for item in items if item.user_id), None)
    tags = sorted({tag for item in items for tag in item.tags})
    service_name = next((item.service_name for item in items if item.service_name), None)
    failed_child = next((item for item in items if item.status == "failed"), None)

    existing = conn.execute("select * from workflow_runs where trace_id = ?", (trace_id,)).fetchone()
    if existing is not None and existing["source"] == "runtime":
        return  # the AgentMesh runtime owns this trace record

    previous = json.loads(existing["metadata_json"] or "{}") if existing is not None else {}
    previous = previous if isinstance(previous, dict) else {}
    root_kind = "root" if root is not None else None
    if root is None and previous.get("root_kind") != "root":
        # The top-most local span may have a remote parent (W3C traceparent from another
        # service) that is never ingested. Use it as a provisional root; an earlier local
        # root or a true root replaces it when it arrives.
        local_root = _local_root(conn, items)
        if local_root is not None and local_root.span.start_time <= str(
            previous.get("root_start") or local_root.span.start_time
        ):
            root, root_kind = local_root, "local"

    root_environment = root.environment if root else None
    if existing is not None and existing["environment"] not in (None, "", "local"):
        environment = root_environment or existing["environment"]
    else:
        environment = (
            root_environment or next((item.environment for item in items if item.environment), None) or "local"
        )

    if root is not None:
        name = _trace_name(root)
        status = root.status
        ended_at = root.span.end_time
        input_json = dumps_json(root.input) if root.input is not None else None
        output_json = dumps_json(root.output) if root.output is not None else None
        error_type = root.error_type or (failed_child.error_type if status == "failed" and failed_child else None)
        error_message = root.error_message or (
            failed_child.error_message if status == "failed" and failed_child else None
        )
    else:
        name = existing["workflow_name"] if existing is not None else (service_name or items[0].span.name)
        status = existing["status"] if existing is not None else "running"
        ended_at = existing["ended_at"] if existing is not None else None
        input_json = output_json = error_type = error_message = None

    started_at = min(batch_start, existing["started_at"]) if existing is not None else batch_start
    duration = duration_ms(started_at, ended_at)
    workflow_id = _workflow_id(name)
    final_root_kind = root_kind or previous.get("root_kind")
    metadata = {
        "source": source,
        "service_name": service_name,
        "root_kind": final_root_kind,
        "root_start": root.span.start_time if root is not None else previous.get("root_start"),
        "partial": final_root_kind != "root",
    }

    if existing is not None:
        previous_tags = json.loads(existing["tags_json"] or "[]")
        tags = sorted(set(tags) | set(previous_tags if isinstance(previous_tags, list) else []))
        session_id = existing["session_id"] or session_id
        user_id = existing["user_id"] or user_id
        input_json = input_json or existing["input_json"]
        output_json = output_json or existing["output_json"]
        if root is None:
            error_type, error_message = existing["error_type"], existing["error_message"]
        elif existing["workflow_name"] != name:
            _rename_trace(conn, trace_id, workflow_id, name)

    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        insert into workflows_catalog (workflow_id, workflow_name, created_at, updated_at, metadata_json)
        values (?, ?, ?, ?, ?)
        on conflict(workflow_id) do update set updated_at = excluded.updated_at
        """,
        (workflow_id, name, now, now, dumps_json({"source": source})),
    )
    conn.execute(
        """
        insert into workflow_runs
        (run_id, trace_id, workflow_id, workflow_name, status, started_at, ended_at, duration_ms, input_json, output_json,
         error_type, error_message, environment, is_demo, metadata_json, session_id, user_id, tags_json, source, service_name)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
        on conflict(run_id) do update set
          workflow_id = excluded.workflow_id,
          workflow_name = excluded.workflow_name,
          status = excluded.status,
          started_at = excluded.started_at,
          ended_at = excluded.ended_at,
          duration_ms = excluded.duration_ms,
          input_json = excluded.input_json,
          output_json = excluded.output_json,
          error_type = excluded.error_type,
          error_message = excluded.error_message,
          environment = excluded.environment,
          metadata_json = excluded.metadata_json,
          session_id = excluded.session_id,
          user_id = excluded.user_id,
          tags_json = excluded.tags_json,
          service_name = coalesce(excluded.service_name, workflow_runs.service_name)
        """,
        (
            trace_id,
            trace_id,
            workflow_id,
            name,
            status,
            started_at,
            ended_at,
            duration,
            input_json,
            output_json,
            error_type,
            error_message,
            environment,
            dumps_json(metadata),
            session_id,
            user_id,
            dumps_json(tags),
            source,
            service_name,
        ),
    )
    conn.execute(
        """
        insert or replace into traces
        (trace_id, run_id, workflow_id, workflow_name, status, started_at, ended_at, duration_ms, environment, is_demo, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            trace_id,
            trace_id,
            workflow_id,
            name,
            status,
            started_at,
            ended_at,
            duration,
            environment,
            dumps_json(metadata),
        ),
    )
    if existing is not None and existing["workflow_id"] != workflow_id:
        # A provisional name (from a child batch) was replaced by the root span's name.
        conn.execute(
            "delete from workflows_catalog where workflow_id = ? and workflow_id not in (select workflow_id from workflow_runs)",
            (existing["workflow_id"],),
        )
    error_json = dumps_json({"type": error_type, "message": error_message}) if error_message else dumps_json(None)
    conn.execute(
        """
        insert or replace into workflows (trace_id, name, status, started_at, ended_at, input_json, output_json, error_json)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trace_id,
            name,
            status,
            started_at,
            ended_at,
            input_json or dumps_json(None),
            output_json or dumps_json(None),
            error_json,
        ),
    )


def _rename_trace(conn: sqlite3.Connection, trace_id: str, workflow_id: str, name: str) -> None:
    conn.execute(
        "update spans set workflow_id = ?, workflow_name = ? where trace_id = ?", (workflow_id, name, trace_id)
    )
    conn.execute(
        "update cost_records set workflow_id = ?, workflow_name = ? where trace_id = ?", (workflow_id, name, trace_id)
    )


def _local_root(conn: sqlite3.Connection, items: list[NormalizedSpan]) -> NormalizedSpan | None:
    """Earliest entry-point span (server/consumer, agent, or workflow) whose parent is unknown."""
    batch_ids = {item.span.span_id for item in items}
    candidates = [
        item
        for item in items
        if item.span.parent_span_id not in batch_ids
        and (item.span.kind in {"SERVER", "CONSUMER"} or item.category in {"agent", "workflow"})
        and conn.execute("select 1 from spans where span_id = ?", (item.span.parent_span_id,)).fetchone() is None
    ]
    return min(candidates, key=lambda item: item.span.start_time, default=None)


def _trace_name(root: NormalizedSpan) -> str:
    if root.workflow_name:
        return root.workflow_name
    if root.category == "agent" and root.agent_name:
        return root.agent_name
    return root.span.name or root.service_name or "trace"


def _write_span(conn: sqlite3.Connection, item: NormalizedSpan, workflow: JsonObject) -> None:
    from agentmesh.observability import _agent_id

    span = item.span
    conn.execute(
        """
        insert or replace into spans
        (span_id, trace_id, run_id, workflow_id, workflow_name, parent_span_id, agent_id, agent_name, task_id, task_name,
         event_type, status, started_at, ended_at, duration_ms, input_json, output_json, error_type, error_message,
         retry_count, provider, model, prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, total_tokens,
         estimated_cost, temperature, top_p, max_tokens, prompt_version, tool_name, memory_operation, rag_document_ids_json,
         environment, is_demo, metadata_json, name, span_kind, cache_write_tokens)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        """,
        (
            span.span_id,
            span.trace_id,
            span.trace_id,
            workflow["workflow_id"],
            workflow["workflow_name"],
            span.parent_span_id,
            _agent_id(item.agent_name) if item.agent_name else None,
            item.agent_name,
            span.span_id if item.category in {"chain", "workflow", "plan", "agent"} else None,
            span.name if item.category in {"chain", "workflow", "plan", "agent"} else None,
            item.event_type,
            item.status,
            span.start_time,
            span.end_time,
            item.duration_ms,
            dumps_json(item.input),
            dumps_json(item.output),
            item.error_type,
            item.error_message,
            item.provider,
            item.model,
            item.input_tokens,
            item.output_tokens,
            item.cache_read_tokens,
            item.reasoning_tokens,
            item.total_tokens,
            item.cost_usd,
            item.temperature,
            item.top_p,
            item.max_tokens,
            item.prompt_version,
            item.tool_name,
            MEMORY_OPERATIONS.get(item.operation or "") if item.category == "memory" else None,
            dumps_json([_doc_id(doc) for doc in item.documents]),
            item.environment or workflow.get("environment") or "local",
            dumps_json({**item.metadata, "category": item.category, "cost_status": item.cost_status}),
            span.name,
            span.kind,
            item.cache_write_tokens,
        ),
    )


def _write_events(conn: sqlite3.Connection, item: NormalizedSpan) -> None:
    span = item.span
    actor = item.agent_name or "workflow"
    failed = item.status == "failed"
    error = {"kind": item.error_type, "message": item.error_message} if failed else None
    base: JsonObject = {"span_name": span.name, "source": "ingest", "category": item.category}
    pairs = {
        "llm": ("model.call", "model.failed" if failed else "model.response"),
        "embedding": ("model.call", "model.failed" if failed else "model.response"),
        "tool": ("tool.started", "tool.failed" if failed else "tool.finished"),
        "agent": ("agent.started", "agent.failed" if failed else "agent.finished"),
    }
    rows: list[tuple[str, str, JsonObject]] = []
    if item.category in pairs:
        start_type, end_type = pairs[item.category]
        if item.category in {"llm", "embedding"}:
            start_payload = {
                **base,
                "provider": item.provider,
                "model": item.model,
                "system": item.system,
                "prompt": item.input,
                "temperature": item.temperature,
                "top_p": item.top_p,
                "max_tokens": item.max_tokens,
            }
            end_payload = {
                **base,
                "provider": item.provider,
                "model": item.model,
                "output": item.output,
                "prompt_tokens": item.input_tokens,
                "completion_tokens": item.output_tokens,
                "cached_tokens": item.cache_read_tokens,
                "cache_write_tokens": item.cache_write_tokens,
                "reasoning_tokens": item.reasoning_tokens,
                "total_tokens": item.total_tokens,
                "cost_usd": item.cost_usd,
                "cost_status": item.cost_status,
                "latency_ms": item.duration_ms,
                "request_id": item.request_id,
            }
        elif item.category == "tool":
            start_payload = {**base, "tool": item.tool_name, "arguments": item.input}
            end_payload = {**base, "tool": item.tool_name, "result": item.output}
        else:
            start_payload = {**base, "input": item.input}
            end_payload = {**base, "output": item.output}
        rows.append(("s", start_type, start_payload))
        if span.end_time:
            rows.append(("e", end_type, {**end_payload, "error": error} if failed else end_payload))
    elif span.end_time:
        rows.append(
            (
                "e",
                f"{item.event_type}.failed" if failed else item.event_type,
                {**base, "input": item.input, "output": item.output, "error": error},
            )
        )
    for suffix, event_type, payload in rows:
        conn.execute(
            """
            insert or replace into events
            (event_id, trace_id, span_id, parent_span_id, timestamp, event_type, actor, payload_json)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"evt_{span.span_id}_{suffix}",
                span.trace_id,
                span.span_id,
                span.parent_span_id,
                span.start_time if suffix == "s" else span.end_time,
                event_type,
                actor,
                dumps_json(payload),
            ),
        )


def _write_model_call(conn: sqlite3.Connection, item: NormalizedSpan, workflow: JsonObject) -> None:
    from agentmesh.observability import _agent_id, _context_window

    span = item.span
    agent_id = _agent_id(item.agent_name) if item.agent_name else None
    provider = item.provider or "unknown"
    model = item.model or "unknown"
    metadata = dumps_json(
        {
            "operation": item.operation,
            "finish_reasons": item.finish_reasons,
            "span_name": span.name,
            "cost_notes": item.cost_source,
        }
    )
    conn.execute(
        """
        insert or replace into model_calls
        (model_call_id, trace_id, span_id, parent_span_id, agent_id, agent_name, task_id, task_name, provider, model,
         endpoint_alias, status, started_at, ended_at, duration_ms, prompt_version, prompt_json, output_json,
         prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, total_tokens, estimated_cost,
         cost_status, cost_source, temperature, top_p, max_tokens, context_window, error_type, error_message,
         request_id, retry_count, metadata_json, cache_write_tokens)
        values (?, ?, ?, ?, ?, ?, null, null, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            span.span_id,
            span.trace_id,
            span.span_id,
            span.parent_span_id,
            agent_id,
            item.agent_name,
            provider,
            model,
            item.operation,
            item.status,
            span.start_time,
            span.end_time,
            item.duration_ms,
            item.prompt_version,
            dumps_json({"system": item.system, "prompt": item.input}),
            dumps_json(item.output),
            item.input_tokens,
            item.output_tokens,
            item.cache_read_tokens,
            item.reasoning_tokens,
            item.total_tokens,
            item.cost_usd,
            item.cost_status,
            item.cost_source,
            item.temperature,
            item.top_p,
            item.max_tokens,
            _context_window(model),
            item.error_type,
            item.error_message,
            item.request_id,
            metadata,
            item.cache_write_tokens,
        ),
    )
    conn.execute(
        """
        insert or replace into cost_records
        (cost_record_id, trace_id, workflow_id, workflow_name, agent_id, agent_name, provider, model, status,
         prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, total_tokens, estimated_cost,
         cost_status, cost_source, latency_ms, timestamp, metadata_json, cache_write_tokens)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"cost_{span.span_id}",
            span.trace_id,
            workflow["workflow_id"],
            workflow["workflow_name"],
            agent_id,
            item.agent_name,
            provider,
            model,
            item.status,
            item.input_tokens,
            item.output_tokens,
            item.cache_read_tokens,
            item.reasoning_tokens,
            item.total_tokens,
            item.cost_usd,
            item.cost_status,
            item.cost_source,
            item.duration_ms,
            span.end_time or span.start_time,
            dumps_json({"operation": item.operation}),
            item.cache_write_tokens,
        ),
    )


def _write_tool_call(conn: sqlite3.Connection, item: NormalizedSpan) -> None:
    from agentmesh.observability import _agent_id

    span = item.span
    conn.execute(
        """
        insert or replace into tool_calls
        (tool_call_id, trace_id, span_id, parent_span_id, agent_id, agent_name, tool_name, tool_type, status,
         started_at, ended_at, duration_ms, permission_level, approval_status, risk_level, retry_count, side_effect,
         input_json, output_json, stdout, stderr, error_type, error_message, sandbox_logs_json, mcp_metadata_json,
         side_effects_json, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, 'not_required', ?, 0, 0, ?, ?, null, null, ?, ?, '[]', ?, '[]', ?)
        """,
        (
            span.span_id,
            span.trace_id,
            span.span_id,
            span.parent_span_id,
            _agent_id(item.agent_name) if item.agent_name else None,
            item.agent_name,
            item.tool_name or "unknown",
            item.tool_type or "function",
            item.status,
            span.start_time,
            span.end_time,
            item.duration_ms,
            "high" if item.status == "failed" else "low",
            dumps_json(item.input),
            dumps_json(item.output),
            item.error_type,
            item.error_message,
            dumps_json(item.mcp),
            dumps_json({"tool_call_id": item.tool_call_id, "span_name": span.name}),
        ),
    )


def _write_retrieval(conn: sqlite3.Connection, item: NormalizedSpan) -> None:
    from agentmesh.observability import _agent_id, _preview

    span = item.span
    documents = item.documents
    first = documents[0] if documents and isinstance(documents[0], dict) else {}
    conn.execute(
        """
        insert or replace into rag_retrievals
        (retrieval_id, trace_id, span_id, agent_id, agent_name, query, embedding_model, vector_store,
         retrieved_documents_json, chunk_ids_json, chunk_preview, scores_json, source_metadata_json, used_in_answer,
         citation_mapping_json, timestamp, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 1, '{}', ?, ?)
        """,
        (
            span.span_id,
            span.trace_id,
            span.span_id,
            _agent_id(item.agent_name) if item.agent_name else None,
            item.agent_name,
            item.retrieval_query,
            item.model,
            item.data_source or "unknown",
            dumps_json(documents),
            dumps_json([_doc_id(doc) for doc in documents]),
            _preview(first.get("content") if isinstance(first, dict) else None),
            dumps_json([doc.get("score") if isinstance(doc, dict) else None for doc in documents]),
            span.start_time,
            dumps_json({"span_name": span.name}),
        ),
    )


def _write_memory_operation(conn: sqlite3.Connection, item: NormalizedSpan) -> None:
    from agentmesh.observability import _agent_id, _preview

    span = item.span
    conn.execute(
        """
        insert or replace into memory_operations
        (operation_id, trace_id, span_id, agent_id, agent_name, memory_type, operation, key, value_preview, value_json,
         version, redacted, timestamp, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, 0, ?, ?)
        """,
        (
            span.span_id,
            span.trace_id,
            span.span_id,
            _agent_id(item.agent_name) if item.agent_name else None,
            item.agent_name,
            item.memory_store or "long-term",
            MEMORY_OPERATIONS.get(item.operation or "", "operation"),
            item.memory_key,
            _preview(item.output if item.output is not None else item.input),
            dumps_json(item.output if item.output is not None else item.input),
            span.start_time,
            dumps_json({"operation": item.operation, "span_name": span.name}),
        ),
    )


def _upsert_agent(conn: sqlite3.Connection, item: NormalizedSpan) -> None:
    from agentmesh.observability import _agent_id

    timestamp = item.span.end_time or item.span.start_time
    conn.execute(
        """
        insert into agents
        (agent_id, agent_name, role, instructions, provider, model, status, current_task, created_at, updated_at, metadata_json)
        values (?, ?, ?, null, ?, ?, ?, ?, ?, ?, ?)
        on conflict(agent_id) do update set
          role = coalesce(excluded.role, agents.role),
          provider = coalesce(excluded.provider, agents.provider),
          model = coalesce(excluded.model, agents.model),
          status = case when excluded.updated_at >= agents.updated_at then excluded.status else agents.status end,
          current_task = coalesce(excluded.current_task, agents.current_task),
          updated_at = case when excluded.updated_at > agents.updated_at then excluded.updated_at else agents.updated_at end
        """,
        (
            _agent_id(str(item.agent_name)),
            item.agent_name,
            item.agent_description,
            item.provider if item.category in {"llm", "embedding"} else None,
            item.model if item.category in {"llm", "embedding"} else None,
            item.status,
            item.span.name if item.category == "agent" else None,
            item.span.start_time,
            timestamp,
            dumps_json({"source": "ingest"}),
        ),
    )


def _write_evaluations(conn: sqlite3.Connection, item: NormalizedSpan) -> None:
    from agentmesh.observability import save_score

    for position, event in enumerate(item.span.events):
        if event.get("name") != "gen_ai.evaluation.result":
            continue
        attrs = event.get("attributes") or {}
        name = _str(attrs.get("gen_ai.evaluation.name"))
        if not name:
            continue
        save_score(
            conn,
            {
                "score_id": f"eval_{item.span.span_id}_{position}",
                "trace_id": item.span.trace_id,
                "span_id": item.span.span_id,
                "name": name,
                "value": _float_or_none(attrs.get("gen_ai.evaluation.score.value")),
                "label": _str(attrs.get("gen_ai.evaluation.score.label")),
                "comment": _str(attrs.get("gen_ai.evaluation.explanation")),
                "source": "otel",
                "created_at": event.get("time"),
            },
        )


POLICY_DECISION_EVENT = "agentmesh.policy.decision"


def _write_policy_decisions(conn: sqlite3.Connection, item: NormalizedSpan) -> None:
    """Guardrail decisions travel as span events, so they reach the server with the span."""
    from agentmesh.policy_store import save_decision

    for position, event in enumerate(item.span.events):
        if event.get("name") != POLICY_DECISION_EVENT:
            continue
        attrs = event.get("attributes") or {}
        details = attrs.get("agentmesh.policy.details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except ValueError:
                details = {"raw": details}
        save_decision(
            conn,
            {
                "decision_id": f"decision_{item.span.span_id}_{position}",
                "trace_id": item.span.trace_id,
                "span_id": item.span.span_id,
                "policy_id": _str(attrs.get("agentmesh.policy.id")),
                "policy_name": _str(attrs.get("agentmesh.policy.name")),
                "rule": _str(attrs.get("agentmesh.policy.rule")) or "unknown",
                "action": _str(attrs.get("agentmesh.policy.action")) or "deny",
                "enforced": attrs.get("agentmesh.policy.enforced") not in (False, "false", 0),
                "kind": _str(attrs.get("agentmesh.policy.kind")),
                "target": _str(attrs.get("agentmesh.policy.target")),
                "agent": _str(attrs.get("agentmesh.policy.agent")) or item.agent_name,
                "service": item.service_name,
                "reason": _str(attrs.get("agentmesh.policy.reason")),
                "details": details if isinstance(details, dict) else {},
                "created_at": event.get("time") or item.span.start_time,
            },
        )


def _inherited_agent(conn: sqlite3.Connection, item: NormalizedSpan, index: dict[str, NormalizedSpan]) -> str | None:
    parent_id = item.span.parent_span_id
    for _ in range(64):
        if not parent_id:
            return None
        parent = index.get(parent_id)
        if parent is not None:
            if parent.agent_name:
                return parent.agent_name
            parent_id = parent.span.parent_span_id
            continue
        row = conn.execute("select agent_name, parent_span_id from spans where span_id = ?", (parent_id,)).fetchone()
        if row is None:
            return None
        if row["agent_name"]:
            return str(row["agent_name"])
        parent_id = row["parent_span_id"]
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def content_capture_enabled() -> bool:
    return os.getenv("AGENTMESH_CAPTURE_CONTENT", "true").strip().lower() not in {"0", "false", "no", "off"}


def max_content_chars() -> int:
    try:
        return max(int(os.getenv("AGENTMESH_MAX_CONTENT_CHARS", "100000")), 256)
    except ValueError:
        return 100_000


def duration_ms(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((end_dt - start_dt).total_seconds() * 1000, 0.0)


def iso_from_unix_nano(value: object) -> str | None:
    try:
        nanos = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if nanos <= 0:
        return None
    seconds, remainder = divmod(nanos, 1_000_000_000)
    return (
        datetime.fromtimestamp(seconds, UTC).replace(microsecond=remainder // 1000).isoformat(timespec="microseconds")
    )


def _first(attrs: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = attrs.get(key)
        if value is not None and value != "" and value != []:
            return value
    return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = ",".join(str(item) for item in value)
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in {"{", "["}:
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _indexed(attrs: dict[str, Any], prefix: str) -> list[JsonObject]:
    pattern = re.compile(rf"^{re.escape(prefix)}\.(\d+)\.(.+)$")
    items: dict[int, JsonObject] = {}
    for key, value in attrs.items():
        match = pattern.match(key)
        if match:
            field_name = re.sub(r"^(message|document)\.", "", match.group(2))
            items.setdefault(int(match.group(1)), {})[field_name] = _maybe_json(safe_json(value))
    return [items[position] for position in sorted(items)]


def _tags(value: Any) -> list[str]:
    value = _maybe_json(value)
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str):
        return [tag.strip() for tag in value.split(",") if tag.strip()]
    return []


def _limit(value: JsonValue, limit: int | None = None) -> JsonValue:
    maximum = limit or max_content_chars()
    if isinstance(value, str):
        return value if len(value) <= maximum else f"{value[:maximum]}... [truncated {len(value) - maximum} chars]"
    if isinstance(value, dict | list):
        rendered = json.dumps(value, default=str)
        if len(rendered) > maximum:
            return f"{rendered[:maximum]}... [truncated {len(rendered) - maximum} chars]"
    return value


def _is_content_key(key: str) -> bool:
    return key in CONTENT_KEYS or key.startswith(CONTENT_PREFIXES)


def _strip_operation_prefix(name: str, operation: str) -> str | None:
    if name.startswith(f"{operation} "):
        return name[len(operation) + 1 :].strip() or None
    return name or None


def _infer_provider(model: str | None) -> str | None:
    lowered = (model or "").lower()
    if lowered.startswith("claude") or "anthropic." in lowered:
        return "anthropic"
    if lowered.startswith(("gpt-", "o1", "o3", "o4", "chatgpt", "text-embedding")):
        return "openai"
    if lowered.startswith(("gemini", "models/gemini")):
        return "gemini"
    return None


def _doc_id(document: JsonValue) -> str | None:
    if isinstance(document, dict):
        value = document.get("id") or document.get("document_id") or document.get("chunk_id")
        return str(value) if value is not None else None
    return None
