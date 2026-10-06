"""The ClickHouse DDL translation, read off the SQL it produces.

No server is involved: this is the half of a ClickHouse backend that can be checked anywhere, and
the half where the irreversible choices live — engine, dedup key, row order.
"""

import pytest

from agentmesh.backends import TABLE_WRITES
from agentmesh.clickhouse import VERSION_COLUMN, ClickHouseUnsupported, translate_create_table
from agentmesh.stores import create_store

SPANS = """
create table if not exists spans (
  span_id text primary key,
  trace_id text not null,
  run_id text,
  duration_ms real,
  retry_count integer not null default 0,
  metadata_json text not null
)
"""

SWARMS = """
create table if not exists swarms (
  swarm_id text not null,
  name text,
  first_seen_at text not null,
  last_seen_at text not null
)
"""

SPAN_LINKS = """
create table if not exists span_links (
  span_id text not null,
  linked_span_id text not null,
  attributes_json text not null,
  primary key (span_id, linked_span_id)
)
"""


def test_a_replaced_table_deduplicates_on_its_key():
    ddl = translate_create_table(SPANS)
    assert f"engine = ReplacingMergeTree({VERSION_COLUMN})" in ddl
    assert "order by (span_id)" in ddl
    assert f"{VERSION_COLUMN} DateTime64(3) default now64(3)" in ddl


def test_an_appended_table_is_never_deduplicated():
    """swarms rows that look alike are separate observations; collapsing them loses the window."""
    ddl = translate_create_table(SWARMS)
    assert "engine = MergeTree()" in ddl
    assert "Replacing" not in ddl and VERSION_COLUMN not in ddl


def test_nullability_is_inverted_from_sqlite():
    """SQLite columns are nullable by default and ClickHouse columns are not."""
    ddl = translate_create_table(SPANS)
    assert "trace_id String" in ddl and "Nullable(String)" not in ddl.split("trace_id")[1].split("\n")[0]
    assert "run_id Nullable(String)" in ddl
    assert "duration_ms Nullable(Float64)" in ddl
    assert "span_id String" in ddl, "a key column is never nullable"


def test_types_and_defaults_survive():
    ddl = translate_create_table(SPANS)
    assert "retry_count Int64 default 0" in ddl
    assert "metadata_json String" in ddl


def test_a_composite_key_orders_by_all_of_it():
    ddl = translate_create_table(SPAN_LINKS)
    assert "order by (span_id, linked_span_id)" in ddl


def test_an_autoincrement_table_is_refused_rather_than_approximated():
    sql = "create table if not exists memories (id integer primary key autoincrement, agent text not null)"
    with pytest.raises(ClickHouseUnsupported, match="no sequences"):
        translate_create_table(sql)


def test_an_undeclared_table_is_refused():
    with pytest.raises(ClickHouseUnsupported, match="write mode"):
        translate_create_table("create table if not exists mystery (a text)", {})


def test_every_table_in_the_real_schema_translates_or_says_why(tmp_path):
    """Run the whole shipped schema through it, so the gaps are counted rather than discovered later."""
    store = create_store(str(tmp_path / "schema.db"))
    statements = store._read(lambda conn: conn.execute(  # noqa: SLF001
        "select name, sql from sqlite_master where type = 'table' and name not like 'sqlite_%'"
    ).fetchall())
    store.close()

    translated, refused = {}, {}
    for row in statements:
        name = str(row["name"])
        if name not in TABLE_WRITES:
            continue  # migration scratch table, covered by test_backends
        try:
            translated[name] = translate_create_table(str(row["sql"]))
        except ClickHouseUnsupported as exc:
            refused[name] = str(exc)

    # Everything refused is an autoincrement id, and those two are the only ones in the schema.
    assert sorted(refused) == ["audit_logs", "memories"], refused
    assert all("no sequences" in reason for reason in refused.values()), refused
    assert len(translated) == len(TABLE_WRITES) - 2

    for name, ddl in translated.items():
        assert ddl.startswith(f"create table if not exists {name} ("), ddl
        assert "engine = " in ddl and "order by (" in ddl
        assert "primary key" not in ddl.lower(), f"{name} kept a constraint ClickHouse does not have"
        assert " unique" not in ddl.lower(), f"{name} kept a unique constraint"
