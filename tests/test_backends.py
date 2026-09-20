"""The write contracts in :mod:`agentmesh.backends` have to match what the code actually does.

Checked against the source rather than trusted, so that adding a table, or an ``update`` to a table
that never had one, fails here instead of surfacing when a column-store backend is written.
"""

import re
from pathlib import Path

import pytest

from agentmesh.backends import APPEND, HOT_TABLES, MUTATE, REPLACE, TABLE_WRITES, tables_with, write_mode
from agentmesh.stores import create_store

SOURCE = {path: path.read_text(encoding="utf-8") for path in Path("src/agentmesh").rglob("*.py")}
# Rebuilt by migration 7, and never read or written outside it.
SCRATCH_TABLES = {"swarms_rebuilt"}


def _targets(pattern: str) -> dict[str, set[str]]:
    """Table -> the modules whose SQL matches ``pattern``."""
    found: dict[str, set[str]] = {}
    for path, text in SOURCE.items():
        for match in re.finditer(pattern, text, re.S | re.I):
            found.setdefault(match.group(1).lower(), set()).add(path.name)
    return found


@pytest.fixture(scope="module")
def schema_tables(tmp_path_factory):
    store = create_store(str(tmp_path_factory.mktemp("backends") / "schema.db"))
    rows = store._read(lambda conn: conn.execute(  # noqa: SLF001 - reading the schema it just created
        "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
    ).fetchall())
    store.close()
    return {str(row["name"]) for row in rows} - SCRATCH_TABLES


def test_every_table_declares_how_its_rows_change(schema_tables):
    undeclared = schema_tables - set(TABLE_WRITES)
    assert not undeclared, f"new tables must declare a write mode in agentmesh.backends: {sorted(undeclared)}"
    stale = set(TABLE_WRITES) - schema_tables
    assert not stale, f"declared but no longer in the schema: {sorted(stale)}"


def test_only_tables_declared_mutable_are_rewritten_in_place():
    """An ``update ... set`` is the one write a column store cannot take cheaply."""
    updated = _targets(r"\bupdate\s+(\w+)\s+set\b")
    wrong = {table: sorted(where) for table, where in updated.items() if write_mode(table) != MUTATE}
    assert not wrong, f"these rewrite rows in place but are not declared MUTATE: {wrong}"


def test_tables_written_by_key_more_than_once_are_not_declared_append():
    """``insert or replace``/``or ignore``/``on conflict`` all mean the same key can be written twice."""
    keyed = _targets(r"insert\s+or\s+(?:replace|ignore)\s+into\s+(\w+)")
    for path, text in SOURCE.items():
        for match in re.finditer(r"insert\s+into\s+(\w+)(.{0,900}?)(?:\"\"\"|\Z)", text, re.S | re.I):
            if re.search(r"on\s+conflict", match.group(2), re.I):
                keyed.setdefault(match.group(1).lower(), set()).add(path.name)
    keyed = {table: where for table, where in keyed.items() if table not in SCRATCH_TABLES}
    wrong = {table: sorted(where) for table, where in keyed.items() if write_mode(table) == APPEND}
    assert not wrong, f"declared APPEND but written by key: a backend would deduplicate them away: {wrong}"


def test_swarms_is_the_append_only_table_and_stays_that_way():
    """Its duplicate-looking rows are the record of what each ingest batch saw."""
    assert write_mode("swarms") == APPEND
    for pattern in (r"insert\s+or\s+(?:replace|ignore)\s+into\s+(swarms)\b", r"\bupdate\s+(swarms)\s+set\b"):
        assert not _targets(pattern), "swarms must only ever be appended to; the rollup folds it on read"


def test_the_hot_path_is_classified_and_mostly_append_or_replace():
    """A mutation per span would sink a column store; per finished run is the known exception."""
    assert HOT_TABLES <= set(TABLE_WRITES)
    mutating = sorted(HOT_TABLES & tables_with(MUTATE))
    # traces and workflow_runs are rewritten when the AgentMesh runtime finishes a run. Ingest
    # upserts them instead, so this is one mutation per run of the optional runtime, not per span.
    assert mutating == ["traces", "workflow_runs"], (
        f"a new hot table rewrites rows in place: {mutating}. Per-span mutation is what a column "
        "store cannot absorb, so this needs a decision, not a passing test."
    )


def test_modes_are_the_three_documented_ones():
    assert set(TABLE_WRITES.values()) <= {APPEND, REPLACE, MUTATE}
