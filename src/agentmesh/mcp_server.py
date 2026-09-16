"""Model Context Protocol server for AgentMesh traces.

Lets a coding agent (Claude Code, Cursor, VS Code, ...) debug your agents:
"why did the last support-bot run fail?", "which model call was most expensive
today?", "is my planner looping?". Runs over stdio with no extra dependencies:

    agentmesh mcp --db .agentmesh/agentmesh.db

Claude Code:  claude mcp add agentmesh -- agentmesh mcp --db /abs/path/agentmesh.db
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, BinaryIO

from agentmesh.analysis import span_label, trace_insights
from agentmesh.types import JsonObject

SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INSTRUCTIONS = (
    "AgentMesh stores traces of AI agent runs. Start with list_traces (filter status='failed' to find problems), "
    "then get_trace for the span tree and diagnose_trace for root cause, loops, context growth, and cost hotspots. "
    "Use get_span to read the full prompt/response of one step."
)

ToolHandler = Callable[[JsonObject], Any]


class AgentMeshMCPServer:
    def __init__(self, store: Any) -> None:
        from agentmesh import __version__

        self.store = store
        self.version = __version__
        self.tools: dict[str, tuple[JsonObject, ToolHandler]] = {}
        self._register_tools()

    # -- protocol -----------------------------------------------------------
    def handle(self, message: Any) -> JsonObject | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Invalid Request")
        method = message.get("method")
        request_id = message.get("id")
        is_notification = "id" not in message
        if not isinstance(method, str):
            return None if is_notification else _error(request_id, -32600, "Invalid Request")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        try:
            if method == "initialize":
                result: Any = self._initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [definition for definition, _handler in self.tools.values()]}
            elif method == "tools/call":
                result = self._call_tool(params)
            elif method in {"resources/list", "prompts/list"}:
                result = {method.split("/")[0]: []}
            elif method.startswith("notifications/"):
                return None
            else:
                return None if is_notification else _error(request_id, -32601, f"Method not found: {method}")
        except _InvalidParams as exc:
            return None if is_notification else _error(request_id, -32602, str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return None if is_notification else _error(request_id, -32603, f"Internal error: {exc}")
        return None if is_notification else {"jsonrpc": "2.0", "id": request_id, "result": result}

    def serve_stdio(self, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> None:
        reader = stdin or sys.stdin.buffer
        writer = stdout or sys.stdout.buffer
        for raw_line in reader:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._write(writer, _error(None, -32700, "Parse error"))
                continue
            if isinstance(message, list):
                responses = [response for item in message if (response := self.handle(item)) is not None]
                if responses:
                    self._write(writer, responses)
                continue
            response = self.handle(message)
            if response is not None:
                self._write(writer, response)

    def _write(self, writer: BinaryIO, payload: Any) -> None:
        writer.write(json.dumps(payload, default=str).encode("utf-8") + b"\n")
        writer.flush()

    def _initialize(self, params: JsonObject) -> JsonObject:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "agentmesh", "title": "AgentMesh traces", "version": self.version},
            "instructions": SERVER_INSTRUCTIONS,
        }

    def _call_tool(self, params: JsonObject) -> JsonObject:
        name = params.get("name")
        if name not in self.tools:
            raise _InvalidParams(f"Unknown tool: {name}")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        _definition, handler = self.tools[str(name)]
        try:
            payload = handler(arguments)
        except _ToolError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except Exception as exc:
            return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(payload, indent=1, default=str)}], "isError": False}

    # -- tools ------------------------------------------------------------------
    def _register_tools(self) -> None:
        read_only = {"readOnlyHint": True, "openWorldHint": False}
        self._tool(
            "list_traces",
            "List recent agent traces (newest first) with status, duration, tokens, cost, session, and error summary.",
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                "status": {"type": "string", "enum": ["succeeded", "failed", "running", "cancelled"]},
                "workflow": {"type": "string", "description": "Substring match on workflow/trace name"},
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
                "query": {"type": "string", "description": "Free-text match on trace id, name, session, user"},
            },
            self._list_traces,
            annotations=read_only,
        )
        self._tool(
            "get_trace",
            "Get one trace as a compact span tree (name, type, status, duration, model, tokens, cost, errors). Set include_content to add truncated inputs/outputs.",
            {
                "trace_id": {"type": "string"},
                "include_content": {"type": "boolean", "default": False},
                "max_spans": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 300},
                "max_chars": {"type": "integer", "minimum": 50, "maximum": 20000, "default": 400},
            },
            self._get_trace,
            required=["trace_id"],
            annotations=read_only,
        )
        self._tool(
            "get_span",
            "Get the full detail of one span: prompt/messages, output, tool arguments/results, attributes, error.",
            {
                "trace_id": {"type": "string"},
                "span_id": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 100, "maximum": 100000, "default": 8000},
            },
            self._get_span,
            required=["trace_id", "span_id"],
            annotations=read_only,
        )
        self._tool(
            "diagnose_trace",
            "Automatic insights for a trace: first failure (root cause), tool-call loops, repeated prompts, context growth, cache usage, slowest spans, costliest calls.",
            {"trace_id": {"type": "string"}},
            lambda args: trace_insights(self.store, _required(args, "trace_id")),
            required=["trace_id"],
            annotations=read_only,
        )
        self._tool(
            "search_spans",
            "Search spans across all traces by text (span name, error message, tool, model, agent) and/or status.",
            {
                "query": {"type": "string"},
                "status": {"type": "string", "enum": ["succeeded", "failed", "running"]},
                "category": {
                    "type": "string",
                    "enum": ["model", "tool", "agent", "task", "rag", "memory", "llm", "retrieval"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
            },
            self._search_spans,
            annotations=read_only,
        )
        self._tool(
            "cost_summary",
            "Token and cost totals, optionally broken down by model, provider, agent, or workflow.",
            {"group_by": {"type": "string", "enum": ["model", "provider", "agent", "workflow"]}},
            self._cost_summary,
            annotations=read_only,
        )
        self._tool(
            "list_sessions",
            "List multi-turn sessions/conversations (grouped traces) with trace counts, failures, and cost.",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}, "user_id": {"type": "string"}},
            lambda args: self._require("list_sessions")(limit=int(args.get("limit", 20)), user_id=args.get("user_id")),
            annotations=read_only,
        )
        self._tool(
            "get_session",
            "Get all traces in a session in chronological order, with inputs/outputs and scores.",
            {"session_id": {"type": "string"}},
            self._get_session,
            required=["session_id"],
            annotations=read_only,
        )
        self._tool(
            "list_experiments",
            "List experiments (a task run over a dataset and scored by evaluators), newest first, with mean scores and error counts.",
            {"dataset": {"type": "string", "description": "Dataset name or id"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}},
            lambda args: self._require("list_experiments")(dataset=args.get("dataset"), limit=int(args.get("limit", 20))),
            annotations=read_only,
        )
        self._tool(
            "compare_experiments",
            "Compare two experiments item by item: which dataset items regressed or improved, score deltas, and cost change. "
            "Use before shipping a prompt or model change.",
            {"base": {"type": "string", "description": "Baseline experiment id"}, "candidate": {"type": "string", "description": "Candidate experiment id"}},
            self._compare_experiments,
            required=["base", "candidate"],
            annotations=read_only,
        )
        self._tool(
            "list_alerts",
            "Alert rules with their current state (firing/ok) and the most recent alert notifications.",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}},
            lambda args: {
                "rules": self._require("list_alert_rules")(),
                "recent": self._require("list_alert_events")(limit=int(args.get("limit", 20))),
            },
            annotations=read_only,
        )
        self._tool(
            "list_access",
            "What agents reached: outbound hosts (egress) and the data they read or wrote (retrievals, memory, databases, files), with how often and by how many agents. Use it to answer 'did anything talk to an unexpected domain?'.",
            {
                "kind": {"type": "string", "enum": ["network", "retrieval", "memory", "db", "file", "api", "other"]},
                "hours": {"type": "number", "description": "Only the last N hours; destinations first seen in the window are flagged is_new"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            self._list_access,
            annotations=read_only,
        )
        self._tool(
            "list_swarms",
            "Agent swarms (many agents working as one run, often across traces): status, agent count, failed agents, calls, tokens, and cost.",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}, "query": {"type": "string", "description": "Match swarm id, name, or service"}},
            lambda args: self._require("list_swarms")(limit=int(args.get("limit", 20)), query=args.get("query")),
            annotations=read_only,
        )
        self._tool(
            "get_swarm",
            "One swarm: summary (agents, depth, fan-out, cost, errors), roles with their spawn/message edges, and insights such as failed agents or runaway fan-out. Use get_trace on an agent's trace_id for details.",
            {"swarm_id": {"type": "string"}, "include_agents": {"type": "boolean", "default": False, "description": "Also return up to 200 individual agents"}},
            self._get_swarm,
            required=["swarm_id"],
            annotations=read_only,
        )
        self._tool(
            "add_score",
            "Attach a score or feedback to a trace (e.g. after reviewing it): numeric value, boolean, or label, plus a comment.",
            {
                "trace_id": {"type": "string"},
                "name": {"type": "string", "description": "Score name, e.g. 'correctness' or 'reviewer_verdict'"},
                "value": {"type": ["number", "boolean", "string"]},
                "comment": {"type": "string"},
                "span_id": {"type": "string"},
            },
            lambda args: self._require("save_score")({**args, "source": "mcp"}),
            required=["trace_id", "name", "value"],
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": False,
            },
        )

    def _tool(
        self,
        name: str,
        description: str,
        properties: JsonObject,
        handler: ToolHandler,
        required: list[str] | None = None,
        annotations: JsonObject | None = None,
    ) -> None:
        schema: JsonObject = {"type": "object", "properties": properties, "additionalProperties": False}
        if required:
            schema["required"] = required
        definition: JsonObject = {"name": name, "description": description, "inputSchema": schema}
        if annotations:
            definition["annotations"] = annotations
        self.tools[name] = (definition, handler)

    def _require(self, method: str) -> Callable[..., Any]:
        function = getattr(self.store, method, None)
        if function is None:
            raise _ToolError(f"The configured store does not support {method}; use an AgentMesh SQLite or PostgreSQL store.")
        return function

    def _list_access(self, args: JsonObject) -> JsonObject:
        from datetime import UTC, datetime, timedelta

        hours = args.get("hours")
        since = (datetime.now(UTC) - timedelta(hours=float(hours))).isoformat() if hours else None
        return {"destinations": self._require("access_summary")(since=since, limit=int(args.get("limit", 50)), kind=args.get("kind"))}

    def _get_swarm(self, args: JsonObject) -> JsonObject:
        detail = self._require("get_swarm")(_required(args, "swarm_id"))
        if detail is None:
            raise _ToolError(f"Swarm not found: {args['swarm_id']}")
        result = {key: detail[key] for key in ("swarm_id", "name", "service_name", "summary", "roles", "insights")}
        if args.get("include_agents"):
            result["agents"] = [
                {key: node[key] for key in ("key", "name", "kind", "status", "trace_id", "depth", "children", "llm_calls", "tool_calls", "cost", "error_message")}
                for node in detail["nodes"][:200]
            ]
        return result

    def _list_traces(self, args: JsonObject) -> JsonObject:
        filters = {
            "status": args.get("status"),
            "workflow": args.get("workflow"),
            "session_id": args.get("session_id"),
            "user_id": args.get("user_id"),
            "q": args.get("query"),
        }
        rows = self._require("list_observable_traces")(
            int(args.get("limit", 20)), {key: value for key, value in filters.items() if value}
        )
        return {
            "traces": [
                {
                    "trace_id": row.get("trace_id"),
                    "name": row.get("workflow_name"),
                    "status": row.get("status"),
                    "started_at": row.get("started_at"),
                    "duration_ms": row.get("duration_ms"),
                    "spans": row.get("span_count"),
                    "total_tokens": row.get("total_tokens"),
                    "estimated_cost": row.get("estimated_cost"),
                    "session_id": row.get("session_id"),
                    "user_id": row.get("user_id"),
                    "error": row.get("error_message"),
                }
                for row in rows
            ]
        }

    def _get_trace(self, args: JsonObject) -> JsonObject:
        trace_id = _required(args, "trace_id")
        trace = self._require("get_observable_trace")(trace_id)
        if trace is None:
            raise _ToolError(f"Trace not found: {trace_id}")
        spans = self._require("list_spans")(trace_id)
        max_spans = int(args.get("max_spans", 300))
        max_chars = int(args.get("max_chars", 400))
        include_content = bool(args.get("include_content", False))
        depth = _depths(spans)
        tree = []
        for span in spans[:max_spans]:
            node = {
                "span_id": span.get("span_id"),
                "parent_span_id": span.get("parent_span_id"),
                "depth": depth.get(str(span.get("span_id")), 0),
                "name": span_label(span),
                "type": span.get("event_type"),
                "status": span.get("status"),
                "duration_ms": span.get("duration_ms"),
            }
            for key in ("agent_name", "model", "tool_name", "error_type", "error_message"):
                if span.get(key):
                    node[key] = span[key]
            if span.get("total_tokens"):
                node["tokens"] = span["total_tokens"]
            if span.get("estimated_cost"):
                node["cost"] = span["estimated_cost"]
            if include_content:
                node["input"] = _truncate(span.get("input"), max_chars)
                node["output"] = _truncate(span.get("output"), max_chars)
            tree.append(node)
        return {
            "trace": {
                key: trace.get(key)
                for key in (
                    "trace_id",
                    "workflow_name",
                    "status",
                    "started_at",
                    "ended_at",
                    "duration_ms",
                    "total_tokens",
                    "estimated_cost",
                    "session_id",
                    "user_id",
                    "tags",
                    "error_type",
                    "error_message",
                    "source",
                )
            },
            "input": _truncate(trace.get("input"), max_chars * 4),
            "output": _truncate(trace.get("output"), max_chars * 4),
            "span_count": len(spans),
            "spans_truncated": len(spans) > max_spans,
            "spans": tree,
        }

    def _get_span(self, args: JsonObject) -> JsonObject:
        trace_id = _required(args, "trace_id")
        span_id = _required(args, "span_id")
        max_chars = int(args.get("max_chars", 8000))
        span = next((item for item in self._require("list_spans")(trace_id) if item.get("span_id") == span_id), None)
        if span is None:
            raise _ToolError(f"Span {span_id} not found in trace {trace_id}")
        detail = {key: value for key, value in span.items() if key not in {"input", "output", "metadata"}}
        detail["input"] = _truncate(span.get("input"), max_chars)
        detail["output"] = _truncate(span.get("output"), max_chars)
        detail["metadata"] = _truncate(span.get("metadata"), max_chars)
        model_call = next(
            (call for call in self._require("list_model_calls")(trace_id, 5000) if call.get("span_id") == span_id), None
        )
        if model_call is not None:
            detail["model_call"] = {
                "prompt": _truncate(model_call.get("prompt"), max_chars),
                "output": _truncate(model_call.get("output"), max_chars),
                "cost_status": model_call.get("cost_status"),
                "cached_tokens": model_call.get("cached_tokens"),
                "reasoning_tokens": model_call.get("reasoning_tokens"),
            }
        return detail

    def _search_spans(self, args: JsonObject) -> JsonObject:
        category = args.get("category")
        category = {"llm": "model", "retrieval": "rag"}.get(str(category), category) if category else None
        rows = self._require("search_spans")(
            args.get("query"), args.get("status"), category, int(args.get("limit", 25))
        )
        return {
            "spans": [
                {
                    "trace_id": row.get("trace_id"),
                    "span_id": row.get("span_id"),
                    "name": span_label(row),
                    "type": row.get("event_type"),
                    "status": row.get("status"),
                    "started_at": row.get("started_at"),
                    "duration_ms": row.get("duration_ms"),
                    "workflow": row.get("workflow_name"),
                    "agent": row.get("agent_name"),
                    "model": row.get("model"),
                    "tool": row.get("tool_name"),
                    "error": row.get("error_message"),
                }
                for row in rows
            ]
        }

    def _cost_summary(self, args: JsonObject) -> JsonObject:
        summary = self._require("cost_summary")()
        result: JsonObject = {
            key: summary.get(key)
            for key in (
                "total_cost",
                "total_tokens",
                "token_split",
                "cost_status_counts",
                "cost_wasted_on_failed_runs",
                "cost_per_successful_run",
            )
        }
        group_by = args.get("group_by")
        if group_by:
            result["breakdown"] = self._require("cost_by_dimension")(str(group_by))
        return result

    def _compare_experiments(self, args: JsonObject) -> JsonObject:
        base, candidate = _required(args, "base"), _required(args, "candidate")
        comparison = self._require("compare_experiments")(base, candidate)
        if comparison is None:
            raise _ToolError(f"Experiment not found: {base} or {candidate}")
        changed = [item for item in comparison["items"] if item["change"] != "unchanged"]
        for item in changed:
            item["input"] = _truncate(item.get("input"), 800)
            for side in ("base", "candidate"):
                if item.get(side):
                    item[side]["output"] = _truncate(item[side].get("output"), 800)
        return {
            "base": comparison["base"]["name"],
            "candidate": comparison["candidate"]["name"],
            "counts": comparison["counts"],
            "score_deltas": comparison["score_deltas"],
            "cost_delta": comparison["cost_delta"],
            "changed_items": changed[:50],
        }

    def _get_session(self, args: JsonObject) -> JsonObject:
        session_id = _required(args, "session_id")
        session = self._require("get_session")(session_id)
        if session is None:
            raise _ToolError(f"Session not found: {session_id}")
        session["traces"] = [
            {
                "trace_id": trace.get("trace_id"),
                "name": trace.get("workflow_name"),
                "status": trace.get("status"),
                "started_at": trace.get("started_at"),
                "input": _truncate(trace.get("input"), 1500),
                "output": _truncate(trace.get("output"), 1500),
                "estimated_cost": trace.get("estimated_cost"),
                "error": trace.get("error_message"),
            }
            for trace in session.get("traces", [])
        ]
        return session


class _InvalidParams(ValueError):
    pass


class _ToolError(RuntimeError):
    pass


def _required(args: JsonObject, key: str) -> str:
    value = args.get(key)
    if not value:
        raise _ToolError(f"Missing required argument: {key}")
    return str(value)


def _error(request_id: Any, code: int, message: str) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _truncate(value: Any, limit: int) -> Any:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    return f"{text[:limit]}... [{len(text) - limit} more chars; use get_span with a larger max_chars]"


def _depths(spans: list[JsonObject]) -> dict[str, int]:
    parents = {str(span.get("span_id")): span.get("parent_span_id") for span in spans}
    depths: dict[str, int] = {}
    for span_id in parents:
        depth = 0
        cursor = parents.get(span_id)
        seen = {span_id}
        while cursor and str(cursor) in parents and str(cursor) not in seen and depth < 64:
            seen.add(str(cursor))
            depth += 1
            cursor = parents.get(str(cursor))
        depths[span_id] = depth
    return depths


def run_stdio_server(db_path: str) -> None:
    from agentmesh.stores import create_store

    AgentMeshMCPServer(create_store(db_path)).serve_stdio()
