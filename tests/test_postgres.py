import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from agentmesh.dashboard import create_app
from agentmesh.demo import seed_demo_data
from agentmesh.postgres import PostgresConnection, Row, _convert
from agentmesh.stores import create_store
from tests.conftest import POSTGRES_URL, _reset_postgres

requires_postgres = pytest.mark.skipif(not POSTGRES_URL, reason="set AGENTMESH_TEST_POSTGRES_URL to run PostgreSQL tests")


def _translator(primary_keys):
    conn = PostgresConnection.__new__(PostgresConnection)
    conn._primary_keys = primary_keys
    conn._translations = {}
    return conn


def test_sqlite_dialect_translation():
    conn = _translator({"spans": ["span_id"], "budget_settings": ["scope", "scope_id"]})
    translate = conn._translate_uncached

    upsert = translate("insert or replace into spans (span_id, name, status) values (?, ?, 'ok')")
    assert upsert == (
        "insert into spans (span_id, name, status) values (%s, %s, 'ok')"
        " on conflict (span_id) do update set name = excluded.name, status = excluded.status"
    )
    assert translate("insert or ignore into budget_settings (scope, scope_id) values ('workspace', 'default')").endswith(
        "values ('workspace', 'default') on conflict do nothing"
    )
    # ? and % inside string literals are data, not placeholders; like becomes ilike outside literals only.
    assert translate("select * from spans where name like ? and note = 'what? 100% like'") == (
        "select * from spans where name ilike %s and note = 'what? 100%% like'"
    )
    assert translate("select rowid as _rowid from events order by timestamp asc, rowid asc") == (
        "select ctid as _rowid from events order by timestamp asc, ctid asc"
    )
    ddl = translate(
        "create table if not exists t (id integer primary key autoincrement, cost real not null default 0, "
        "n integer, trace_id text, foreign key(trace_id) references workflows(trace_id))"
    )
    assert ddl == "create table if not exists t (id bigserial primary key, cost double precision not null default 0, n bigint, trace_id text)"
    assert translate("alter table spans add column retries integer not null default 0") == (
        "alter table spans add column retries bigint not null default 0"
    )
    assert "information_schema.columns" in translate("pragma table_info(spans)")
    assert translate("pragma journal_mode = wal") is None

    row = Row(["n", "name"], {"n": 0, "name": 1}, [3, "x"])
    assert row["name"] == "x" and row[0] == 3 and row.keys() == ["n", "name"] and dict(zip(row.keys(), row, strict=True)) == {"n": 3, "name": "x"}
    from decimal import Decimal

    assert _convert(Decimal("4")) == 4 and isinstance(_convert(Decimal("4")), int)
    assert _convert(Decimal("0.25")) == 0.25


@requires_postgres
def test_postgres_matches_sqlite_across_the_api(tmp_path):
    _reset_postgres(POSTGRES_URL)
    sqlite_path = str(tmp_path / "parity.db")
    seed_demo_data(sqlite_path, reset=True)
    seed_demo_data(POSTGRES_URL, reset=True)
    sqlite = TestClient(create_app(sqlite_path))
    postgres_app = create_app(POSTGRES_URL)
    postgres = TestClient(postgres_app, raise_server_exceptions=False)

    def shape(client, path):
        response = client.get(path)
        assert response.status_code == 200, f"{path}: {response.text[:300]}"
        return response.json()

    def ordered(client):
        return sorted(shape(client, "/api/traces"), key=lambda trace: (trace["workflow_name"], json.dumps(trace["input"], sort_keys=True), trace["started_at"]))

    # Demo trace ids are random, so pair the two databases' traces by name and order.
    pairs = list(zip(ordered(sqlite), ordered(postgres), strict=True))
    assert len(pairs) == 26  # 18 demo traces (incl. 8 swarm traces) plus 2 experiments x 4 items
    assert [(a["workflow_name"], a["status"], a["span_count"]) for a, _ in pairs] == [
        (b["workflow_name"], b["status"], b["span_count"]) for _, b in pairs
    ]
    same = ["session_id", "agent_id", "workflow_id"]
    ids = {
        key: (shape(sqlite, f"/api/{collection}")[0][key], shape(postgres, f"/api/{collection}")[0][key])
        for key, collection in zip(same, ["sessions", "agents", "workflows"], strict=True)
    }
    paths = [
        ("/api/overview", "/api/overview"), ("/api/overview/timeseries",) * 2, ("/api/traces?status=failed",) * 2,
        ("/api/traces?min_cost=0.00001&q=a",) * 2, ("/api/traces?workflow=Support&tag=beta",) * 2, ("/api/scores",) * 2,
        ("/api/workflows",) * 2, ("/api/agents",) * 2, ("/api/models",) * 2, ("/api/providers/health",) * 2,
        ("/api/costs/summary",) * 2, ("/api/costs/by-model",) * 2, ("/api/costs/by-failed-run",) * 2, ("/api/tool-calls",) * 2,
        ("/api/memory/operations",) * 2, ("/api/rag/retrievals",) * 2, ("/api/prompts",) * 2, ("/api/approvals",) * 2,
        ("/api/evaluations/summary",) * 2, ("/api/datasets",) * 2, ("/api/experiments",) * 2, ("/api/alerts/rules",) * 2,
        ("/api/policies",) * 2, ("/api/policy-decisions",) * 2, ("/api/guardrails/summary",) * 2, ("/api/halts?active=false",) * 2,
        ("/api/swarms",) * 2,
        tuple(f"/api/sessions/{value}" for value in ids["session_id"]),
        tuple(f"/api/agents/{value}/runs" for value in ids["agent_id"]),
        tuple(f"/api/workflows/{value}/graph" for value in ids["workflow_id"]),
    ]
    swarm_pairs = zip(
        sorted(shape(sqlite, "/api/swarms"), key=lambda item: item["name"]),
        sorted(shape(postgres, "/api/swarms"), key=lambda item: item["name"]),
        strict=True,
    )
    for left_swarm, right_swarm in swarm_pairs:
        left_detail = shape(sqlite, f"/api/swarms/{left_swarm['swarm_id']}")
        right_detail = shape(postgres, f"/api/swarms/{right_swarm['swarm_id']}")
        for key in ("status", "agents", "roles", "max_depth", "max_fan_out", "failed_agents", "messages", "handoffs"):
            assert left_detail["summary"][key] == right_detail["summary"][key], (left_swarm["name"], key)
    for left_trace, right_trace in pairs:
        for suffix in ("", "/spans", "/events", "/insights"):
            paths.append((f"/api/traces/{left_trace['trace_id']}{suffix}", f"/api/traces/{right_trace['trace_id']}{suffix}"))
    for left_path, right_path in paths:
        left, right = shape(sqlite, left_path), shape(postgres, right_path)
        path = left_path
        if path == "/api/overview":
            for key in ("runs_today", "failure_rate", "total_tokens"):
                assert left[key] == right[key], key
            assert left["total_cost"] == pytest.approx(right["total_cost"])
        elif path.endswith("/insights"):
            assert [f["kind"] for f in left["findings"]] == [f["kind"] for f in right["findings"]], path
        elif isinstance(left, list):
            assert len(left) == len(right), path
    # Reads never leave a transaction open on the shared connection.
    assert postgres_app.state.store._conn._in_transaction is False


