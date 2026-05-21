from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from agentmesh.types import JsonObject, JsonValue, dumps_json, has_redactions, loads_json, redact_secrets, safe_json, utc_now


PROVIDER_CATALOG = [
    ("openai-compatible", "OpenAI-compatible", "not_configured"),
    ("ollama", "Ollama", "not_configured"),
    ("anthropic", "Anthropic", "planned"),
    ("gemini", "Gemini", "planned"),
    ("azure-openai", "Azure OpenAI", "planned"),
    ("vllm", "vLLM", "planned"),
    ("mock", "Mock provider", "healthy"),
]


def install_schema(conn: sqlite3.Connection) -> None:
    statements = [
        """
        create table if not exists schema_migrations (
          version integer primary key,
          name text not null,
          applied_at text not null
        )
        """,
        """
        create table if not exists workflows_catalog (
          workflow_id text primary key,
          workflow_name text not null unique,
          created_at text not null,
          updated_at text not null,
          metadata_json text not null
        )
        """,
        """
        create table if not exists traces (
          trace_id text primary key,
          run_id text not null,
          workflow_id text,
          workflow_name text,
          status text not null,
          started_at text not null,
          ended_at text,
          duration_ms real,
          environment text not null default 'local',
          is_demo integer not null default 0,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_traces_status_time on traces(status, started_at)",
        "create index if not exists idx_traces_environment on traces(environment, is_demo, started_at)",
        """
        create table if not exists workflow_runs (
          run_id text primary key,
          trace_id text not null unique,
          workflow_id text not null,
          workflow_name text not null,
          status text not null,
          started_at text not null,
          ended_at text,
          duration_ms real,
          input_json text,
          output_json text,
          error_type text,
          error_message text,
          environment text not null default 'local',
          is_demo integer not null default 0,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_workflow_runs_status_time on workflow_runs(status, started_at)",
        """
        create table if not exists agents (
          agent_id text primary key,
          agent_name text not null unique,
          role text,
          instructions text,
          provider text,
          model text,
          status text not null,
          current_task text,
          created_at text not null,
          updated_at text not null,
          metadata_json text not null
        )
        """,
        """
        create table if not exists tasks (
          task_id text primary key,
          trace_id text not null,
          workflow_id text,
          agent_id text,
          agent_name text,
          task_name text,
          status text not null,
          started_at text not null,
          ended_at text,
          duration_ms real,
          retry_count integer not null default 0,
          input_json text,
          output_json text,
          error_type text,
          error_message text,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_tasks_trace on tasks(trace_id, started_at)",
        """
        create table if not exists spans (
          span_id text primary key,
          trace_id text not null,
          run_id text,
          workflow_id text,
          workflow_name text,
          parent_span_id text,
          agent_id text,
          agent_name text,
          task_id text,
          task_name text,
          event_type text not null,
          status text not null,
          started_at text not null,
          ended_at text,
          duration_ms real,
          input_json text,
          output_json text,
          error_type text,
          error_message text,
          retry_count integer not null default 0,
          provider text,
          model text,
          prompt_tokens integer not null default 0,
          completion_tokens integer not null default 0,
          cached_tokens integer not null default 0,
          reasoning_tokens integer not null default 0,
          total_tokens integer not null default 0,
          estimated_cost real not null default 0,
          temperature real,
          top_p real,
          max_tokens integer,
          prompt_version text,
          tool_name text,
          memory_operation text,
          rag_document_ids_json text not null,
          environment text not null default 'local',
          is_demo integer not null default 0,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_spans_trace_time on spans(trace_id, started_at)",
        "create index if not exists idx_spans_filters on spans(agent_name, provider, model, tool_name, status)",
        "create index if not exists idx_spans_parent on spans(parent_span_id)",
        "create index if not exists idx_spans_error on spans(error_type)",
        """
        create table if not exists model_calls (
          model_call_id text primary key,
          trace_id text not null,
          span_id text not null,
          parent_span_id text,
          agent_id text,
          agent_name text,
          task_id text,
          task_name text,
          provider text,
          model text,
          endpoint_alias text,
          status text not null,
          started_at text not null,
          ended_at text,
          duration_ms real,
          prompt_version text,
          prompt_json text,
          output_json text,
          prompt_tokens integer not null default 0,
          completion_tokens integer not null default 0,
          cached_tokens integer not null default 0,
          reasoning_tokens integer not null default 0,
          total_tokens integer not null default 0,
          estimated_cost real not null default 0,
          cost_status text not null default 'unknown',
          cost_source text,
          temperature real,
          top_p real,
          max_tokens integer,
          context_window integer,
          error_type text,
          error_message text,
          request_id text,
          retry_count integer not null default 0,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_model_calls_trace_time on model_calls(trace_id, started_at)",
        "create index if not exists idx_model_calls_provider_model on model_calls(provider, model)",
        """
        create table if not exists tool_calls (
          tool_call_id text primary key,
          trace_id text not null,
          span_id text not null,
          parent_span_id text,
          agent_id text,
          agent_name text,
          tool_name text not null,
          tool_type text not null,
          status text not null,
          started_at text not null,
          ended_at text,
          duration_ms real,
          permission_level text,
          approval_status text,
          risk_level text,
          retry_count integer not null default 0,
          side_effect integer not null default 0,
          input_json text,
          output_json text,
          stdout text,
          stderr text,
          error_type text,
          error_message text,
          sandbox_logs_json text not null,
          mcp_metadata_json text not null,
          side_effects_json text not null,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_tool_calls_trace_time on tool_calls(trace_id, started_at)",
        """
        create table if not exists memory_operations (
          operation_id text primary key,
          trace_id text not null,
          span_id text not null,
          agent_id text,
          agent_name text,
          memory_type text not null,
          operation text not null,
          key text,
          value_preview text,
          value_json text,
          version integer,
          redacted integer not null default 0,
          timestamp text not null,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_memory_operations_trace_time on memory_operations(trace_id, timestamp)",
        """
        create table if not exists rag_retrievals (
          retrieval_id text primary key,
          trace_id text not null,
          span_id text not null,
          agent_id text,
          agent_name text,
          query text,
          embedding_model text,
          vector_store text,
          retrieved_documents_json text not null,
          chunk_ids_json text not null,
          chunk_preview text,
          scores_json text not null,
          source_metadata_json text not null,
          used_in_answer integer not null default 0,
          citation_mapping_json text not null,
          timestamp text not null,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_rag_retrievals_trace_time on rag_retrievals(trace_id, timestamp)",
        """
        create table if not exists cost_records (
          cost_record_id text primary key,
          trace_id text not null,
          workflow_id text,
          workflow_name text,
          agent_id text,
          agent_name text,
          provider text,
          model text,
          status text not null,
          prompt_tokens integer not null default 0,
          completion_tokens integer not null default 0,
          cached_tokens integer not null default 0,
          reasoning_tokens integer not null default 0,
          total_tokens integer not null default 0,
          estimated_cost real not null default 0,
          cost_status text not null default 'unknown',
          cost_source text,
          latency_ms real,
          timestamp text not null,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_cost_records_trace_time on cost_records(trace_id, timestamp)",
        "create index if not exists idx_cost_records_dims on cost_records(workflow_name, agent_name, provider, model)",
        "create index if not exists idx_cost_records_status on cost_records(status, provider, model)",
        """
        create table if not exists provider_health (
          provider text primary key,
          display_name text not null,
          status text not null,
          calls integer not null default 0,
          tokens integer not null default 0,
          cost_usd real not null default 0,
          avg_latency_ms real not null default 0,
          p95_latency_ms real not null default 0,
          error_count integer not null default 0,
          error_rate real not null default 0,
          rate_limit_events integer not null default 0,
          fallback_count integer not null default 0,
          last_error text,
          updated_at text not null,
          metadata_json text not null
        )
        """,
        """
        create table if not exists evaluations (
          evaluation_id text primary key,
          trace_id text,
          workflow_id text,
          workflow_name text,
          agent_id text,
          agent_name text,
          evaluator text not null,
          evaluator_type text not null,
          status text not null,
          score real,
          human_rating real,
          passed integer,
          expected_json text,
          actual_json text,
          findings_json text not null,
          created_at text not null,
          metadata_json text not null
        )
        """,
        """
        create table if not exists budget_settings (
          scope text not null,
          scope_id text not null,
          daily_budget real,
          monthly_budget real,
          workflow_budget real,
          agent_budget real,
          max_tokens_per_run integer,
          max_cost_per_run real,
          updated_at text not null,
          primary key(scope, scope_id)
        )
        """,
        """
        create table if not exists replay_runs (
          replay_id text primary key,
          source_trace_id text not null,
          source_span_id text,
          mode text not null,
          status text not null,
          created_at text not null,
          completed_at text,
          result_json text not null,
          metadata_json text not null
        )
        """,
        """
        create table if not exists replay_checkpoints (
          checkpoint_id text primary key,
          trace_id text not null,
          span_id text,
          step_id text,
          checkpoint_type text not null,
          created_at text not null,
          metadata_json text not null
        )
        """,
        "create index if not exists idx_replay_checkpoints_trace on replay_checkpoints(trace_id, created_at)",
    ]
    for statement in statements:
        conn.execute(statement)
    _apply_lightweight_migrations(conn)
    now = utc_now()
    for provider, display_name, status in PROVIDER_CATALOG:
        conn.execute(
            """
            insert or ignore into provider_health
            (provider, display_name, status, updated_at, metadata_json)
            values (?, ?, ?, ?, ?)
            """,
            (provider, display_name, status, now, dumps_json({"placeholder": status != "healthy"})),
        )
    conn.execute(
        """
        insert or ignore into budget_settings
        (scope, scope_id, daily_budget, monthly_budget, max_tokens_per_run, max_cost_per_run, updated_at)
        values ('workspace', 'default', 25.0, 500.0, 100000, 25.0, ?)
        """,
        (now,),
    )
    conn.execute(
        "insert or ignore into schema_migrations (version, name, applied_at) values (1, 'initial_observability_schema', ?)",
        (now,),
    )


def _apply_lightweight_migrations(conn: sqlite3.Connection) -> None:
    migrations: dict[str, dict[str, str]] = {
        "workflow_runs": {
            "environment": "text not null default 'local'",
            "is_demo": "integer not null default 0",
        },
        "spans": {
            "environment": "text not null default 'local'",
            "is_demo": "integer not null default 0",
        },
        "model_calls": {
            "cost_status": "text not null default 'unknown'",
            "cost_source": "text",
            "request_id": "text",
            "retry_count": "integer not null default 0",
        },
        "cost_records": {
            "cost_status": "text not null default 'unknown'",
            "cost_source": "text",
        },
    }
    for table, columns in migrations.items():
        existing = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"alter table {table} add column {column} {definition}")


def materialize_workflow_created(conn: sqlite3.Connection, trace_id: str, name: str, input_value: JsonValue) -> None:
    now = utc_now()
    workflow_id = _workflow_id(name)
    environment = _environment(input_value)
    is_demo = 1 if _is_demo(input_value) else 0
    conn.execute(
        """
        insert into workflows_catalog (workflow_id, workflow_name, created_at, updated_at, metadata_json)
        values (?, ?, ?, ?, ?)
        on conflict(workflow_id) do update set updated_at = excluded.updated_at
        """,
        (workflow_id, name, now, now, dumps_json({})),
    )
    conn.execute(
        """
        insert or replace into workflow_runs
        (run_id, trace_id, workflow_id, workflow_name, status, started_at, ended_at, duration_ms, input_json, output_json,
         error_type, error_message, environment, is_demo, metadata_json)
        values (?, ?, ?, ?, 'running', ?, null, null, ?, null, null, null, ?, ?, ?)
        """,
        (
            trace_id,
            trace_id,
            workflow_id,
            name,
            now,
            dumps_json(input_value),
            environment,
            is_demo,
            dumps_json({"demo": bool(is_demo), "environment": environment}),
        ),
    )
    conn.execute(
        """
        insert or replace into traces
        (trace_id, run_id, workflow_id, workflow_name, status, started_at, ended_at, duration_ms, environment, is_demo, metadata_json)
        values (?, ?, ?, ?, 'running', ?, null, null, ?, ?, ?)
        """,
        (trace_id, trace_id, workflow_id, name, now, environment, is_demo, dumps_json({"demo": bool(is_demo)})),
    )


def materialize_workflow_finished(
    conn: sqlite3.Connection,
    trace_id: str,
    status: str,
    output_value: JsonValue | None,
    error_value: JsonValue | None,
) -> None:
    now = utc_now()
    error = error_value if isinstance(error_value, dict) else {}
    started = conn.execute("select started_at from workflow_runs where trace_id = ?", (trace_id,)).fetchone()
    duration = _duration_ms(started["started_at"], now) if started else None
    conn.execute(
        """
        update workflow_runs
        set status = ?, ended_at = ?, duration_ms = ?, output_json = ?, error_type = ?, error_message = ?
        where trace_id = ?
        """,
        (
            status,
            now,
            duration,
            dumps_json(output_value),
            _string(error.get("kind") or error.get("error_type")),
            _string(error.get("message") or error.get("error_message")),
            trace_id,
        ),
    )
    conn.execute(
        """
        update traces
        set status = ?, ended_at = ?, duration_ms = ?
        where trace_id = ?
        """,
        (status, now, duration, trace_id),
    )


def materialize_event(conn: sqlite3.Connection, event: Any) -> None:
    safe_payload = redact_secrets(safe_json(event.payload))
    payload = safe_payload if isinstance(safe_payload, dict) else {}
    workflow = _workflow_for_trace(conn, event.trace_id)
    environment = str(workflow.get("environment") or "local")
    is_demo = 1 if workflow.get("is_demo") else 0
    agent_name = _agent_name(event.actor)
    agent_id = _agent_id(agent_name) if agent_name else None
    task = _extract_task(payload)
    metadata_value = payload.get("metadata", {})
    metadata_obj = metadata_value if isinstance(metadata_value, dict) else {}
    task_id = _string(payload.get("task_id") or metadata_obj.get("task_id") or task.get("id") or task.get("task_id"))
    task_name = _string(payload.get("task_name") or task.get("description") or payload.get("task"))
    status = _status_from_event(event.event_type, payload)
    error = _extract_error(payload)
    prompt_tokens = _int(payload.get("prompt_tokens"))
    completion_tokens = _int(payload.get("completion_tokens"))
    cached_tokens = _int(payload.get("cached_tokens"))
    reasoning_tokens = _int(payload.get("reasoning_tokens"))
    total_tokens = _int(payload.get("total_tokens")) or prompt_tokens + completion_tokens + cached_tokens + reasoning_tokens
    cost = _float(payload.get("estimated_cost") or payload.get("cost_usd"))
    latency_ms = _float(payload.get("latency_ms") or payload.get("duration_ms")) or None
    provider = _string(payload.get("provider"))
    model = _string(payload.get("model"))
    tool_payload = payload.get("tool", {})
    tool_name = _string(payload.get("tool_name") or (payload.get("tool") if isinstance(payload.get("tool"), str) else None))
    if isinstance(tool_payload, dict):
        tool_name = tool_name or _string(tool_payload.get("name"))
    memory_operation = _memory_operation(event.event_type, payload)
    rag_doc_ids = _rag_doc_ids(payload)
    metadata = _span_metadata(payload)
    conn.execute(
        """
        insert or replace into spans
        (span_id, trace_id, run_id, workflow_id, workflow_name, parent_span_id, agent_id, agent_name, task_id, task_name,
         event_type, status, started_at, ended_at, duration_ms, input_json, output_json, error_type, error_message,
         retry_count, provider, model, prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, total_tokens,
         estimated_cost, temperature, top_p, max_tokens, prompt_version, tool_name, memory_operation, rag_document_ids_json,
         environment, is_demo, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.span_id,
            event.trace_id,
            event.trace_id,
            workflow["workflow_id"],
            workflow["workflow_name"],
            event.parent_span_id,
            agent_id,
            agent_name,
            task_id,
            task_name,
            event.event_type,
            status,
            event.timestamp,
            event.timestamp if status in {"succeeded", "failed", "cancelled"} else None,
            latency_ms,
            dumps_json(_input_payload(event.event_type, payload)),
            dumps_json(_output_payload(event.event_type, payload)),
            error["type"],
            error["message"],
            _int(payload.get("retry_count") or payload.get("attempt")) - 1 if _int(payload.get("attempt")) > 1 else _int(payload.get("retry_count")),
            provider,
            model,
            prompt_tokens,
            completion_tokens,
            cached_tokens,
            reasoning_tokens,
            total_tokens,
            cost,
            _float_or_none(payload.get("temperature")),
            _float_or_none(payload.get("top_p")),
            _int_or_none(payload.get("max_tokens")),
            _string(payload.get("prompt_version") or payload.get("prompt_id")),
            tool_name,
            memory_operation,
            dumps_json(rag_doc_ids),
            environment,
            is_demo,
            dumps_json(metadata),
        ),
    )
    if event.event_type.startswith("agent."):
        _materialize_agent(conn, event, payload, agent_id, agent_name, provider, model, status, task_name)
    if event.event_type.startswith("task."):
        _materialize_task(conn, event, payload, workflow, agent_id, agent_name, task_id, task_name, status, error)
    if event.event_type.startswith("model."):
        _materialize_model_event(conn, event, payload, workflow, agent_id, agent_name, task_id, task_name, status, error)
    if event.event_type.startswith("tool."):
        _materialize_tool_event(conn, event, payload, agent_id, agent_name, status, error)
    if event.event_type.startswith("memory."):
        _materialize_memory_operation(conn, event, payload, agent_id, agent_name)
    if event.event_type.startswith("rag."):
        _materialize_rag_retrieval(conn, event, payload, agent_id, agent_name)
    if event.event_type == "checkpoint.saved":
        _materialize_replay_checkpoint(conn, event, payload)
    if event.event_type.startswith(("approval.", "tool.", "model.", "workflow.", "prompt.")):
        _audit_signal(conn, event, payload)
    if has_redactions(payload):
        conn.execute(
            """
            insert into audit_logs (trace_id, actor, action, resource, payload_json, timestamp)
            values (?, ?, 'secret.redacted', ?, ?, ?)
            """,
            (event.trace_id, event.actor, event.event_type, dumps_json({"redacted": True}), event.timestamp),
        )


def list_traces(
    conn: sqlite3.Connection,
    limit: int = 100,
    filters: dict[str, Any] | None = None,
    offset: int = 0,
) -> list[JsonObject]:
    filters = filters or {}
    limit = max(min(int(limit), 500), 1)
    offset = max(int(offset), 0)
    where: list[str] = []
    params: list[Any] = []
    if filters.get("status"):
        where.append("wr.status = ?")
        params.append(filters["status"])
    if filters.get("environment"):
        where.append("wr.environment = ?")
        params.append(filters["environment"])
    if filters.get("is_demo") is not None:
        value = str(filters["is_demo"]).lower()
        where.append("wr.is_demo = ?")
        params.append(1 if value in {"1", "true", "yes", "demo"} else 0)
    if filters.get("workflow"):
        where.append("wr.workflow_name like ?")
        params.append(f"%{filters['workflow']}%")
    if filters.get("agent"):
        where.append("exists (select 1 from spans s where s.trace_id = wr.trace_id and s.agent_name like ?)")
        params.append(f"%{filters['agent']}%")
    if filters.get("task"):
        where.append("exists (select 1 from spans s where s.trace_id = wr.trace_id and s.task_name like ?)")
        params.append(f"%{filters['task']}%")
    if filters.get("model"):
        where.append("exists (select 1 from model_calls mc where mc.trace_id = wr.trace_id and mc.model like ?)")
        params.append(f"%{filters['model']}%")
    if filters.get("provider"):
        where.append("exists (select 1 from model_calls mc where mc.trace_id = wr.trace_id and mc.provider = ?)")
        params.append(filters["provider"])
    if filters.get("tool"):
        where.append("exists (select 1 from tool_calls tc where tc.trace_id = wr.trace_id and tc.tool_name like ?)")
        params.append(f"%{filters['tool']}%")
    if filters.get("error_type"):
        where.append("wr.error_type = ?")
        params.append(filters["error_type"])
    if filters.get("start") or filters.get("started_after"):
        where.append("wr.started_at >= ?")
        params.append(filters.get("start") or filters.get("started_after"))
    if filters.get("end") or filters.get("started_before"):
        where.append("wr.started_at <= ?")
        params.append(filters.get("end") or filters.get("started_before"))
    if filters.get("q"):
        where.append("(wr.trace_id like ? or wr.workflow_name like ? or wr.status like ?)")
        q = f"%{filters['q']}%"
        params.extend([q, q, q])
    clause = f"where {' and '.join(where)}" if where else ""
    having: list[str] = []
    if filters.get("min_cost") is not None:
        having.append("estimated_cost >= ?")
        params.append(filters["min_cost"])
    if filters.get("max_cost") is not None:
        having.append("estimated_cost <= ?")
        params.append(filters["max_cost"])
    if filters.get("min_latency") is not None:
        having.append("max_latency_ms >= ?")
        params.append(filters["min_latency"])
    if filters.get("max_latency") is not None:
        having.append("max_latency_ms <= ?")
        params.append(filters["max_latency"])
    having_clause = f"having {' and '.join(having)}" if having else ""
    rows = conn.execute(
        f"""
        select wr.*, coalesce(sum(cr.total_tokens), 0) as total_tokens,
               coalesce(sum(cr.estimated_cost), 0) as estimated_cost,
               coalesce(max(cr.latency_ms), wr.duration_ms, 0) as max_latency_ms,
               (select count(*) from spans s where s.trace_id = wr.trace_id) as span_count
        from workflow_runs wr
        left join cost_records cr on cr.trace_id = wr.trace_id
        {clause}
        group by wr.trace_id
        {having_clause}
        order by wr.started_at desc
        limit ? offset ?
        """,
        (*params, limit, offset),
    ).fetchall()
    if not rows and not filters and offset == 0:
        return _legacy_trace_rows(conn, limit)
    return [_workflow_run_to_json(row) for row in rows]


def get_trace(conn: sqlite3.Connection, trace_id: str) -> JsonObject | None:
    row = conn.execute(
        """
        select wr.*, coalesce(sum(cr.total_tokens), 0) as total_tokens,
               coalesce(sum(cr.estimated_cost), 0) as estimated_cost,
               coalesce(max(cr.latency_ms), wr.duration_ms, 0) as max_latency_ms,
               (select count(*) from spans s where s.trace_id = wr.trace_id) as span_count
        from workflow_runs wr
        left join cost_records cr on cr.trace_id = wr.trace_id
        where wr.trace_id = ?
        group by wr.trace_id
        """,
        (trace_id,),
    ).fetchone()
    if row is None:
        return None
    return _workflow_run_to_json(row)


def list_spans(conn: sqlite3.Connection, trace_id: str) -> list[JsonObject]:
    rows = conn.execute(
        "select * from spans where trace_id = ? order by started_at asc, rowid asc",
        (trace_id,),
    ).fetchall()
    return [_span_to_json(row) for row in rows]


def list_model_calls(conn: sqlite3.Connection, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
    where = "where trace_id = ?" if trace_id else ""
    params: tuple[Any, ...] = (trace_id, limit) if trace_id else (limit,)
    rows = conn.execute(
        f"select * from model_calls {where} order by started_at desc limit ?",
        params,
    ).fetchall()
    return [_model_call_to_json(row) for row in rows]


def list_tool_calls(conn: sqlite3.Connection, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
    where = "where trace_id = ?" if trace_id else ""
    params: tuple[Any, ...] = (trace_id, limit) if trace_id else (limit,)
    rows = conn.execute(
        f"select * from tool_calls {where} order by started_at desc limit ?",
        params,
    ).fetchall()
    return [_tool_call_to_json(row) for row in rows]


def get_tool_call(conn: sqlite3.Connection, tool_call_id: str) -> JsonObject | None:
    row = conn.execute("select * from tool_calls where tool_call_id = ?", (tool_call_id,)).fetchone()
    return _tool_call_to_json(row) if row else None


def list_memory_operations(conn: sqlite3.Connection, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
    where = "where trace_id = ?" if trace_id else ""
    params: tuple[Any, ...] = (trace_id, limit) if trace_id else (limit,)
    rows = conn.execute(
        f"select * from memory_operations {where} order by timestamp desc limit ?",
        params,
    ).fetchall()
    return [_memory_operation_to_json(row) for row in rows]


def list_rag_retrievals(conn: sqlite3.Connection, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
    where = "where trace_id = ?" if trace_id else ""
    params: tuple[Any, ...] = (trace_id, limit) if trace_id else (limit,)
    rows = conn.execute(
        f"select * from rag_retrievals {where} order by timestamp desc limit ?",
        params,
    ).fetchall()
    return [_rag_retrieval_to_json(row) for row in rows]


def get_rag_retrieval(conn: sqlite3.Connection, retrieval_id: str) -> JsonObject | None:
    row = conn.execute("select * from rag_retrievals where retrieval_id = ?", (retrieval_id,)).fetchone()
    return _rag_retrieval_to_json(row) if row else None


def overview(conn: sqlite3.Connection) -> JsonObject:
    runs = conn.execute("select * from workflow_runs").fetchall()
    cost = conn.execute(
        """
        select coalesce(sum(total_tokens), 0) as tokens, coalesce(sum(estimated_cost), 0) as cost,
               coalesce(avg(latency_ms), 0) as avg_latency
        from cost_records
        """
    ).fetchone()
    pending = conn.execute("select count(*) as count from approvals where status = 'pending'").fetchone()["count"]
    providers = list_provider_health(conn)
    active = sum(1 for row in runs if row["status"] == "running")
    failed = sum(1 for row in runs if row["status"] == "failed")
    succeeded = sum(1 for row in runs if row["status"] == "succeeded")
    total = len(runs)
    budget = conn.execute("select * from budget_settings where scope = 'workspace' and scope_id = 'default'").fetchone()
    budget_used = _float(cost["cost"]) / max(_float(budget["monthly_budget"] if budget else 500.0), 1.0)
    return {
        "runs_today": total,
        "active_workflows": active,
        "success_rate": succeeded / total if total else 0,
        "failure_rate": failed / total if total else 0,
        "average_latency_ms": _float(cost["avg_latency"]),
        "total_tokens": _int(cost["tokens"]),
        "total_cost": _float(cost["cost"]),
        "pending_approvals": _int(pending),
        "provider_health": providers,
        "budget_used": min(budget_used, 1.0),
        "budget_remaining": max((_float(budget["monthly_budget"] if budget else 500.0) - _float(cost["cost"])), 0.0),
        "recent_traces": list_traces(conn, 8),
        "recent_failures": [item for item in list_traces(conn, 50) if item["status"] == "failed"][:5],
        "recent_approvals": list_approvals(conn, limit=5),
        "expensive_runs": cost_by_failed_run(conn)[:5],
        "slowest_runs": sorted(list_traces(conn, 50), key=lambda item: _float(item.get("duration_ms") or item.get("max_latency_ms")), reverse=True)[:5],
    }


def overview_timeseries(conn: sqlite3.Connection) -> JsonObject:
    rows = conn.execute(
        """
        select substr(wr.started_at, 1, 13) as bucket,
               count(distinct wr.trace_id) as runs,
               coalesce(sum(cr.estimated_cost), 0) as cost,
               coalesce(sum(cr.total_tokens), 0) as tokens,
               sum(case when wr.status = 'failed' then 1 else 0 end) as failures,
               coalesce(avg(cr.latency_ms), 0) as latency
        from workflow_runs wr
        left join cost_records cr on cr.trace_id = wr.trace_id
        group by bucket
        order by bucket asc
        limit 48
        """
    ).fetchall()
    return {"points": [_row_dict(row) for row in rows]}


def list_workflows(conn: sqlite3.Connection) -> list[JsonObject]:
    rows = conn.execute(
        """
        select wc.workflow_id, wc.workflow_name, wc.created_at, wc.updated_at,
               count(wr.run_id) as runs,
               sum(case when wr.status = 'running' then 1 else 0 end) as active_runs,
               sum(case when wr.status = 'failed' then 1 else 0 end) as failed_runs,
               coalesce(avg(wr.duration_ms), 0) as avg_latency_ms,
               coalesce(sum(cr.estimated_cost), 0) as total_cost,
               coalesce(sum(cr.total_tokens), 0) as total_tokens
        from workflows_catalog wc
        left join workflow_runs wr on wr.workflow_id = wc.workflow_id
        left join cost_records cr on cr.trace_id = wr.trace_id
        group by wc.workflow_id
        order by wc.updated_at desc
        """
    ).fetchall()
    return [_row_dict(row) for row in rows]


def get_workflow(conn: sqlite3.Connection, workflow_id: str) -> JsonObject | None:
    workflows = [item for item in list_workflows(conn) if item["workflow_id"] == workflow_id]
    return workflows[0] if workflows else None


def workflow_runs(conn: sqlite3.Connection, workflow_id: str) -> list[JsonObject]:
    rows = conn.execute(
        "select trace_id from workflow_runs where workflow_id = ? order by started_at desc limit 100",
        (workflow_id,),
    ).fetchall()
    return [get_trace(conn, row["trace_id"]) for row in rows if get_trace(conn, row["trace_id"]) is not None]


def workflow_graph(conn: sqlite3.Connection, workflow_id: str) -> JsonObject:
    run = conn.execute(
        "select trace_id from workflow_runs where workflow_id = ? order by started_at desc limit 1",
        (workflow_id,),
    ).fetchone()
    if run is None:
        return {"workflow_id": workflow_id, "nodes": [], "edges": []}
    spans = list_spans(conn, run["trace_id"])
    nodes: dict[str, JsonObject] = {}
    edges: list[JsonObject] = []
    for span in spans:
        node_id = str(span.get("span_id"))
        nodes[node_id] = {
            "id": node_id,
            "name": span.get("task_name") or span.get("tool_name") or span.get("model") or span.get("event_type"),
            "type": _node_type(str(span.get("event_type"))),
            "status": span.get("status"),
            "duration_ms": span.get("duration_ms"),
            "cost": span.get("estimated_cost"),
            "tokens": span.get("total_tokens"),
            "retry_count": span.get("retry_count"),
            "error": span.get("error_message"),
            "raw": span,
        }
        if span.get("parent_span_id"):
            edges.append({"source": span["parent_span_id"], "target": node_id})
    return {"workflow_id": workflow_id, "trace_id": run["trace_id"], "nodes": list(nodes.values()), "edges": edges}


def list_agents(conn: sqlite3.Connection) -> list[JsonObject]:
    rows = conn.execute(
        """
        select a.*, count(distinct mc.model_call_id) as model_calls,
               coalesce(sum(mc.total_tokens), 0) as total_tokens,
               coalesce(sum(mc.estimated_cost), 0) as total_cost,
               coalesce(avg(mc.duration_ms), 0) as avg_latency_ms,
               sum(case when mc.status = 'failed' then 1 else 0 end) as failures,
               count(distinct tc.tool_call_id) as tool_calls
        from agents a
        left join model_calls mc on mc.agent_id = a.agent_id
        left join tool_calls tc on tc.agent_id = a.agent_id
        group by a.agent_id
        order by a.updated_at desc
        """
    ).fetchall()
    return [_agent_to_json(row) for row in rows]


def get_agent(conn: sqlite3.Connection, agent_id: str) -> JsonObject | None:
    for item in list_agents(conn):
        if item["agent_id"] == agent_id:
            return item
    return None


def agent_runs(conn: sqlite3.Connection, agent_id: str) -> list[JsonObject]:
    rows = conn.execute(
        """
        select distinct wr.trace_id from workflow_runs wr
        join spans s on s.trace_id = wr.trace_id
        where s.agent_id = ?
        order by wr.started_at desc
        limit 100
        """,
        (agent_id,),
    ).fetchall()
    return [get_trace(conn, row["trace_id"]) for row in rows if get_trace(conn, row["trace_id"]) is not None]


def agent_messages(conn: sqlite3.Connection, agent_id: str) -> list[JsonObject]:
    rows = conn.execute(
        "select * from spans where agent_id = ? and event_type like 'agent.%' order by started_at desc limit 100",
        (agent_id,),
    ).fetchall()
    return [_span_to_json(row) for row in rows]


def list_provider_health(conn: sqlite3.Connection) -> list[JsonObject]:
    _refresh_provider_health(conn)
    rows = conn.execute("select * from provider_health order by provider asc").fetchall()
    return [_provider_to_json(row) for row in rows]


def list_models(conn: sqlite3.Connection) -> list[JsonObject]:
    rows = conn.execute(
        """
        select provider, model, coalesce(endpoint_alias, model) as endpoint_alias,
               count(*) as calls,
               sum(prompt_tokens) as prompt_tokens,
               sum(completion_tokens) as completion_tokens,
               sum(cached_tokens) as cached_tokens,
               sum(reasoning_tokens) as reasoning_tokens,
               sum(total_tokens) as total_tokens,
               sum(estimated_cost) as estimated_cost,
               avg(duration_ms) as avg_latency_ms,
               sum(case when status = 'failed' then 1 else 0 end) as errors,
               avg(temperature) as temperature,
               avg(top_p) as top_p,
               max(max_tokens) as max_tokens
        from model_calls
        group by provider, model, endpoint_alias
        order by estimated_cost desc
        """
    ).fetchall()
    models: list[JsonObject] = []
    for row in rows:
        calls = _int(row["calls"])
        errors = _int(row["errors"])
        models.append(
            {
                **_row_dict(row),
                "success_rate": (calls - errors) / calls if calls else 0,
                "error_rate": errors / calls if calls else 0,
                "p95_latency_ms": _p95_latency_for_model(conn, row["provider"], row["model"]),
                "context_window": _context_window(str(row["model"])),
            }
        )
    return models


def cost_summary(conn: sqlite3.Connection) -> JsonObject:
    total = conn.execute(
        """
        select coalesce(sum(estimated_cost), 0) as cost, coalesce(sum(total_tokens), 0) as tokens,
               coalesce(sum(prompt_tokens), 0) as prompt_tokens,
               coalesce(sum(completion_tokens), 0) as completion_tokens,
               coalesce(sum(cached_tokens), 0) as cached_tokens,
               coalesce(sum(reasoning_tokens), 0) as reasoning_tokens,
               sum(case when cost_status = 'unknown' then 1 else 0 end) as unknown_costs,
               sum(case when cost_status = 'local/free' then 1 else 0 end) as local_costs,
               sum(case when cost_status = 'exact' then 1 else 0 end) as exact_costs,
               sum(case when cost_status = 'estimated' then 1 else 0 end) as estimated_costs
        from cost_records
        """
    ).fetchone()
    failed = conn.execute(
        """
        select coalesce(sum(cr.estimated_cost), 0) as cost
        from cost_records cr join workflow_runs wr on wr.trace_id = cr.trace_id
        where wr.status = 'failed'
        """
    ).fetchone()
    succeeded = conn.execute(
        """
        select count(distinct wr.trace_id) as runs, coalesce(sum(cr.estimated_cost), 0) as cost
        from workflow_runs wr left join cost_records cr on cr.trace_id = wr.trace_id
        where wr.status = 'succeeded'
        """
    ).fetchone()
    budget = conn.execute("select * from budget_settings where scope = 'workspace' and scope_id = 'default'").fetchone()
    monthly_budget = _float(budget["monthly_budget"] if budget else 500.0)
    spend = _float(total["cost"])
    successful_runs = max(_int(succeeded["runs"]), 1)
    return {
        "total_spend_today": spend,
        "total_spend_week": spend,
        "total_spend_month": spend,
        "projected_monthly_spend": spend * 1.2,
        "budget_used": spend / max(monthly_budget, 1.0),
        "budget_remaining": max(monthly_budget - spend, 0.0),
        "cost_per_successful_run": _float(succeeded["cost"]) / successful_runs,
        "cost_wasted_on_failed_runs": _float(failed["cost"]),
        "cache_savings": _int(total["cached_tokens"]) * 0.0000005,
        "token_split": {
            "prompt": _int(total["prompt_tokens"]),
            "completion": _int(total["completion_tokens"]),
            "cached": _int(total["cached_tokens"]),
            "reasoning": _int(total["reasoning_tokens"]),
        },
        "total_tokens": _int(total["tokens"]),
        "total_cost": spend,
        "cost_status_counts": {
            "exact": _int(total["exact_costs"]),
            "estimated": _int(total["estimated_costs"]),
            "local/free": _int(total["local_costs"]),
            "unknown": _int(total["unknown_costs"]),
        },
        "budget_settings": _row_dict(budget) if budget else {},
        "budget_alert_history": [],
    }


def cost_by_dimension(conn: sqlite3.Connection, dimension: str) -> list[JsonObject]:
    allowed = {
        "workflow": "workflow_name",
        "agent": "agent_name",
        "model": "model",
        "provider": "provider",
    }
    column = allowed[dimension]
    rows = conn.execute(
        f"""
        select coalesce({column}, 'unknown') as name, count(*) as calls,
               sum(total_tokens) as total_tokens, sum(estimated_cost) as estimated_cost,
               avg(latency_ms) as avg_latency_ms
        from cost_records
        group by coalesce({column}, 'unknown')
        order by estimated_cost desc
        """
    ).fetchall()
    return [_row_dict(row) for row in rows]


def cost_by_failed_run(conn: sqlite3.Connection) -> list[JsonObject]:
    rows = conn.execute(
        """
        select wr.trace_id, wr.workflow_name, wr.status, wr.error_type, wr.error_message,
               coalesce(sum(cr.estimated_cost), 0) as estimated_cost,
               coalesce(sum(cr.total_tokens), 0) as total_tokens
        from workflow_runs wr
        left join cost_records cr on cr.trace_id = wr.trace_id
        where wr.status = 'failed'
        group by wr.trace_id
        order by estimated_cost desc
        """
    ).fetchall()
    return [_row_dict(row) for row in rows]


def list_prompts(conn: sqlite3.Connection) -> list[JsonObject]:
    rows = conn.execute(
        """
        select pv.prompt_hash, pv.agent as owner, max(pv.created_at) as last_updated,
               count(*) as usage_count, max(pv.prompt_id) as latest_version,
               avg(cr.estimated_cost) as avg_cost
        from prompt_versions pv
        left join cost_records cr on cr.trace_id = pv.trace_id
        group by pv.prompt_hash, pv.agent
        order by last_updated desc
        """
    ).fetchall()
    return [
        {
            "prompt_name": f"{row['owner']} prompt",
            "prompt_hash": row["prompt_hash"],
            "latest_version": row["latest_version"],
            "owner": row["owner"],
            "usage_count": _int(row["usage_count"]),
            "avg_cost": _float(row["avg_cost"]),
            "avg_quality_score": None,
            "last_updated": row["last_updated"],
        }
        for row in rows
    ]


def prompt_versions(conn: sqlite3.Connection, prompt_id: str) -> list[JsonObject]:
    row = conn.execute("select prompt_hash from prompt_versions where prompt_id = ?", (prompt_id,)).fetchone()
    if row is None:
        return []
    rows = conn.execute(
        """
        select * from prompt_versions where prompt_hash = ? order by created_at desc
        """,
        (row["prompt_hash"],),
    ).fetchall()
    return [_prompt_version_to_json(row) for row in rows]


def compare_prompts(conn: sqlite3.Connection, left: str, right: str) -> JsonObject:
    left_row = conn.execute("select * from prompt_versions where prompt_id = ?", (left,)).fetchone()
    right_row = conn.execute("select * from prompt_versions where prompt_id = ?", (right,)).fetchone()
    return {
        "left": _prompt_version_to_json(left_row) if left_row else None,
        "right": _prompt_version_to_json(right_row) if right_row else None,
        "cost_difference": 0,
        "quality_difference": None,
        "text_changed": (left_row["user_prompt"] if left_row else "") != (right_row["user_prompt"] if right_row else ""),
    }


def list_approvals(conn: sqlite3.Connection, status: str | None = None, limit: int = 100) -> list[JsonObject]:
    where = "where a.status = ?" if status else ""
    params: tuple[Any, ...] = (status, limit) if status else (limit,)
    rows = conn.execute(
        f"""
        select a.*, wr.workflow_name
        from approvals a
        left join workflow_runs wr on wr.trace_id = a.trace_id
        {where}
        order by a.created_at desc
        limit ?
        """,
        params,
    ).fetchall()
    return [
        {
            "approval_id": row["approval_id"],
            "trace_id": row["trace_id"],
            "workflow": row["workflow_name"],
            "agent": row["agent"],
            "tool": row["tool"],
            "risky_action": row["tool"],
            "arguments": loads_json(row["arguments_json"]),
            "input_args": loads_json(row["arguments_json"]),
            "status": row["status"],
            "risk_level": _risk_level(loads_json(row["arguments_json"])),
            "reason": row["reason"] or "Tool requires human approval because it can perform a sensitive action.",
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }
        for row in rows
    ]


def list_evaluations(conn: sqlite3.Connection) -> list[JsonObject]:
    rows = conn.execute("select * from evaluations order by created_at desc limit 200").fetchall()
    return [_evaluation_to_json(row) for row in rows]


def evaluation_summary(conn: sqlite3.Connection) -> JsonObject:
    rows = list_evaluations(conn)
    scores = [float(item["score"]) for item in rows if item.get("score") is not None]
    passed = [item for item in rows if item.get("passed")]
    return {
        "count": len(rows),
        "task_success_score": sum(scores) / len(scores) if scores else None,
        "human_rating": None,
        "schema_validation_pass_rate": len(passed) / len(rows) if rows else None,
        "rag_faithfulness_score": None,
        "hallucination_risk": None,
        "regression_status": "not_configured" if not rows else "passing",
        "quality_by_workflow": _quality_by(rows, "workflow_name"),
        "quality_by_agent": _quality_by(rows, "agent_name"),
        "quality_by_model": [],
        "quality_by_prompt_version": [],
    }


def save_evaluation(conn: sqlite3.Connection, payload: JsonObject) -> JsonObject:
    evaluation_id = str(payload.get("evaluation_id") or f"eval_{datetime.now(UTC).timestamp():.0f}")
    now = utc_now()
    conn.execute(
        """
        insert or replace into evaluations
        (evaluation_id, trace_id, workflow_id, workflow_name, agent_id, agent_name, evaluator, evaluator_type, status,
         score, human_rating, passed, expected_json, actual_json, findings_json, created_at, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evaluation_id,
            _string(payload.get("trace_id")),
            _string(payload.get("workflow_id")),
            _string(payload.get("workflow_name")),
            _string(payload.get("agent_id")),
            _string(payload.get("agent_name")),
            str(payload.get("evaluator", "mock-evaluator")),
            str(payload.get("evaluator_type", "deterministic_mock")),
            str(payload.get("status", "completed")),
            _float_or_none(payload.get("score")),
            _float_or_none(payload.get("human_rating")),
            1 if payload.get("passed", True) else 0,
            dumps_json(payload.get("expected")),
            dumps_json(payload.get("actual")),
            dumps_json(payload.get("findings", [])),
            now,
            dumps_json(payload.get("metadata", {})),
        ),
    )
    return {"evaluation_id": evaluation_id, "created_at": now, "status": "completed"}


def create_replay(conn: sqlite3.Connection, trace_id: str, span_id: str | None, mode: str, result: JsonObject) -> JsonObject:
    replay_id = f"replay_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    now = utc_now()
    conn.execute(
        """
        insert into replay_runs
        (replay_id, source_trace_id, source_span_id, mode, status, created_at, completed_at, result_json, metadata_json)
        values (?, ?, ?, ?, 'completed', ?, ?, ?, ?)
        """,
        (replay_id, trace_id, span_id, mode, now, now, dumps_json(result), dumps_json({"side_effects_disabled": True})),
    )
    return {"replay_id": replay_id, "source_trace_id": trace_id, "source_span_id": span_id, "status": "completed", "result": result}


def list_replay_runs(conn: sqlite3.Connection) -> list[JsonObject]:
    rows = conn.execute("select * from replay_runs order by created_at desc limit 100").fetchall()
    return [_replay_to_json(row) for row in rows]


def get_replay(conn: sqlite3.Connection, replay_id: str) -> JsonObject | None:
    row = conn.execute("select * from replay_runs where replay_id = ?", (replay_id,)).fetchone()
    return _replay_to_json(row) if row else None


def audit_logs(conn: sqlite3.Connection, limit: int = 200) -> list[JsonObject]:
    rows = conn.execute(
        "select trace_id, actor, action, resource, payload_json, timestamp from audit_logs order by timestamp desc limit ?",
        (limit,),
    ).fetchall()
    return [
        {
            "trace_id": row["trace_id"],
            "actor": row["actor"],
            "action": row["action"],
            "resource": row["resource"],
            "payload": loads_json(row["payload_json"]),
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


def _materialize_agent(
    conn: sqlite3.Connection,
    event: Any,
    payload: JsonObject,
    agent_id: str | None,
    agent_name: str | None,
    provider: str | None,
    model: str | None,
    status: str,
    current_task: str | None,
) -> None:
    if not agent_id or not agent_name:
        return
    role = _string(payload.get("role"))
    message = payload.get("message", {})
    task_name = current_task
    if isinstance(message, dict):
        message_payload = message.get("payload", {})
        if isinstance(message_payload, dict):
            task_name = _string(message_payload.get("task")) or task_name
    existing = conn.execute("select created_at from agents where agent_id = ?", (agent_id,)).fetchone()
    created_at = existing["created_at"] if existing else event.timestamp
    conn.execute(
        """
        insert into agents
        (agent_id, agent_name, role, instructions, provider, model, status, current_task, created_at, updated_at, metadata_json)
        values (?, ?, ?, null, ?, ?, ?, ?, ?, ?, ?)
        on conflict(agent_id) do update set
          role = coalesce(excluded.role, agents.role),
          provider = coalesce(excluded.provider, agents.provider),
          model = coalesce(excluded.model, agents.model),
          status = excluded.status,
          current_task = coalesce(excluded.current_task, agents.current_task),
          updated_at = excluded.updated_at
        """,
        (agent_id, agent_name, role, provider, model, status, task_name, created_at, event.timestamp, dumps_json({})),
    )


def _materialize_task(
    conn: sqlite3.Connection,
    event: Any,
    payload: JsonObject,
    workflow: JsonObject,
    agent_id: str | None,
    agent_name: str | None,
    task_id: str | None,
    task_name: str | None,
    status: str,
    error: JsonObject,
) -> None:
    task = _extract_task(payload)
    resolved_task_id = task_id or _string(task.get("id")) or event.span_id
    started = conn.execute("select started_at from tasks where task_id = ?", (resolved_task_id,)).fetchone()
    started_at = started["started_at"] if started else event.timestamp
    ended_at = event.timestamp if status in {"succeeded", "failed", "cancelled"} else None
    duration = _duration_ms(started_at, ended_at) if ended_at else None
    conn.execute(
        """
        insert into tasks
        (task_id, trace_id, workflow_id, agent_id, agent_name, task_name, status, started_at, ended_at, duration_ms,
         retry_count, input_json, output_json, error_type, error_message, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(task_id) do update set
          status = excluded.status,
          ended_at = coalesce(excluded.ended_at, tasks.ended_at),
          duration_ms = coalesce(excluded.duration_ms, tasks.duration_ms),
          retry_count = max(tasks.retry_count, excluded.retry_count),
          output_json = coalesce(excluded.output_json, tasks.output_json),
          error_type = coalesce(excluded.error_type, tasks.error_type),
          error_message = coalesce(excluded.error_message, tasks.error_message)
        """,
        (
            resolved_task_id,
            event.trace_id,
            workflow["workflow_id"],
            agent_id,
            agent_name,
            task_name,
            status,
            started_at,
            ended_at,
            duration,
            _int(payload.get("attempt")) - 1 if _int(payload.get("attempt")) > 1 else 0,
            dumps_json(_input_payload(event.event_type, payload)),
            dumps_json(_output_payload(event.event_type, payload)),
            error["type"],
            error["message"],
            dumps_json(payload.get("metadata", {})),
        ),
    )


def _materialize_model_event(
    conn: sqlite3.Connection,
    event: Any,
    payload: JsonObject,
    workflow: JsonObject,
    agent_id: str | None,
    agent_name: str | None,
    task_id: str | None,
    task_name: str | None,
    status: str,
    error: JsonObject,
) -> None:
    provider = _string(payload.get("provider")) or "unknown"
    model = _string(payload.get("model")) or "unknown"
    prompt_version = _string(payload.get("prompt_version") or payload.get("prompt_id"))
    if event.event_type == "model.call":
        conn.execute(
            """
            insert or replace into model_calls
            (model_call_id, trace_id, span_id, parent_span_id, agent_id, agent_name, task_id, task_name, provider, model,
             endpoint_alias, status, started_at, ended_at, duration_ms, prompt_version, prompt_json, output_json,
             prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, total_tokens, estimated_cost,
             cost_status, cost_source, temperature, top_p, max_tokens, context_window, error_type, error_message,
             request_id, retry_count, metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, null, null, ?, ?, null, 0, 0, 0, 0, 0, 0,
                    'unknown', null, ?, ?, ?, ?, null, null, ?, 0, ?)
            """,
            (
                event.span_id,
                event.trace_id,
                event.span_id,
                event.parent_span_id,
                agent_id,
                agent_name,
                task_id,
                task_name,
                provider,
                model,
                _string(payload.get("endpoint_alias")),
                event.timestamp,
                prompt_version,
                dumps_json({"system": payload.get("system"), "prompt": payload.get("prompt")}),
                _float_or_none(payload.get("temperature")),
                _float_or_none(payload.get("top_p")),
                _int_or_none(payload.get("max_tokens")),
                _context_window(model),
                _string(payload.get("request_id")),
                dumps_json(payload.get("metadata", {})),
            ),
        )
        return
    if event.event_type in {"model.response", "model.failed", "model.error"}:
        prompt_tokens = _int(payload.get("prompt_tokens"))
        completion_tokens = _int(payload.get("completion_tokens"))
        cached_tokens = _int(payload.get("cached_tokens"))
        reasoning_tokens = _int(payload.get("reasoning_tokens"))
        total_tokens = _int(payload.get("total_tokens")) or prompt_tokens + completion_tokens + cached_tokens + reasoning_tokens
        cost = _float(payload.get("estimated_cost") or payload.get("cost_usd"))
        cost_status = _string(payload.get("cost_status")) or ("estimated" if cost else "unknown")
        cost_source = _string(payload.get("cost_source"))
        latency = _float(payload.get("latency_ms") or payload.get("duration_ms"))
        pending = conn.execute(
            """
            select model_call_id, started_at from model_calls
            where trace_id = ? and agent_name = ? and status = 'running'
            order by started_at desc limit 1
            """,
            (event.trace_id, agent_name),
        ).fetchone()
        model_call_id = pending["model_call_id"] if pending else event.span_id
        started_at = pending["started_at"] if pending else event.timestamp
        conn.execute(
            """
            insert into model_calls
            (model_call_id, trace_id, span_id, parent_span_id, agent_id, agent_name, task_id, task_name, provider, model,
             endpoint_alias, status, started_at, ended_at, duration_ms, prompt_version, output_json, prompt_tokens,
             completion_tokens, cached_tokens, reasoning_tokens, total_tokens, estimated_cost, temperature, top_p,
             max_tokens, context_window, error_type, error_message, cost_status, cost_source, request_id, retry_count,
             metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(model_call_id) do update set
              status = excluded.status,
              provider = excluded.provider,
              model = excluded.model,
              ended_at = excluded.ended_at,
              duration_ms = excluded.duration_ms,
              output_json = excluded.output_json,
              prompt_tokens = excluded.prompt_tokens,
              completion_tokens = excluded.completion_tokens,
              cached_tokens = excluded.cached_tokens,
              reasoning_tokens = excluded.reasoning_tokens,
              total_tokens = excluded.total_tokens,
              estimated_cost = excluded.estimated_cost,
              cost_status = excluded.cost_status,
              cost_source = excluded.cost_source,
              error_type = excluded.error_type,
              error_message = excluded.error_message,
              request_id = excluded.request_id,
              retry_count = excluded.retry_count
            """,
            (
                model_call_id,
                event.trace_id,
                event.span_id,
                event.parent_span_id,
                agent_id,
                agent_name,
                task_id,
                task_name,
                provider,
                model,
                _string(payload.get("endpoint_alias")),
                "failed" if event.event_type != "model.response" else "succeeded",
                started_at,
                event.timestamp,
                latency,
                prompt_version,
                dumps_json(payload.get("output")),
                prompt_tokens,
                completion_tokens,
                cached_tokens,
                reasoning_tokens,
                total_tokens,
                cost,
                _float_or_none(payload.get("temperature")),
                _float_or_none(payload.get("top_p")),
                _int_or_none(payload.get("max_tokens")),
                _context_window(model),
                error["type"],
                error["message"],
                cost_status,
                cost_source,
                _string(payload.get("request_id")),
                _int(payload.get("retry_count")),
                dumps_json(payload.get("metadata", {})),
            ),
        )
        conn.execute(
            """
            insert or replace into cost_records
            (cost_record_id, trace_id, workflow_id, workflow_name, agent_id, agent_name, provider, model, status,
             prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, total_tokens, estimated_cost,
             cost_status, cost_source, latency_ms, timestamp, metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"cost_{model_call_id}",
                event.trace_id,
                workflow["workflow_id"],
                workflow["workflow_name"],
                agent_id,
                agent_name,
                provider,
                model,
                "failed" if event.event_type != "model.response" else "succeeded",
                prompt_tokens,
                completion_tokens,
                cached_tokens,
                reasoning_tokens,
                total_tokens,
                cost,
                cost_status,
                cost_source,
                latency,
                event.timestamp,
                dumps_json(payload.get("metadata", {})),
            ),
        )
        _refresh_provider_health(conn)


def _materialize_tool_event(
    conn: sqlite3.Connection,
    event: Any,
    payload: JsonObject,
    agent_id: str | None,
    agent_name: str | None,
    status: str,
    error: JsonObject,
) -> None:
    tool_value = payload.get("tool", {})
    tool_obj = tool_value if isinstance(tool_value, dict) else {}
    tool_name = _string(payload.get("tool") if isinstance(payload.get("tool"), str) else None) or _string(tool_obj.get("name")) or "unknown"
    if event.event_type == "tool.started":
        conn.execute(
            """
            insert or replace into tool_calls
            (tool_call_id, trace_id, span_id, parent_span_id, agent_id, agent_name, tool_name, tool_type, status,
             started_at, ended_at, duration_ms, permission_level, approval_status, risk_level, retry_count, side_effect,
             input_json, output_json, stdout, stderr, error_type, error_message, sandbox_logs_json, mcp_metadata_json,
             side_effects_json, metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, null, null, ?, ?, ?, 0, ?, ?, null, null, null, null, null, ?, ?, ?, ?)
            """,
            (
                event.span_id,
                event.trace_id,
                event.span_id,
                event.parent_span_id,
                agent_id,
                agent_name,
                tool_name,
                str(tool_obj.get("type", "local")),
                event.timestamp,
                _string(tool_obj.get("permission")),
                "required" if tool_obj.get("requires_approval") else "not_required",
                "high" if tool_obj.get("requires_approval") else "low",
                1 if tool_obj.get("permission") in {"write", "execute", "sensitive"} else 0,
                dumps_json(payload.get("arguments", {})),
                dumps_json([]),
                dumps_json(tool_obj.get("mcp", {})),
                dumps_json([]),
                dumps_json(payload.get("metadata", {})),
            ),
        )
        return
    if event.event_type in {"tool.finished", "tool.failed"}:
        tool_call_id = event.parent_span_id or event.span_id
        row = conn.execute("select started_at from tool_calls where tool_call_id = ?", (tool_call_id,)).fetchone()
        started_at = row["started_at"] if row else event.timestamp
        conn.execute(
            """
            insert into tool_calls
            (tool_call_id, trace_id, span_id, parent_span_id, agent_id, agent_name, tool_name, tool_type, status,
             started_at, ended_at, duration_ms, permission_level, approval_status, risk_level, retry_count, side_effect,
             input_json, output_json, stdout, stderr, error_type, error_message, sandbox_logs_json, mcp_metadata_json,
             side_effects_json, metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, 'local', ?, ?, ?, ?, null, null, ?, 0, 0, null, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(tool_call_id) do update set
              status = excluded.status,
              ended_at = excluded.ended_at,
              duration_ms = excluded.duration_ms,
              output_json = excluded.output_json,
              stdout = excluded.stdout,
              stderr = excluded.stderr,
              error_type = excluded.error_type,
              error_message = excluded.error_message,
              sandbox_logs_json = excluded.sandbox_logs_json,
              side_effects_json = excluded.side_effects_json
            """,
            (
                tool_call_id,
                event.trace_id,
                event.span_id,
                event.parent_span_id,
                agent_id,
                agent_name,
                tool_name,
                "failed" if event.event_type == "tool.failed" else "succeeded",
                started_at,
                event.timestamp,
                _duration_ms(started_at, event.timestamp),
                "high" if event.event_type == "tool.failed" else "low",
                dumps_json(payload.get("result")),
                _string(payload.get("stdout")),
                _string(payload.get("stderr")),
                error["type"],
                error["message"],
                dumps_json(payload.get("sandbox_logs", [])),
                dumps_json(payload.get("mcp_metadata", {})),
                dumps_json(payload.get("side_effects", [])),
                dumps_json(payload.get("metadata", {})),
            ),
        )


def _materialize_memory_operation(
    conn: sqlite3.Connection,
    event: Any,
    payload: JsonObject,
    agent_id: str | None,
    agent_name: str | None,
) -> None:
    value = payload.get("value")
    key = _string(payload.get("key") or payload.get("namespace"))
    conn.execute(
        """
        insert or replace into memory_operations
        (operation_id, trace_id, span_id, agent_id, agent_name, memory_type, operation, key, value_preview, value_json,
         version, redacted, timestamp, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.trace_id,
            event.span_id,
            agent_id,
            agent_name,
            str(payload.get("memory_type", "long-term" if event.event_type == "memory.write" else "workflow state")),
            event.event_type.replace("memory.", ""),
            key,
            _preview(value),
            dumps_json(value),
            _int_or_none(payload.get("version")),
            1 if payload.get("redacted") else 0,
            event.timestamp,
            dumps_json(payload.get("metadata", {})),
        ),
    )


def _materialize_rag_retrieval(
    conn: sqlite3.Connection,
    event: Any,
    payload: JsonObject,
    agent_id: str | None,
    agent_name: str | None,
) -> None:
    documents = payload.get("documents", payload.get("retrieved_documents", []))
    docs = documents if isinstance(documents, list) else []
    chunk_ids = [str(item.get("id") or item.get("chunk_id")) for item in docs if isinstance(item, dict)]
    scores = [item.get("score") for item in docs if isinstance(item, dict)]
    conn.execute(
        """
        insert or replace into rag_retrievals
        (retrieval_id, trace_id, span_id, agent_id, agent_name, query, embedding_model, vector_store,
         retrieved_documents_json, chunk_ids_json, chunk_preview, scores_json, source_metadata_json, used_in_answer,
         citation_mapping_json, timestamp, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.trace_id,
            event.span_id,
            agent_id,
            agent_name,
            _string(payload.get("query")),
            _string(payload.get("embedding_model")) or "simple-hash-embedding",
            _string(payload.get("vector_store")) or "sqlite-vector",
            dumps_json(docs),
            dumps_json(chunk_ids),
            _preview(docs[0].get("content") if docs and isinstance(docs[0], dict) else docs),
            dumps_json(scores),
            dumps_json(payload.get("source_metadata", {})),
            1 if payload.get("used_in_answer", True) else 0,
            dumps_json(payload.get("citation_mapping", {})),
            event.timestamp,
            dumps_json(payload.get("metadata", {})),
        ),
    )


def _materialize_replay_checkpoint(conn: sqlite3.Connection, event: Any, payload: JsonObject) -> None:
    checkpoint_id = str(payload.get("checkpoint_id"))
    conn.execute(
        """
        insert or ignore into replay_runs
        (replay_id, source_trace_id, source_span_id, mode, status, created_at, completed_at, result_json, metadata_json)
        values (?, ?, ?, 'checkpoint', 'available', ?, null, ?, ?)
        """,
        (
            f"checkpoint_{checkpoint_id}",
            event.trace_id,
            _string(payload.get("step_id")),
            event.timestamp,
            dumps_json(payload),
            dumps_json({"checkpoint_id": checkpoint_id}),
        ),
    )
    conn.execute(
        """
        insert or replace into replay_checkpoints
        (checkpoint_id, trace_id, span_id, step_id, checkpoint_type, created_at, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            checkpoint_id,
            event.trace_id,
            event.parent_span_id,
            _string(payload.get("step_id")),
            str(payload.get("checkpoint_type", "checkpoint")),
            event.timestamp,
            dumps_json(payload),
        ),
    )


def _audit_signal(conn: sqlite3.Connection, event: Any, payload: JsonObject) -> None:
    action_map = {
        "approval.requested": "approval.requested",
        "approval.resolved": "approval.resolved",
        "tool.started": "tool.invoked",
        "model.call": "model.call",
        "workflow.started": "workflow.started",
        "workflow.finished": "workflow.finished",
        "workflow.failed": "workflow.failed",
        "prompt.version_saved": "prompt.changed",
    }
    action = action_map.get(event.event_type)
    if not action:
        return
    conn.execute(
        """
        insert into audit_logs (trace_id, actor, action, resource, payload_json, timestamp)
        values (?, ?, ?, ?, ?, ?)
        """,
        (event.trace_id, event.actor, action, event.event_type, dumps_json(payload), event.timestamp),
    )


def _refresh_provider_health(conn: sqlite3.Connection) -> None:
    now = utc_now()
    stats = conn.execute(
        """
        select provider, count(*) as calls, coalesce(sum(total_tokens), 0) as tokens,
               coalesce(sum(estimated_cost), 0) as cost, coalesce(avg(duration_ms), 0) as avg_latency,
               sum(case when status = 'failed' then 1 else 0 end) as errors,
               max(error_message) as last_error
        from model_calls
        group by provider
        """
    ).fetchall()
    for row in stats:
        provider = row["provider"] or "unknown"
        calls = _int(row["calls"])
        errors = _int(row["errors"])
        conn.execute(
            """
            insert into provider_health
            (provider, display_name, status, calls, tokens, cost_usd, avg_latency_ms, p95_latency_ms, error_count,
             error_rate, rate_limit_events, fallback_count, last_error, updated_at, metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
            on conflict(provider) do update set
              status = excluded.status,
              calls = excluded.calls,
              tokens = excluded.tokens,
              cost_usd = excluded.cost_usd,
              avg_latency_ms = excluded.avg_latency_ms,
              p95_latency_ms = excluded.p95_latency_ms,
              error_count = excluded.error_count,
              error_rate = excluded.error_rate,
              last_error = excluded.last_error,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                provider,
                provider.replace("-", " ").title(),
                "degraded" if errors else "healthy",
                calls,
                _int(row["tokens"]),
                _float(row["cost"]),
                _float(row["avg_latency"]),
                _p95_latency_for_provider(conn, provider),
                errors,
                errors / calls if calls else 0,
                row["last_error"],
                now,
                dumps_json({}),
            ),
        )


def _workflow_for_trace(conn: sqlite3.Connection, trace_id: str) -> JsonObject:
    row = conn.execute(
        "select workflow_id, workflow_name, environment, is_demo from workflow_runs where trace_id = ?",
        (trace_id,),
    ).fetchone()
    if row:
        return {
            "workflow_id": row["workflow_id"],
            "workflow_name": row["workflow_name"],
            "environment": row["environment"],
            "is_demo": bool(row["is_demo"]),
        }
    legacy = conn.execute("select name from workflows where trace_id = ?", (trace_id,)).fetchone()
    name = legacy["name"] if legacy else "unknown-workflow"
    return {"workflow_id": _workflow_id(name), "workflow_name": name, "environment": "local", "is_demo": False}


def _workflow_id(name: str) -> str:
    return "wf_" + "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")[:80]


def _agent_id(name: str) -> str:
    return "agent_" + "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")[:80]


def _agent_name(actor: str) -> str | None:
    return None if actor in {"workflow", "system", ""} else actor


def _extract_task(payload: JsonObject) -> JsonObject:
    task = payload.get("task")
    if isinstance(task, dict):
        return task
    step = payload.get("step")
    if isinstance(step, dict) and isinstance(step.get("task"), dict):
        return step["task"]  # type: ignore[return-value]
    message = payload.get("message")
    if isinstance(message, dict):
        message_payload = message.get("payload")
        if isinstance(message_payload, dict):
            return {"id": message.get("task_id"), "description": message_payload.get("task")}
    return {}


def _status_from_event(event_type: str, payload: JsonObject) -> str:
    if "failed" in event_type or "error" in event_type:
        return "failed"
    if "cancelled" in event_type:
        return "cancelled"
    if "retry" in event_type:
        return "retry"
    if event_type.endswith(("finished", "response", "saved", "resolved", "retrieval", "write", "read", "succeeded")):
        return "succeeded"
    if event_type.endswith(("started", "call", "requested")):
        return "running"
    if payload.get("status"):
        return str(payload["status"])
    return "event"


def _extract_error(payload: JsonObject) -> JsonObject:
    error = payload.get("error")
    if isinstance(error, dict):
        return {
            "type": _string(error.get("kind") or error.get("error_type") or error.get("type")),
            "message": _string(error.get("message") or error.get("error_message")),
        }
    return {"type": _string(payload.get("error_type")), "message": _string(payload.get("error_message"))}


def _memory_operation(event_type: str, payload: JsonObject) -> str | None:
    if not event_type.startswith("memory."):
        return None
    return _string(payload.get("operation")) or event_type.replace("memory.", "")


def _rag_doc_ids(payload: JsonObject) -> list[str]:
    documents = payload.get("documents", payload.get("retrieved_documents", []))
    if not isinstance(documents, list):
        return []
    return [str(item.get("id") or item.get("document_id") or item.get("chunk_id")) for item in documents if isinstance(item, dict)]


def _span_metadata(payload: JsonObject) -> JsonObject:
    metadata = payload.get("metadata", {})
    return safe_json(metadata) if isinstance(metadata, dict) else {}


def _input_payload(event_type: str, payload: JsonObject) -> JsonValue:
    if event_type == "model.call":
        return {"system": payload.get("system"), "prompt": payload.get("prompt")}
    if event_type == "tool.started":
        return payload.get("arguments", {})
    if event_type.startswith("memory."):
        return {"key": payload.get("key"), "namespace": payload.get("namespace")}
    return payload.get("input") or payload.get("arguments") or payload.get("message") or payload.get("task")


def _output_payload(event_type: str, payload: JsonObject) -> JsonValue:
    if event_type == "model.response":
        return payload.get("output")
    if event_type == "tool.finished":
        return payload.get("result")
    if event_type.startswith("memory."):
        return payload.get("value")
    return payload.get("output") or payload.get("result")


def _legacy_trace_rows(conn: sqlite3.Connection, limit: int) -> list[JsonObject]:
    rows = conn.execute(
        "select trace_id, name, status, started_at, ended_at, error_json from workflows order by started_at desc limit ?",
        (limit,),
    ).fetchall()
    return [
        {
            "trace_id": row["trace_id"],
            "run_id": row["trace_id"],
            "workflow_id": _workflow_id(row["name"]),
            "workflow_name": row["name"],
            "name": row["name"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "duration_ms": _duration_ms(row["started_at"], row["ended_at"]),
            "error": loads_json(row["error_json"]),
            "total_tokens": 0,
            "estimated_cost": 0,
            "span_count": 0,
        }
        for row in rows
    ]


def _workflow_run_to_json(row: sqlite3.Row) -> JsonObject:
    return {
        "trace_id": row["trace_id"],
        "run_id": row["run_id"],
        "workflow_id": row["workflow_id"],
        "workflow_name": row["workflow_name"],
        "name": row["workflow_name"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "duration_ms": row["duration_ms"],
        "input": loads_json(row["input_json"]),
        "output": loads_json(row["output_json"]),
        "error_type": row["error_type"],
        "error_message": row["error_message"],
        "error": {"type": row["error_type"], "message": row["error_message"]} if row["error_message"] else None,
        "environment": row["environment"],
        "is_demo": bool(row["is_demo"]),
        "metadata": loads_json(row["metadata_json"]),
        "total_tokens": _int(row["total_tokens"]),
        "estimated_cost": _float(row["estimated_cost"]),
        "max_latency_ms": _float(row["max_latency_ms"]),
        "span_count": _int(row["span_count"]),
    }


def _span_to_json(row: sqlite3.Row) -> JsonObject:
    data = _row_dict(row)
    for key in ["input_json", "output_json", "rag_document_ids_json", "metadata_json"]:
        target = key.replace("_json", "")
        data[target] = loads_json(row[key])
        data.pop(key, None)
    return data


def _model_call_to_json(row: sqlite3.Row) -> JsonObject:
    data = _row_dict(row)
    for key in ["prompt_json", "output_json", "metadata_json"]:
        target = key.replace("_json", "")
        data[target] = loads_json(row[key])
        data.pop(key, None)
    return data


def _tool_call_to_json(row: sqlite3.Row) -> JsonObject:
    data = _row_dict(row)
    for key in ["input_json", "output_json", "sandbox_logs_json", "mcp_metadata_json", "side_effects_json", "metadata_json"]:
        target = key.replace("_json", "")
        data[target] = loads_json(row[key])
        data.pop(key, None)
    data["side_effect"] = bool(data["side_effect"])
    return data


def _memory_operation_to_json(row: sqlite3.Row) -> JsonObject:
    data = _row_dict(row)
    data["value"] = loads_json(row["value_json"])
    data["metadata"] = loads_json(row["metadata_json"])
    data["redacted"] = bool(row["redacted"])
    data.pop("value_json", None)
    data.pop("metadata_json", None)
    return data


def _rag_retrieval_to_json(row: sqlite3.Row) -> JsonObject:
    data = _row_dict(row)
    for key in ["retrieved_documents_json", "chunk_ids_json", "scores_json", "source_metadata_json", "citation_mapping_json", "metadata_json"]:
        target = key.replace("_json", "")
        data[target] = loads_json(row[key])
        data.pop(key, None)
    data["used_in_answer"] = bool(data["used_in_answer"])
    return data


def _agent_to_json(row: sqlite3.Row) -> JsonObject:
    calls = _int(row["model_calls"])
    failures = _int(row["failures"])
    return {
        **_row_dict(row),
        "metadata": loads_json(row["metadata_json"]),
        "success_rate": (calls - failures) / calls if calls else 1.0,
        "failure_rate": failures / calls if calls else 0.0,
        "tools_available": _int(row["tool_calls"]),
        "memory_permissions": ["workflow state", "long-term"],
    }


def _provider_to_json(row: sqlite3.Row) -> JsonObject:
    return {
        **_row_dict(row),
        "metadata": loads_json(row["metadata_json"]),
    }


def _prompt_version_to_json(row: sqlite3.Row) -> JsonObject:
    return {
        "prompt_id": row["prompt_id"],
        "trace_id": row["trace_id"],
        "agent": row["agent"],
        "task_id": row["task_id"],
        "prompt_hash": row["prompt_hash"],
        "system_prompt": row["system_prompt"],
        "user_prompt": row["user_prompt"],
        "metadata": loads_json(row["metadata_json"]),
        "created_at": row["created_at"],
    }


def _evaluation_to_json(row: sqlite3.Row) -> JsonObject:
    data = _row_dict(row)
    data["expected"] = loads_json(row["expected_json"])
    data["actual"] = loads_json(row["actual_json"])
    data["findings"] = loads_json(row["findings_json"])
    data["metadata"] = loads_json(row["metadata_json"])
    data["passed"] = bool(row["passed"]) if row["passed"] is not None else None
    for key in ["expected_json", "actual_json", "findings_json", "metadata_json"]:
        data.pop(key, None)
    return data


def _replay_to_json(row: sqlite3.Row) -> JsonObject:
    data = _row_dict(row)
    data["result"] = loads_json(row["result_json"])
    data["metadata"] = loads_json(row["metadata_json"])
    data.pop("result_json", None)
    data.pop("metadata_json", None)
    return data


def _row_dict(row: sqlite3.Row | None) -> JsonObject:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def _quality_by(rows: list[JsonObject], key: str) -> list[JsonObject]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.get("score") is None:
            continue
        grouped[str(row.get(key) or "unknown")].append(float(row["score"]))
    return [{"name": name, "score": sum(values) / len(values)} for name, values in grouped.items()]


def _node_type(event_type: str) -> str:
    if event_type.startswith("agent."):
        return "agent"
    if event_type.startswith("task."):
        return "task"
    if event_type.startswith("model."):
        return "model"
    if event_type.startswith("tool."):
        return "tool"
    if event_type.startswith("memory."):
        return "memory"
    if event_type.startswith("rag."):
        return "rag"
    if event_type.startswith("approval."):
        return "approval"
    return "event"


def _p95_latency_for_provider(conn: sqlite3.Connection, provider: str) -> float:
    rows = conn.execute(
        "select duration_ms from model_calls where provider = ? and duration_ms is not null order by duration_ms asc",
        (provider,),
    ).fetchall()
    return _p95([_float(row["duration_ms"]) for row in rows])


def _p95_latency_for_model(conn: sqlite3.Connection, provider: str, model: str) -> float:
    rows = conn.execute(
        """
        select duration_ms from model_calls
        where provider = ? and model = ? and duration_ms is not null
        order by duration_ms asc
        """,
        (provider, model),
    ).fetchall()
    return _p95([_float(row["duration_ms"]) for row in rows])


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, int(round((len(values) - 1) * 0.95)))
    return values[index]


def _context_window(model: str) -> int | None:
    lowered = model.lower()
    if "gpt-4.1" in lowered or "gpt-5" in lowered:
        return 1_000_000
    if "claude" in lowered:
        return 200_000
    if "gemini" in lowered:
        return 1_000_000
    if "llama" in lowered or "mistral" in lowered:
        return 128_000
    if "mock" in lowered:
        return 8_192
    return None


def _risk_level(arguments: JsonValue) -> str:
    text = str(arguments).lower()
    if any(token in text for token in ["delete", "drop", "send", "write", "payment", "credential"]):
        return "high"
    return "medium"


def _duration_ms(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((end_dt - start_dt).total_seconds() * 1000, 0.0)


def _is_demo(value: JsonValue) -> bool:
    return isinstance(value, dict) and bool(value.get("demo"))


def _environment(value: JsonValue) -> str:
    if isinstance(value, dict):
        environment = value.get("environment")
        if isinstance(environment, str) and environment:
            return environment
        if value.get("demo"):
            return "demo"
        if value.get("test"):
            return "test"
    return "local"


def _preview(value: JsonValue, limit: int = 180) -> str:
    rendered = dumps_json(value) if not isinstance(value, str) else value
    return rendered[:limit] + ("..." if len(rendered) > limit else "")


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
