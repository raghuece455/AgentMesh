"""How each table's rows change, and therefore what a storage backend has to support.

SQLite and PostgreSQL rewrite a row in place for free, so nothing in AgentMesh had to say out loud
how a table's rows change over time. A column store does not: ClickHouse has no cheap in-place
update, and deduplicating by key costs a merge on read. Before a backend like that can be written,
each table has to declare which of three contracts it needs.

``APPEND``
    Rows accumulate and are folded when they are read. Two rows with the same identity are
    *meaningful*, not a mistake, so a backend must never deduplicate them. :data:`swarms` is the
    case to keep in mind: every ingest batch appends what it saw, and
    :data:`agentmesh.swarms.SWARM_ROLLUP` takes the earliest start, the latest end, and any name.

``REPLACE``
    One row per primary key, whole rows, last write wins — what ``insert or replace``,
    ``insert or ignore``, and ``on conflict do update`` all ask for. A span delivered while it was
    still running and again once it finished is the same row twice, and the second delivery has to
    win. On ClickHouse this is ``ReplacingMergeTree`` and a ``FINAL`` on reads, which is a
    correctness requirement rather than a tuning choice.

``MUTATE``
    Some columns are rewritten after the row was written, which no other contract can express. On a
    column store each one is a real mutation, so these want to stay small and off the hot path.
    Nothing written per span or per trace needs this: where the caller has the row in hand it uses
    :func:`agentmesh.observability.write_row` and writes all of it.

The point of writing it down is that :mod:`tests.test_backends` checks it against the code: every
table is classified, and a statement that rewrites a table in place has to be one the table admits
to. Adding a table, or an ``update`` to a table that did not have one, fails until it is declared.
"""

from __future__ import annotations

APPEND = "append"
REPLACE = "replace"
MUTATE = "mutate"

TABLE_WRITES: dict[str, str] = {
    # Telemetry: written once per span, trace, or call, and the bulk of the rows.
    "spans": REPLACE,
    "events": REPLACE,
    "cost_records": REPLACE,
    "model_calls": REPLACE,
    "tool_calls": REPLACE,
    "memory_operations": REPLACE,
    "rag_retrievals": REPLACE,
    "resource_access": REPLACE,
    "policy_decisions": REPLACE,
    "agents": REPLACE,
    "tasks": REPLACE,
    "audit_logs": APPEND,
    "prompt_versions": APPEND,
    # The run itself. Both ingest and the runtime write whole rows, so finishing a run supersedes
    # the row rather than patching it.
    "traces": REPLACE,
    "workflow_runs": REPLACE,
    "workflows": REPLACE,
    "workflows_catalog": REPLACE,
    # Swarms. ``swarms`` is the one table whose duplicate-looking rows carry information.
    "swarms": APPEND,
    "swarm_traces": REPLACE,
    "span_links": REPLACE,
    "agent_messages_log": REPLACE,
    # Control plane: small, edited by people or by a scheduler, read far more often than written.
    "policies": MUTATE,
    "policy_halts": MUTATE,
    "approvals": MUTATE,
    "alert_rules": MUTATE,
    "alert_events": MUTATE,
    "datasets": MUTATE,
    "dataset_items": REPLACE,
    "experiments": REPLACE,
    "experiment_results": REPLACE,
    "evaluations": REPLACE,
    "documents": REPLACE,
    "memories": APPEND,
    "checkpoints": REPLACE,
    "replay_runs": REPLACE,
    "replay_checkpoints": REPLACE,
    "task_results": REPLACE,
    "provider_health": MUTATE,
    "budget_settings": REPLACE,
    "schema_migrations": REPLACE,
}

# Written once per span or per trace, so the write contract decides whether a backend keeps up.
# Everything else is edited by hand or by a scheduler and stays small whatever the traffic.
HOT_TABLES = frozenset({
    "spans",
    "events",
    "cost_records",
    "model_calls",
    "tool_calls",
    "memory_operations",
    "rag_retrievals",
    "resource_access",
    "policy_decisions",
    "span_links",
    "agent_messages_log",
    "swarms",
    "swarm_traces",
    "traces",
    "workflow_runs",
})


def write_mode(table: str) -> str:
    """The contract ``table`` needs, or ``KeyError`` if nobody has decided yet."""
    return TABLE_WRITES[table]


def tables_with(mode: str) -> set[str]:
    """Every table needing ``mode``."""
    return {table for table, value in TABLE_WRITES.items() if value == mode}