@requires_postgres
def test_legacy_postgres_schema_is_upgraded():
    import psycopg

    _reset_postgres(POSTGRES_URL)
    with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
        conn.execute(
            "create table workflows (trace_id text primary key, name text not null, status text not null, started_at text not null,"
            " ended_at text, input_json jsonb, output_json jsonb, error_json jsonb)"
        )
        conn.execute(
            "create table events (event_id text primary key, trace_id text not null references workflows(trace_id), span_id text not null,"
            " parent_span_id text, timestamp text not null, event_type text not null, actor text not null, payload_json jsonb not null)"
        )
        conn.execute("insert into workflows values ('t1', 'legacy', 'succeeded', '2026-01-01T00:00:00+00:00', null, '{\"q\": 1}', null, null)")
        conn.execute("insert into events values ('e1', 't1', 's1', null, '2026-01-01T00:00:00+00:00', 'workflow.started', 'runtime', '{\"a\": [1, 2]}')")
        # Another application's table in the same schema must be left alone.
        conn.execute("create table billing_invoices (id int primary key, payload jsonb not null)")

    store = create_store(POSTGRES_URL)
    assert store.list_events("t1")[0]["payload"] == {"a": [1, 2]}
    assert store.get_trace("t1")["name"] == "legacy"
    with psycopg.connect(POSTGRES_URL) as conn:
        types = dict(conn.execute("select column_name, data_type from information_schema.columns where table_name = 'events'").fetchall())
        foreign_keys = conn.execute(
            "select count(*) from information_schema.table_constraints where table_name = 'events' and constraint_type = 'FOREIGN KEY'"
        ).fetchone()[0]
    assert types["payload_json"] == "text" and foreign_keys == 0
    with psycopg.connect(POSTGRES_URL) as conn:
        untouched = conn.execute(
            "select data_type from information_schema.columns where table_name = 'billing_invoices' and column_name = 'payload'"
        ).fetchone()[0]
    assert untouched == "jsonb"
    # The upgraded database accepts everything the SQLite store does, e.g. OTLP ingestion.
    from agentmesh.otlp import decode_json
    from tests.test_ingest_otlp import TRACE_ID, otlp, root_span

    store.ingest_spans(decode_json(otlp([root_span()])))
    assert store.get_observable_trace(TRACE_ID)["session_id"] == "session-42"
    store.close()


@requires_postgres
def test_cli_against_postgres():
    _reset_postgres(POSTGRES_URL)
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src"), "AGENTMESH_DB_URL": POSTGRES_URL}

    def cli(*args):
        completed = subprocess.run([sys.executable, "-m", "agentmesh.cli", *args], capture_output=True, text=True, env=env, timeout=180)
        assert completed.returncode == 0, completed.stderr
        return completed.stdout

    assert json.loads(cli("demo", "seed", "--reset"))["traces_seeded"] == 12
    assert len(json.loads(cli("traces", "list", "--limit", "50"))) == 26
    assert json.loads(cli("sessions", "list"))[0]["trace_count"] == 3
    doctor = json.loads(cli("doctor"))
    assert doctor["database_readable"] is True and doctor["trace_count"] >= 6
    pruned = json.loads(cli("traces", "prune", "--older-than", "3650d", "--dry-run"))
    assert pruned["dry_run"] is True
