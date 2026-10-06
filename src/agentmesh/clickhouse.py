"""Translating AgentMesh's schema into ClickHouse DDL.

The PostgreSQL backend works by translating the SQLite dialect the queries are written in, and a
ClickHouse backend has to do the same. This module is the first half of that: turning the
``create table`` statements the schema is written in into ClickHouse tables, which is where the
choices that cannot be taken back are made — the engine, what it deduplicates on, and how rows are
ordered on disk.

The engine comes from :mod:`agentmesh.backends`, which is the point of that registry:

* ``REPLACE`` and ``MUTATE`` -> ``ReplacingMergeTree(_version)``. The same key can be written more
  than once and the last write has to win. A span delivered while it was running and again once it
  finished is one row twice, so reads of these tables need ``FINAL`` to collapse them.
* ``APPEND`` -> ``MergeTree()``. Rows that look alike are the record of separate observations.
  ``swarms`` is the case: deduplicating it would quietly narrow every swarm's window.

Two differences from SQLite that the column types have to carry:

* a SQLite column is nullable unless it says otherwise, a ClickHouse column is the reverse, so
  anything without ``not null`` becomes ``Nullable(T)``;
* ``integer primary key autoincrement`` has no equivalent — ClickHouse has no sequences — so those
  tables raise rather than silently producing a table that cannot generate ids.

Nothing here talks to a server, so it is tested by reading the SQL it produces.
"""

from __future__ import annotations

import re

from agentmesh.backends import APPEND, TABLE_WRITES

VERSION_COLUMN = "_version"
# Set by the server on insert, so the latest delivery of a row wins without the caller tracking it.
VERSION_DDL = f"{VERSION_COLUMN} DateTime64(3) default now64(3)"

TYPES = {"text": "String", "integer": "Int64", "real": "Float64", "blob": "String"}

_CREATE = re.compile(r"^\s*create\s+table\s+(?:if\s+not\s+exists\s+)?[\"`]?(\w+)[\"`]?\s*\((.*)\)\s*$", re.S | re.I)
_TABLE_CONSTRAINT = re.compile(r"^\s*(primary\s+key|unique|foreign\s+key|check)\b", re.I)
_PRIMARY_KEY_CLAUSE = re.compile(r"^\s*primary\s+key\s*\((.*)\)\s*$", re.S | re.I)
_INLINE_PK = re.compile(r"\s+primary\s+key\b", re.I)
_AUTOINCREMENT = re.compile(r"\bautoincrement\b", re.I)
_NOT_NULL = re.compile(r"\s+not\s+null\b", re.I)
_UNIQUE = re.compile(r"\s+unique\b", re.I)
_REFERENCES = re.compile(r"\s+references\s+\w+\s*\([^)]*\)", re.I)
_DEFAULT = re.compile(r"\s+default\s+(.+?)\s*$", re.I)


class ClickHouseUnsupported(RuntimeError):
    """A part of the schema that has no ClickHouse equivalent, named rather than approximated."""


def translate_create_table(sql: str, table_writes: dict[str, str] | None = None) -> str:
    """One SQLite ``create table`` statement as ClickHouse DDL.

    Raises :class:`ClickHouseUnsupported` for a table whose identity ClickHouse cannot provide, or
    one that has not declared a write mode in :mod:`agentmesh.backends`.
    """
    modes = TABLE_WRITES if table_writes is None else table_writes
    match = _CREATE.match(sql.strip().rstrip(";"))
    if match is None:
        raise ClickHouseUnsupported(f"not a create table statement: {sql.strip()[:60]}")
    table, body = match.group(1), match.group(2)
    if table not in modes:
        raise ClickHouseUnsupported(f"{table} has not declared a write mode in agentmesh.backends")
    if _AUTOINCREMENT.search(body):
        raise ClickHouseUnsupported(
            f"{table} uses an autoincrement id and ClickHouse has no sequences; it needs a natural key first"
        )

    columns: list[str] = []
    key: list[str] = []
    for part in _split_columns(body):
        if _TABLE_CONSTRAINT.match(part):
            clause = _PRIMARY_KEY_CLAUSE.match(part)
            if clause is not None:
                key = [name.strip().strip('"`') for name in clause.group(1).split(",")]
            continue  # unique / foreign key / check have no ClickHouse equivalent and are not relied on
        name, declaration = _column(part)
        if _INLINE_PK.search(part):
            key = [name]
        columns.append(declaration)

    mode = modes[table]
    if mode == APPEND:
        engine = "MergeTree()"
    else:
        columns.append(VERSION_DDL)
        engine = f"ReplacingMergeTree({VERSION_COLUMN})"
    order = ", ".join(key) if key else _fallback_order(columns)
    rendered = ",\n  ".join(columns)
    return f"create table if not exists {table} (\n  {rendered}\n) engine = {engine} order by ({order})"


def _column(part: str) -> tuple[str, str]:
    """``agent text not null default 'x'`` -> ``("agent", "agent String default 'x'")``."""
    text = _REFERENCES.sub("", part.strip())
    default = ""
    found = _DEFAULT.search(text)
    if found is not None:
        default = f" default {found.group(1).strip()}"
        text = text[: found.start()]
    required = bool(_NOT_NULL.search(text)) or bool(_INLINE_PK.search(text))
    text = _UNIQUE.sub("", _NOT_NULL.sub("", _INLINE_PK.sub("", text))).strip()
    name, _, declared = text.partition(" ")
    name = name.strip('"`')
    base = TYPES.get(declared.strip().lower())
    if base is None:
        raise ClickHouseUnsupported(f"no ClickHouse type for {name} {declared.strip()!r}")
    return name, f"{name} {base if required else f'Nullable({base})'}{default}"


def _fallback_order(columns: list[str]) -> str:
    """A table with no declared key still has to be ordered; its first column is the best guess."""
    return columns[0].split(" ")[0] if columns else "tuple()"


def _split_columns(body: str) -> list[str]:
    """Split a column list on commas that are not inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        current.append(char)
    if "".join(current).strip():
        parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]
