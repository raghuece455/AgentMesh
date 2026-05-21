from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from agentmesh.types import JsonObject, JsonValue, dumps_json, loads_json, safe_json, utc_now


@dataclass(slots=True)
class EventRecord:
    trace_id: str
    event_type: str
    actor: str
    payload: JsonObject
    event_id: str
    span_id: str
    parent_span_id: str | None
    timestamp: str

    def to_json(self) -> JsonObject:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor": self.actor,
            "payload": self.payload,
        }


@dataclass(slots=True)
class TraceSummary:
    trace_id: str
    name: str
    status: str
    started_at: str
    ended_at: str | None
    error: JsonValue

    def to_json(self) -> JsonObject:
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
        }


class SQLiteStore:
    def __init__(self, path: str | Path = ".agentmesh/agentmesh.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("pragma busy_timeout = 30000")
        try:
            self._conn.execute("pragma journal_mode = wal")
        except sqlite3.OperationalError:
            # Another dashboard/CLI process may already hold the database. The
            # busy timeout still protects ordinary reads and writes, so keep the
            # current journal mode instead of failing process startup.
            pass
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate(self) -> None:
        from agentmesh.observability import install_schema

        if self._schema_is_ready():
            with self._lock:
                install_schema(self._conn)
                self._conn.commit()
            return
        statements = [
            """
            create table if not exists workflows (
              trace_id text primary key,
              name text not null,
              status text not null,
              started_at text not null,
              ended_at text,
              input_json text,
              output_json text,
              error_json text
            )
            """,
            """
            create table if not exists events (
              event_id text primary key,
              trace_id text not null,
              span_id text not null,
              parent_span_id text,
              timestamp text not null,
              event_type text not null,
              actor text not null,
              payload_json text not null,
              foreign key(trace_id) references workflows(trace_id)
            )
            """,
            "create index if not exists idx_events_trace_time on events(trace_id, timestamp)",
            """
            create table if not exists memories (
              id integer primary key autoincrement,
              agent text not null,
              namespace text not null,
              key text not null,
              value_json text not null,
              version integer not null,
              trace_id text,
              created_at text not null,
              updated_at text not null
            )
            """,
            "create index if not exists idx_memories_lookup on memories(agent, namespace, key, version)",
            """
            create table if not exists audit_logs (
              id integer primary key autoincrement,
              trace_id text,
              actor text not null,
              action text not null,
              resource text not null,
              payload_json text not null,
              timestamp text not null
            )
            """,
            """
            create table if not exists documents (
              id text primary key,
              source text not null,
              content text not null,
              metadata_json text not null,
              embedding_json text not null,
              created_at text not null
            )
            """,
            """
            create table if not exists checkpoints (
              checkpoint_id text primary key,
              trace_id text not null,
              step_id text,
              checkpoint_type text not null,
              state_json text not null,
              created_at text not null,
              foreign key(trace_id) references workflows(trace_id)
            )
            """,
            "create index if not exists idx_checkpoints_trace on checkpoints(trace_id, created_at)",
            """
            create table if not exists prompt_versions (
              prompt_id text primary key,
              trace_id text,
              agent text not null,
              task_id text,
              prompt_hash text not null,
              system_prompt text,
              user_prompt text not null,
              metadata_json text not null,
              created_at text not null
            )
            """,
            "create index if not exists idx_prompt_versions_trace on prompt_versions(trace_id, created_at)",
            """
            create table if not exists approvals (
              approval_id text primary key,
              trace_id text,
              agent text not null,
              tool text not null,
              arguments_json text not null,
              status text not null,
              reason text,
              created_at text not null,
              resolved_at text
            )
            """,
            "create index if not exists idx_approvals_status on approvals(status, created_at)",
            """
            create table if not exists task_results (
              idempotency_key text primary key,
              trace_id text not null,
              task_id text not null,
              value_json text not null,
              created_at text not null
            )
            """,
        ]
        try:
            with self._lock:
                for statement in statements:
                    self._conn.execute(statement)
                install_schema(self._conn)
                self._conn.commit()
        except sqlite3.OperationalError as exc:
            self._conn.rollback()
            if "locked" in str(exc).lower() and self._schema_is_ready():
                return
            raise

    def _schema_is_ready(self) -> bool:
        required = {
            "agents",
            "approvals",
            "audit_logs",
            "budget_settings",
            "checkpoints",
            "cost_records",
            "documents",
            "evaluations",
            "events",
            "memories",
            "memory_operations",
            "model_calls",
            "prompt_versions",
            "provider_health",
            "rag_retrievals",
            "replay_runs",
            "replay_checkpoints",
            "schema_migrations",
            "spans",
            "task_results",
            "tasks",
            "tool_calls",
            "workflow_runs",
            "workflows",
            "workflows_catalog",
            "traces",
        }
        rows = self._conn.execute(
            "select name from sqlite_master where type = 'table' and name in ({})".format(
                ",".join("?" for _ in required)
            ),
            tuple(required),
        ).fetchall()
        return {str(row["name"]) for row in rows} == required

    def reset_local_data(self) -> None:
        """Clear local AgentMesh records without deleting the SQLite file.

        This is useful on Windows when a dashboard process has the database
        file open and the filesystem will not allow unlinking it.
        """
        from agentmesh.observability import install_schema

        tables = [
            "replay_runs",
            "replay_checkpoints",
            "evaluations",
            "cost_records",
            "rag_retrievals",
            "memory_operations",
            "tool_calls",
            "model_calls",
            "spans",
            "tasks",
            "workflow_runs",
            "workflows_catalog",
            "events",
            "approvals",
            "prompt_versions",
            "checkpoints",
            "task_results",
            "memories",
            "documents",
            "audit_logs",
            "workflows",
            "traces",
            "provider_health",
            "budget_settings",
        ]
        with self._lock:
            for table in tables:
                self._conn.execute(f"delete from {table}")
            install_schema(self._conn)
            self._conn.commit()

    def create_workflow(self, trace_id: str, name: str, input_value: JsonValue) -> None:
        from agentmesh.observability import materialize_workflow_created

        with self._lock:
            self._conn.execute(
                """
                insert or replace into workflows
                (trace_id, name, status, started_at, ended_at, input_json, output_json, error_json)
                values (?, ?, ?, ?, null, ?, null, null)
                """,
                (trace_id, name, "running", utc_now(), dumps_json(input_value)),
            )
            materialize_workflow_created(self._conn, trace_id, name, input_value)
            self._conn.commit()

    def finish_workflow(
        self,
        trace_id: str,
        status: str,
        output_value: JsonValue | None = None,
        error_value: JsonValue | None = None,
    ) -> None:
        from agentmesh.observability import materialize_workflow_finished

        with self._lock:
            self._conn.execute(
                """
                update workflows
                set status = ?, ended_at = ?, output_json = ?, error_json = ?
                where trace_id = ?
                """,
                (status, utc_now(), dumps_json(output_value), dumps_json(error_value), trace_id),
            )
            materialize_workflow_finished(self._conn, trace_id, status, output_value, error_value)
            self._conn.commit()

    def record_event(self, event: EventRecord) -> None:
        from agentmesh.observability import materialize_event

        with self._lock:
            self._conn.execute(
                """
                insert into events
                (event_id, trace_id, span_id, parent_span_id, timestamp, event_type, actor, payload_json)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.trace_id,
                    event.span_id,
                    event.parent_span_id,
                    event.timestamp,
                    event.event_type,
                    event.actor,
                    dumps_json(event.payload),
                ),
            )
            materialize_event(self._conn, event)
            self._conn.commit()

    def list_traces(self, limit: int = 50) -> list[TraceSummary]:
        with self._lock:
            rows = self._conn.execute(
                """
                select trace_id, name, status, started_at, ended_at, error_json
                from workflows
                order by started_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [
            TraceSummary(
                trace_id=row["trace_id"],
                name=row["name"],
                status=row["status"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                error=loads_json(row["error_json"]),
            )
            for row in rows
        ]

    def get_trace(self, trace_id: str) -> JsonObject | None:
        with self._lock:
            row = self._conn.execute(
                """
                select trace_id, name, status, started_at, ended_at, input_json, output_json, error_json
                from workflows
                where trace_id = ?
                """,
                (trace_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "trace_id": row["trace_id"],
            "name": row["name"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "input": loads_json(row["input_json"]),
            "output": loads_json(row["output_json"]),
            "error": loads_json(row["error_json"]),
        }

    def list_events(self, trace_id: str) -> list[JsonObject]:
        with self._lock:
            rows = self._conn.execute(
                """
                select event_id, trace_id, span_id, parent_span_id, timestamp, event_type, actor, payload_json
                from events
                where trace_id = ?
                order by timestamp asc, rowid asc
                """,
                (trace_id,),
            ).fetchall()
        events: list[JsonObject] = []
        for row in rows:
            events.append(
                {
                    "event_id": row["event_id"],
                    "trace_id": row["trace_id"],
                    "span_id": row["span_id"],
                    "parent_span_id": row["parent_span_id"],
                    "timestamp": row["timestamp"],
                    "event_type": row["event_type"],
                    "actor": row["actor"],
                    "payload": safe_json(loads_json(row["payload_json"])),
                }
            )
        return events

    def list_all_events(self, limit: int | None = None) -> list[JsonObject]:
        sql = """
            select event_id, trace_id, span_id, parent_span_id, timestamp, event_type, actor, payload_json
            from events
            order by timestamp asc, rowid asc
        """
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " limit ?"
            params = (limit,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "trace_id": row["trace_id"],
                "span_id": row["span_id"],
                "parent_span_id": row["parent_span_id"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "payload": safe_json(loads_json(row["payload_json"])),
            }
            for row in rows
        ]

    def save_memory(self, agent: str, namespace: str, key: str, value: JsonValue, trace_id: str | None = None) -> int:
        now = utc_now()
        with self._lock:
            row = self._conn.execute(
                """
                select max(version) as version
                from memories
                where agent = ? and namespace = ? and key = ?
                """,
                (agent, namespace, key),
            ).fetchone()
            version = int(row["version"] or 0) + 1
            self._conn.execute(
                """
                insert into memories
                (agent, namespace, key, value_json, version, trace_id, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (agent, namespace, key, dumps_json(value), version, trace_id, now, now),
            )
            self._conn.commit()
            return version

    def get_memory(self, agent: str, namespace: str, key: str, version: int | None = None) -> JsonValue:
        sql = """
            select value_json
            from memories
            where agent = ? and namespace = ? and key = ?
        """
        params: tuple[object, ...]
        if version is None:
            sql += " order by version desc limit 1"
            params = (agent, namespace, key)
        else:
            sql += " and version = ? limit 1"
            params = (agent, namespace, key, version)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return loads_json(row["value_json"]) if row else None

    def list_memories(
        self,
        agent: str | None = None,
        namespace: str | None = None,
        limit: int = 100,
    ) -> list[JsonObject]:
        conditions: list[str] = []
        params: list[object] = []
        if agent is not None:
            conditions.append("agent = ?")
            params.append(agent)
        if namespace is not None:
            conditions.append("namespace = ?")
            params.append(namespace)
        where = f" where {' and '.join(conditions)}" if conditions else ""
        with self._lock:
            rows = self._conn.execute(
                f"""
                select agent, namespace, key, value_json, version, trace_id, created_at, updated_at
                from memories
                {where}
                order by updated_at desc, id desc
                limit ?
                """,
                (*params, limit),
            ).fetchall()
        return [
            {
                "agent": row["agent"],
                "namespace": row["namespace"],
                "key": row["key"],
                "value": loads_json(row["value_json"]),
                "version": row["version"],
                "trace_id": row["trace_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def list_memory_versions(self, agent: str, namespace: str, key: str) -> list[JsonObject]:
        with self._lock:
            rows = self._conn.execute(
                """
                select version, trace_id, created_at, updated_at, value_json
                from memories
                where agent = ? and namespace = ? and key = ?
                order by version asc
                """,
                (agent, namespace, key),
            ).fetchall()
        return [
            {
                "version": row["version"],
                "trace_id": row["trace_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "value": loads_json(row["value_json"]),
            }
            for row in rows
        ]

    def audit(self, trace_id: str | None, actor: str, action: str, resource: str, payload: JsonObject) -> None:
        with self._lock:
            self._conn.execute(
                """
                insert into audit_logs (trace_id, actor, action, resource, payload_json, timestamp)
                values (?, ?, ?, ?, ?, ?)
                """,
                (trace_id, actor, action, resource, dumps_json(payload), utc_now()),
            )
            self._conn.commit()

    def save_prompt_version(
        self,
        trace_id: str | None,
        agent: str,
        task_id: str | None,
        system_prompt: str | None,
        user_prompt: str,
        metadata: JsonObject | None = None,
    ) -> str:
        from agentmesh.types import has_redactions, new_id, redact_secrets, stable_hash

        prompt_id = new_id("prompt")
        safe_system = redact_secrets(system_prompt) if system_prompt is not None else None
        safe_user = redact_secrets(user_prompt)
        redacted = has_redactions(safe_system) or has_redactions(safe_user)
        rendered_system = str(safe_system) if safe_system is not None else None
        rendered_user = str(safe_user)
        prompt_hash = stable_hash(f"{rendered_system or ''}\n{rendered_user}")
        with self._lock:
            self._conn.execute(
                """
                insert into prompt_versions
                (prompt_id, trace_id, agent, task_id, prompt_hash, system_prompt, user_prompt, metadata_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt_id,
                    trace_id,
                    agent,
                    task_id,
                    prompt_hash,
                    rendered_system,
                    rendered_user,
                    dumps_json(metadata or {}),
                    utc_now(),
                ),
            )
            if redacted:
                self._conn.execute(
                    """
                    insert into audit_logs (trace_id, actor, action, resource, payload_json, timestamp)
                    values (?, ?, 'secret.redacted', 'prompt.version', ?, ?)
                    """,
                    (trace_id, agent, dumps_json({"prompt_id": prompt_id, "redacted": True}), utc_now()),
                )
            self._conn.execute(
                """
                insert into audit_logs (trace_id, actor, action, resource, payload_json, timestamp)
                values (?, ?, 'prompt.changed', ?, ?, ?)
                """,
                (trace_id, agent, prompt_id, dumps_json({"task_id": task_id, "prompt_hash": prompt_hash}), utc_now()),
            )
            self._conn.commit()
        return prompt_id

    def list_prompt_versions(self, trace_id: str | None = None, limit: int = 100) -> list[JsonObject]:
        sql = """
            select prompt_id, trace_id, agent, task_id, prompt_hash, system_prompt, user_prompt, metadata_json, created_at
            from prompt_versions
        """
        params: tuple[object, ...] = ()
        if trace_id is not None:
            sql += " where trace_id = ?"
            params = (trace_id,)
        sql += " order by created_at desc limit ?"
        params = (*params, limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            {
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
            for row in rows
        ]

    def create_approval(self, trace_id: str | None, agent: str, tool: str, arguments: JsonObject) -> str:
        from agentmesh.types import new_id

        approval_id = new_id("approval")
        with self._lock:
            self._conn.execute(
                """
                insert into approvals
                (approval_id, trace_id, agent, tool, arguments_json, status, reason, created_at, resolved_at)
                values (?, ?, ?, ?, ?, 'pending', null, ?, null)
                """,
                (approval_id, trace_id, agent, tool, dumps_json(arguments), utc_now()),
            )
            self._conn.commit()
        return approval_id

    def resolve_approval(self, approval_id: str, approved: bool, reason: str | None = None) -> None:
        status = "approved" if approved else "rejected"
        with self._lock:
            self._conn.execute(
                """
                update approvals
                set status = ?, reason = ?, resolved_at = ?
                where approval_id = ?
                """,
                (status, reason, utc_now(), approval_id),
            )
            self._conn.commit()

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[JsonObject]:
        sql = """
            select approval_id, trace_id, agent, tool, arguments_json, status, reason, created_at, resolved_at
            from approvals
        """
        params: tuple[object, ...] = ()
        if status is not None:
            sql += " where status = ?"
            params = (status,)
        sql += " order by created_at desc limit ?"
        params = (*params, limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "approval_id": row["approval_id"],
                "trace_id": row["trace_id"],
                "agent": row["agent"],
                "tool": row["tool"],
                "arguments": loads_json(row["arguments_json"]),
                "status": row["status"],
                "reason": row["reason"],
                "created_at": row["created_at"],
                "resolved_at": row["resolved_at"],
            }
            for row in rows
        ]

    def get_task_result(self, idempotency_key: str) -> JsonValue:
        with self._lock:
            row = self._conn.execute(
                """
                select value_json
                from task_results
                where idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        return loads_json(row["value_json"]) if row else None

    def save_task_result(self, idempotency_key: str, trace_id: str, task_id: str, value: JsonValue) -> None:
        with self._lock:
            self._conn.execute(
                """
                insert or replace into task_results
                (idempotency_key, trace_id, task_id, value_json, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (idempotency_key, trace_id, task_id, dumps_json(value), utc_now()),
            )
            self._conn.commit()

    def list_audit_logs(self, trace_id: str | None = None, limit: int = 100) -> list[JsonObject]:
        sql = """
            select trace_id, actor, action, resource, payload_json, timestamp
            from audit_logs
        """
        params: tuple[object, ...] = ()
        if trace_id is not None:
            sql += " where trace_id = ?"
            params = (trace_id,)
        sql += " order by timestamp desc limit ?"
        params = (*params, limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
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

    def add_document(
        self,
        document_id: str,
        source: str,
        content: str,
        metadata: JsonObject,
        embedding: list[float],
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                insert or replace into documents
                (id, source, content, metadata_json, embedding_json, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (document_id, source, content, dumps_json(metadata), dumps_json(embedding), utc_now()),
            )
            self._conn.commit()

    def list_documents(self) -> list[JsonObject]:
        with self._lock:
            rows = self._conn.execute(
                """
                select id, source, content, metadata_json, embedding_json, created_at
                from documents
                order by created_at asc
                """
            ).fetchall()
        documents: list[JsonObject] = []
        for row in rows:
            documents.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "content": row["content"],
                    "metadata": loads_json(row["metadata_json"]),
                    "embedding": loads_json(row["embedding_json"]),
                    "created_at": row["created_at"],
                }
            )
        return documents

    def save_checkpoint(
        self,
        trace_id: str,
        checkpoint_type: str,
        state: JsonValue,
        step_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> str:
        from agentmesh.types import new_id

        resolved_id = checkpoint_id or new_id("ckpt")
        with self._lock:
            self._conn.execute(
                """
                insert or replace into checkpoints
                (checkpoint_id, trace_id, step_id, checkpoint_type, state_json, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (resolved_id, trace_id, step_id, checkpoint_type, dumps_json(state), utc_now()),
            )
            self._conn.commit()
        return resolved_id

    def list_checkpoints(self, trace_id: str) -> list[JsonObject]:
        with self._lock:
            rows = self._conn.execute(
                """
                select checkpoint_id, trace_id, step_id, checkpoint_type, state_json, created_at
                from checkpoints
                where trace_id = ?
                order by created_at asc, rowid asc
                """,
                (trace_id,),
            ).fetchall()
        return [_checkpoint_row_to_json(row) for row in rows]

    def get_checkpoint(self, checkpoint_id: str) -> JsonObject | None:
        with self._lock:
            row = self._conn.execute(
                """
                select checkpoint_id, trace_id, step_id, checkpoint_type, state_json, created_at
                from checkpoints
                where checkpoint_id = ?
                """,
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            return None
        return _checkpoint_row_to_json(row)

    def list_observable_traces(
        self,
        limit: int = 100,
        filters: dict[str, object] | None = None,
        offset: int = 0,
    ) -> list[JsonObject]:
        from agentmesh.observability import list_traces

        with self._lock:
            return list_traces(self._conn, limit, filters, offset)

    def get_observable_trace(self, trace_id: str) -> JsonObject | None:
        from agentmesh.observability import get_trace

        with self._lock:
            return get_trace(self._conn, trace_id)

    def list_spans(self, trace_id: str) -> list[JsonObject]:
        from agentmesh.observability import list_spans

        with self._lock:
            return list_spans(self._conn, trace_id)

    def list_model_calls(self, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
        from agentmesh.observability import list_model_calls

        with self._lock:
            return list_model_calls(self._conn, trace_id, limit)

    def list_tool_calls(self, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
        from agentmesh.observability import list_tool_calls

        with self._lock:
            return list_tool_calls(self._conn, trace_id, limit)

    def get_tool_call(self, tool_call_id: str) -> JsonObject | None:
        from agentmesh.observability import get_tool_call

        with self._lock:
            return get_tool_call(self._conn, tool_call_id)

    def list_memory_operations(self, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
        from agentmesh.observability import list_memory_operations

        with self._lock:
            return list_memory_operations(self._conn, trace_id, limit)

    def list_rag_retrievals(self, trace_id: str | None = None, limit: int = 200) -> list[JsonObject]:
        from agentmesh.observability import list_rag_retrievals

        with self._lock:
            return list_rag_retrievals(self._conn, trace_id, limit)

    def get_rag_retrieval(self, retrieval_id: str) -> JsonObject | None:
        from agentmesh.observability import get_rag_retrieval

        with self._lock:
            return get_rag_retrieval(self._conn, retrieval_id)

    def overview(self) -> JsonObject:
        from agentmesh.observability import overview

        with self._lock:
            return overview(self._conn)

    def overview_timeseries(self) -> JsonObject:
        from agentmesh.observability import overview_timeseries

        with self._lock:
            return overview_timeseries(self._conn)

    def list_workflows(self) -> list[JsonObject]:
        from agentmesh.observability import list_workflows

        with self._lock:
            return list_workflows(self._conn)

    def get_workflow(self, workflow_id: str) -> JsonObject | None:
        from agentmesh.observability import get_workflow

        with self._lock:
            return get_workflow(self._conn, workflow_id)

    def list_workflow_runs(self, workflow_id: str) -> list[JsonObject]:
        from agentmesh.observability import workflow_runs

        with self._lock:
            return workflow_runs(self._conn, workflow_id)

    def workflow_graph(self, workflow_id: str) -> JsonObject:
        from agentmesh.observability import workflow_graph

        with self._lock:
            return workflow_graph(self._conn, workflow_id)

    def list_agents(self) -> list[JsonObject]:
        from agentmesh.observability import list_agents

        with self._lock:
            return list_agents(self._conn)

    def get_agent(self, agent_id: str) -> JsonObject | None:
        from agentmesh.observability import get_agent

        with self._lock:
            return get_agent(self._conn, agent_id)

    def list_agent_runs(self, agent_id: str) -> list[JsonObject]:
        from agentmesh.observability import agent_runs

        with self._lock:
            return agent_runs(self._conn, agent_id)

    def list_agent_messages(self, agent_id: str) -> list[JsonObject]:
        from agentmesh.observability import agent_messages

        with self._lock:
            return agent_messages(self._conn, agent_id)

    def list_provider_health(self) -> list[JsonObject]:
        from agentmesh.observability import list_provider_health

        with self._lock:
            return list_provider_health(self._conn)

    def list_models(self) -> list[JsonObject]:
        from agentmesh.observability import list_models

        with self._lock:
            return list_models(self._conn)

    def cost_summary(self) -> JsonObject:
        from agentmesh.observability import cost_summary

        with self._lock:
            return cost_summary(self._conn)

    def cost_by_dimension(self, dimension: str) -> list[JsonObject]:
        from agentmesh.observability import cost_by_dimension

        with self._lock:
            return cost_by_dimension(self._conn, dimension)

    def cost_by_failed_run(self) -> list[JsonObject]:
        from agentmesh.observability import cost_by_failed_run

        with self._lock:
            return cost_by_failed_run(self._conn)

    def list_prompts(self) -> list[JsonObject]:
        from agentmesh.observability import list_prompts

        with self._lock:
            return list_prompts(self._conn)

    def prompt_versions_for_prompt(self, prompt_id: str) -> list[JsonObject]:
        from agentmesh.observability import prompt_versions

        with self._lock:
            return prompt_versions(self._conn, prompt_id)

    def compare_prompts(self, left: str, right: str) -> JsonObject:
        from agentmesh.observability import compare_prompts

        with self._lock:
            return compare_prompts(self._conn, left, right)

    def list_evaluations(self) -> list[JsonObject]:
        from agentmesh.observability import list_evaluations

        with self._lock:
            return list_evaluations(self._conn)

    def evaluation_summary(self) -> JsonObject:
        from agentmesh.observability import evaluation_summary

        with self._lock:
            return evaluation_summary(self._conn)

    def save_evaluation(self, payload: JsonObject) -> JsonObject:
        from agentmesh.observability import save_evaluation

        with self._lock:
            result = save_evaluation(self._conn, payload)
            self._conn.commit()
            return result

    def create_replay(self, trace_id: str, span_id: str | None, mode: str, result: JsonObject) -> JsonObject:
        from agentmesh.observability import create_replay

        with self._lock:
            replay = create_replay(self._conn, trace_id, span_id, mode, result)
            self._conn.execute(
                """
                insert into audit_logs (trace_id, actor, action, resource, payload_json, timestamp)
                values (?, 'system', 'replay.started', ?, ?, ?)
                """,
                (trace_id, mode, dumps_json({"span_id": span_id, "replay_id": replay.get("replay_id")}), utc_now()),
            )
            self._conn.commit()
            return replay

    def list_replay_runs(self) -> list[JsonObject]:
        from agentmesh.observability import list_replay_runs

        with self._lock:
            return list_replay_runs(self._conn)

    def get_replay_run(self, replay_id: str) -> JsonObject | None:
        from agentmesh.observability import get_replay

        with self._lock:
            return get_replay(self._conn, replay_id)

    def export_trace(self, trace_id: str) -> JsonObject:
        trace = self.get_trace(trace_id)
        if trace is None:
            return {"trace_id": trace_id, "found": False}
        self.audit(trace_id, "system", "trace.exported", trace_id, {"format": "json"})
        return {
            "trace_id": trace_id,
            "found": True,
            "trace": trace,
            "observable_trace": self.get_observable_trace(trace_id),
            "spans": self.list_spans(trace_id),
            "events": self.list_events(trace_id),
            "model_calls": self.list_model_calls(trace_id),
            "tool_calls": self.list_tool_calls(trace_id),
            "memory_operations": self.list_memory_operations(trace_id),
            "rag_retrievals": self.list_rag_retrievals(trace_id),
            "approvals": [approval for approval in self.list_approvals(limit=1000) if approval.get("trace_id") == trace_id],
            "checkpoints": self.list_checkpoints(trace_id),
            "audit_logs": self.list_audit_logs(trace_id),
            "prompt_versions": self.list_prompt_versions(trace_id),
        }

    def import_trace(self, payload: JsonObject) -> str:
        from agentmesh.observability import materialize_event, materialize_workflow_created, materialize_workflow_finished

        trace_value = payload.get("trace", {})
        if not isinstance(trace_value, dict):
            raise ValueError("Trace export payload is missing trace object")
        trace_id = str(trace_value.get("trace_id") or payload.get("trace_id") or "")
        if not trace_id:
            raise ValueError("Trace export payload is missing trace_id")
        with self._lock:
            self._conn.execute(
                """
                insert or replace into workflows
                (trace_id, name, status, started_at, ended_at, input_json, output_json, error_json)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    str(trace_value.get("name", "imported-trace")),
                    str(trace_value.get("status", "imported")),
                    str(trace_value.get("started_at") or utc_now()),
                    trace_value.get("ended_at") if isinstance(trace_value.get("ended_at"), str) else None,
                    dumps_json(trace_value.get("input")),
                    dumps_json(trace_value.get("output")),
                    dumps_json(trace_value.get("error")),
                ),
            )
            materialize_workflow_created(
                self._conn,
                trace_id,
                str(trace_value.get("name", "imported-trace")),
                trace_value.get("input"),
            )
            materialize_workflow_finished(
                self._conn,
                trace_id,
                str(trace_value.get("status", "imported")),
                trace_value.get("output"),
                trace_value.get("error"),
            )
            for raw_event in payload.get("events", []):
                if not isinstance(raw_event, dict):
                    continue
                event = EventRecord(
                    event_id=str(raw_event.get("event_id")),
                    trace_id=trace_id,
                    span_id=str(raw_event.get("span_id")),
                    parent_span_id=str(raw_event.get("parent_span_id")) if raw_event.get("parent_span_id") else None,
                    timestamp=str(raw_event.get("timestamp") or utc_now()),
                    event_type=str(raw_event.get("event_type")),
                    actor=str(raw_event.get("actor", "import")),
                    payload=safe_json(raw_event.get("payload", {})) if isinstance(raw_event.get("payload", {}), dict) else {},
                )
                self._conn.execute(
                    """
                    insert or replace into events
                    (event_id, trace_id, span_id, parent_span_id, timestamp, event_type, actor, payload_json)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.trace_id,
                        event.span_id,
                        event.parent_span_id,
                        event.timestamp,
                        event.event_type,
                        event.actor,
                        dumps_json(event.payload),
                    ),
                )
                materialize_event(self._conn, event)
            for raw_checkpoint in payload.get("checkpoints", []):
                if not isinstance(raw_checkpoint, dict):
                    continue
                self._conn.execute(
                    """
                    insert or replace into checkpoints
                    (checkpoint_id, trace_id, step_id, checkpoint_type, state_json, created_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(raw_checkpoint.get("checkpoint_id")),
                        trace_id,
                        raw_checkpoint.get("step_id") if isinstance(raw_checkpoint.get("step_id"), str) else None,
                        str(raw_checkpoint.get("checkpoint_type", "imported")),
                        dumps_json(raw_checkpoint.get("state")),
                        str(raw_checkpoint.get("created_at") or utc_now()),
                    ),
                )
            self._conn.commit()
        return trace_id


def _checkpoint_row_to_json(row: sqlite3.Row) -> JsonObject:
    return {
        "checkpoint_id": row["checkpoint_id"],
        "trace_id": row["trace_id"],
        "step_id": row["step_id"],
        "checkpoint_type": row["checkpoint_type"],
        "state": loads_json(row["state_json"]),
        "created_at": row["created_at"],
    }
