from __future__ import annotations

from dataclasses import dataclass, field

from agentmesh.dependencies import optional_import
from agentmesh.storage import EventRecord, TraceSummary
from agentmesh.types import JsonObject, JsonValue, dumps_json, loads_json, safe_json, utc_now


@dataclass(slots=True)
class PostgreSQLStore:
    dsn: str
    _psycopg: object = field(init=False, repr=False)
    _conn: object = field(init=False, repr=False)

    def __post_init__(self) -> None:
        psycopg = optional_import("psycopg", "postgres")
        self._psycopg = psycopg
        self._conn = psycopg.connect(self.dsn)
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        statements = [
            """
            create table if not exists workflows (
              trace_id text primary key,
              name text not null,
              status text not null,
              started_at text not null,
              ended_at text,
              input_json jsonb,
              output_json jsonb,
              error_json jsonb
            )
            """,
            """
            create table if not exists events (
              event_id text primary key,
              trace_id text not null references workflows(trace_id),
              span_id text not null,
              parent_span_id text,
              timestamp text not null,
              event_type text not null,
              actor text not null,
              payload_json jsonb not null
            )
            """,
            "create index if not exists idx_events_trace_time on events(trace_id, timestamp)",
            """
            create table if not exists memories (
              id bigserial primary key,
              agent text not null,
              namespace text not null,
              key text not null,
              value_json jsonb not null,
              version integer not null,
              trace_id text,
              created_at text not null,
              updated_at text not null
            )
            """,
            "create index if not exists idx_memories_lookup on memories(agent, namespace, key, version)",
            """
            create table if not exists audit_logs (
              id bigserial primary key,
              trace_id text,
              actor text not null,
              action text not null,
              resource text not null,
              payload_json jsonb not null,
              timestamp text not null
            )
            """,
            """
            create table if not exists documents (
              id text primary key,
              source text not null,
              content text not null,
              metadata_json jsonb not null,
              embedding_json jsonb not null,
              created_at text not null
            )
            """,
            """
            create table if not exists checkpoints (
              checkpoint_id text primary key,
              trace_id text not null references workflows(trace_id),
              step_id text,
              checkpoint_type text not null,
              state_json jsonb not null,
              created_at text not null
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
              metadata_json jsonb not null,
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
              arguments_json jsonb not null,
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
              value_json jsonb not null,
              created_at text not null
            )
            """,
        ]
        with self._conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        self._conn.commit()

    def create_workflow(self, trace_id: str, name: str, input_value: JsonValue) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                insert into workflows
                (trace_id, name, status, started_at, ended_at, input_json, output_json, error_json)
                values (%s, %s, %s, %s, null, %s::jsonb, null, null)
                on conflict (trace_id) do update
                set name = excluded.name, status = excluded.status, started_at = excluded.started_at,
                    ended_at = null, input_json = excluded.input_json, output_json = null, error_json = null
                """,
                (trace_id, name, "running", utc_now(), dumps_json(input_value)),
            )
        self._conn.commit()

    def finish_workflow(
        self,
        trace_id: str,
        status: str,
        output_value: JsonValue | None = None,
        error_value: JsonValue | None = None,
    ) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                update workflows
                set status = %s, ended_at = %s, output_json = %s::jsonb, error_json = %s::jsonb
                where trace_id = %s
                """,
                (status, utc_now(), dumps_json(output_value), dumps_json(error_value), trace_id),
            )
        self._conn.commit()

    def record_event(self, event: EventRecord) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                insert into events
                (event_id, trace_id, span_id, parent_span_id, timestamp, event_type, actor, payload_json)
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
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
        self._conn.commit()

    def list_traces(self, limit: int = 50) -> list[TraceSummary]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                select trace_id, name, status, started_at, ended_at, error_json::text
                from workflows
                order by started_at desc
                limit %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        return [
            TraceSummary(row[0], row[1], row[2], row[3], row[4], loads_json(row[5]))
            for row in rows
        ]

    def get_trace(self, trace_id: str) -> JsonObject | None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                select trace_id, name, status, started_at, ended_at, input_json::text, output_json::text, error_json::text
                from workflows
                where trace_id = %s
                """,
                (trace_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "trace_id": row[0],
            "name": row[1],
            "status": row[2],
            "started_at": row[3],
            "ended_at": row[4],
            "input": loads_json(row[5]),
            "output": loads_json(row[6]),
            "error": loads_json(row[7]),
        }

    def list_events(self, trace_id: str) -> list[JsonObject]:
        return self._events("where trace_id = %s", (trace_id,), None)

    def list_all_events(self, limit: int | None = None) -> list[JsonObject]:
        return self._events("", (), limit)

    def _events(self, where_clause: str, params: tuple[object, ...], limit: int | None) -> list[JsonObject]:
        limit_clause = "limit %s" if limit is not None else ""
        resolved_params = (*params, limit) if limit is not None else params
        with self._conn.cursor() as cursor:
            cursor.execute(
                f"""
                select event_id, trace_id, span_id, parent_span_id, timestamp, event_type, actor, payload_json::text
                from events
                {where_clause}
                order by timestamp asc
                {limit_clause}
                """,
                resolved_params,
            )
            rows = cursor.fetchall()
        return [
            {
                "event_id": row[0],
                "trace_id": row[1],
                "span_id": row[2],
                "parent_span_id": row[3],
                "timestamp": row[4],
                "event_type": row[5],
                "actor": row[6],
                "payload": safe_json(loads_json(row[7])),
            }
            for row in rows
        ]

    def save_memory(self, agent: str, namespace: str, key: str, value: JsonValue, trace_id: str | None = None) -> int:
        with self._conn.cursor() as cursor:
            cursor.execute(
                "select coalesce(max(version), 0) + 1 from memories where agent = %s and namespace = %s and key = %s",
                (agent, namespace, key),
            )
            version = int(cursor.fetchone()[0])
            now = utc_now()
            cursor.execute(
                """
                insert into memories
                (agent, namespace, key, value_json, version, trace_id, created_at, updated_at)
                values (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                """,
                (agent, namespace, key, dumps_json(value), version, trace_id, now, now),
            )
        self._conn.commit()
        return version

    def get_memory(self, agent: str, namespace: str, key: str, version: int | None = None) -> JsonValue:
        sql = "select value_json::text from memories where agent = %s and namespace = %s and key = %s"
        params: tuple[object, ...] = (agent, namespace, key)
        if version is None:
            sql += " order by version desc limit 1"
        else:
            sql += " and version = %s limit 1"
            params = (*params, version)
        with self._conn.cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
        return loads_json(row[0]) if row else None

    def list_memories(
        self,
        agent: str | None = None,
        namespace: str | None = None,
        limit: int = 100,
    ) -> list[JsonObject]:
        conditions: list[str] = []
        params: list[object] = []
        if agent is not None:
            conditions.append("agent = %s")
            params.append(agent)
        if namespace is not None:
            conditions.append("namespace = %s")
            params.append(namespace)
        where = f"where {' and '.join(conditions)}" if conditions else ""
        with self._conn.cursor() as cursor:
            cursor.execute(
                f"""
                select agent, namespace, key, value_json::text, version, trace_id, created_at, updated_at
                from memories
                {where}
                order by updated_at desc, id desc
                limit %s
                """,
                (*params, limit),
            )
            rows = cursor.fetchall()
        return [
            {
                "agent": row[0],
                "namespace": row[1],
                "key": row[2],
                "value": loads_json(row[3]),
                "version": row[4],
                "trace_id": row[5],
                "created_at": row[6],
                "updated_at": row[7],
            }
            for row in rows
        ]

    def list_memory_versions(self, agent: str, namespace: str, key: str) -> list[JsonObject]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                select version, trace_id, created_at, updated_at, value_json::text
                from memories
                where agent = %s and namespace = %s and key = %s
                order by version asc
                """,
                (agent, namespace, key),
            )
            rows = cursor.fetchall()
        return [
            {"version": row[0], "trace_id": row[1], "created_at": row[2], "updated_at": row[3], "value": loads_json(row[4])}
            for row in rows
        ]

    def audit(self, trace_id: str | None, actor: str, action: str, resource: str, payload: JsonObject) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                insert into audit_logs (trace_id, actor, action, resource, payload_json, timestamp)
                values (%s, %s, %s, %s, %s::jsonb, %s)
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
        from agentmesh.types import new_id, stable_hash

        prompt_id = new_id("prompt")
        prompt_hash = stable_hash(f"{system_prompt or ''}\n{user_prompt}")
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                insert into prompt_versions
                (prompt_id, trace_id, agent, task_id, prompt_hash, system_prompt, user_prompt, metadata_json, created_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (prompt_id, trace_id, agent, task_id, prompt_hash, system_prompt, user_prompt, dumps_json(metadata or {}), utc_now()),
            )
        self._conn.commit()
        return prompt_id

    def list_prompt_versions(self, trace_id: str | None = None, limit: int = 100) -> list[JsonObject]:
        where = "where trace_id = %s" if trace_id else ""
        params: tuple[object, ...] = (trace_id, limit) if trace_id else (limit,)
        with self._conn.cursor() as cursor:
            cursor.execute(
                f"""
                select prompt_id, trace_id, agent, task_id, prompt_hash, system_prompt, user_prompt, metadata_json::text, created_at
                from prompt_versions
                {where}
                order by created_at desc
                limit %s
                """,
                params,
            )
            rows = cursor.fetchall()
        return [
            {
                "prompt_id": row[0],
                "trace_id": row[1],
                "agent": row[2],
                "task_id": row[3],
                "prompt_hash": row[4],
                "system_prompt": row[5],
                "user_prompt": row[6],
                "metadata": loads_json(row[7]),
                "created_at": row[8],
            }
            for row in rows
        ]

    def create_approval(self, trace_id: str | None, agent: str, tool: str, arguments: JsonObject) -> str:
        from agentmesh.types import new_id

        approval_id = new_id("approval")
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                insert into approvals
                (approval_id, trace_id, agent, tool, arguments_json, status, reason, created_at, resolved_at)
                values (%s, %s, %s, %s, %s::jsonb, 'pending', null, %s, null)
                """,
                (approval_id, trace_id, agent, tool, dumps_json(arguments), utc_now()),
            )
        self._conn.commit()
        return approval_id

    def resolve_approval(self, approval_id: str, approved: bool, reason: str | None = None) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                update approvals
                set status = %s, reason = %s, resolved_at = %s
                where approval_id = %s
                """,
                ("approved" if approved else "rejected", reason, utc_now(), approval_id),
            )
        self._conn.commit()

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[JsonObject]:
        where = "where status = %s" if status else ""
        params: tuple[object, ...] = (status, limit) if status else (limit,)
        with self._conn.cursor() as cursor:
            cursor.execute(
                f"""
                select approval_id, trace_id, agent, tool, arguments_json::text, status, reason, created_at, resolved_at
                from approvals
                {where}
                order by created_at desc
                limit %s
                """,
                params,
            )
            rows = cursor.fetchall()
        return [
            {
                "approval_id": row[0],
                "trace_id": row[1],
                "agent": row[2],
                "tool": row[3],
                "arguments": loads_json(row[4]),
                "status": row[5],
                "reason": row[6],
                "created_at": row[7],
                "resolved_at": row[8],
            }
            for row in rows
        ]

    def get_task_result(self, idempotency_key: str) -> JsonValue:
        with self._conn.cursor() as cursor:
            cursor.execute("select value_json::text from task_results where idempotency_key = %s", (idempotency_key,))
            row = cursor.fetchone()
        return loads_json(row[0]) if row else None

    def save_task_result(self, idempotency_key: str, trace_id: str, task_id: str, value: JsonValue) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                insert into task_results (idempotency_key, trace_id, task_id, value_json, created_at)
                values (%s, %s, %s, %s::jsonb, %s)
                on conflict (idempotency_key) do update
                set value_json = excluded.value_json
                """,
                (idempotency_key, trace_id, task_id, dumps_json(value), utc_now()),
            )
        self._conn.commit()

    def list_audit_logs(self, trace_id: str | None = None, limit: int = 100) -> list[JsonObject]:
        where = "where trace_id = %s" if trace_id else ""
        params: tuple[object, ...] = (trace_id, limit) if trace_id else (limit,)
        with self._conn.cursor() as cursor:
            cursor.execute(
                f"""
                select trace_id, actor, action, resource, payload_json::text, timestamp
                from audit_logs
                {where}
                order by timestamp desc
                limit %s
                """,
                params,
            )
            rows = cursor.fetchall()
        return [
            {"trace_id": row[0], "actor": row[1], "action": row[2], "resource": row[3], "payload": loads_json(row[4]), "timestamp": row[5]}
            for row in rows
        ]

    def add_document(self, document_id: str, source: str, content: str, metadata: JsonObject, embedding: list[float]) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                insert into documents (id, source, content, metadata_json, embedding_json, created_at)
                values (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                on conflict (id) do update
                set source = excluded.source, content = excluded.content,
                    metadata_json = excluded.metadata_json, embedding_json = excluded.embedding_json
                """,
                (document_id, source, content, dumps_json(metadata), dumps_json(embedding), utc_now()),
            )
        self._conn.commit()

    def list_documents(self) -> list[JsonObject]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                select id, source, content, metadata_json::text, embedding_json::text, created_at
                from documents
                order by created_at asc
                """
            )
            rows = cursor.fetchall()
        return [
            {"id": row[0], "source": row[1], "content": row[2], "metadata": loads_json(row[3]), "embedding": loads_json(row[4]), "created_at": row[5]}
            for row in rows
        ]

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
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                insert into checkpoints (checkpoint_id, trace_id, step_id, checkpoint_type, state_json, created_at)
                values (%s, %s, %s, %s, %s::jsonb, %s)
                on conflict (checkpoint_id) do update
                set state_json = excluded.state_json, checkpoint_type = excluded.checkpoint_type
                """,
                (resolved_id, trace_id, step_id, checkpoint_type, dumps_json(state), utc_now()),
            )
        self._conn.commit()
        return resolved_id

    def list_checkpoints(self, trace_id: str) -> list[JsonObject]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                select checkpoint_id, trace_id, step_id, checkpoint_type, state_json::text, created_at
                from checkpoints
                where trace_id = %s
                order by created_at asc
                """,
                (trace_id,),
            )
            rows = cursor.fetchall()
        return [_checkpoint_row(row) for row in rows]

    def get_checkpoint(self, checkpoint_id: str) -> JsonObject | None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                select checkpoint_id, trace_id, step_id, checkpoint_type, state_json::text, created_at
                from checkpoints
                where checkpoint_id = %s
                """,
                (checkpoint_id,),
            )
            row = cursor.fetchone()
        return _checkpoint_row(row) if row else None

    def export_trace(self, trace_id: str) -> JsonObject:
        trace = self.get_trace(trace_id)
        if trace is None:
            return {"trace_id": trace_id, "found": False}
        return {
            "trace_id": trace_id,
            "found": True,
            "trace": trace,
            "events": self.list_events(trace_id),
            "checkpoints": self.list_checkpoints(trace_id),
            "audit_logs": self.list_audit_logs(trace_id),
            "prompt_versions": self.list_prompt_versions(trace_id),
        }

    def import_trace(self, payload: JsonObject) -> str:
        trace_value = payload.get("trace", {})
        if not isinstance(trace_value, dict):
            raise ValueError("Trace export payload is missing trace object")
        trace_id = str(trace_value.get("trace_id") or payload.get("trace_id") or "")
        if not trace_id:
            raise ValueError("Trace export payload is missing trace_id")
        self.create_workflow(trace_id, str(trace_value.get("name", "imported-trace")), trace_value.get("input"))
        self.finish_workflow(trace_id, str(trace_value.get("status", "imported")), trace_value.get("output"), trace_value.get("error"))
        with self._conn.cursor() as cursor:
            for raw_event in payload.get("events", []):
                if not isinstance(raw_event, dict):
                    continue
                cursor.execute(
                    """
                    insert into events
                    (event_id, trace_id, span_id, parent_span_id, timestamp, event_type, actor, payload_json)
                    values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (event_id) do update set payload_json = excluded.payload_json
                    """,
                    (
                        str(raw_event.get("event_id")),
                        trace_id,
                        str(raw_event.get("span_id")),
                        raw_event.get("parent_span_id") if isinstance(raw_event.get("parent_span_id"), str) else None,
                        str(raw_event.get("timestamp") or utc_now()),
                        str(raw_event.get("event_type")),
                        str(raw_event.get("actor", "import")),
                        dumps_json(raw_event.get("payload", {})),
                    ),
                )
        self._conn.commit()
        return trace_id


def _checkpoint_row(row: tuple[object, ...]) -> JsonObject:
    return {
        "checkpoint_id": str(row[0]),
        "trace_id": str(row[1]),
        "step_id": str(row[2]) if row[2] is not None else None,
        "checkpoint_type": str(row[3]),
        "state": loads_json(str(row[4])),
        "created_at": str(row[5]),
    }
