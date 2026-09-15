"""PostgreSQL storage with the same features as the SQLite store.

``PostgreSQLStore`` reuses every query of :class:`~agentmesh.storage.SQLiteStore` through a small
connection adapter that translates the SQLite dialect those queries are written in:

* ``?`` placeholders -> ``%s`` (and literal ``%`` -> ``%%``)
* ``insert or replace`` -> ``insert ... on conflict (<primary key>) do update``
* ``insert or ignore`` -> ``insert ... on conflict do nothing``
* ``like`` -> ``ilike`` (SQLite's ``like`` is case-insensitive)
* ``rowid`` -> ``ctid`` (physical order, used only as a tie-breaker)
* DDL types: ``integer`` -> ``bigint``, ``real`` -> ``double precision``, autoincrement -> ``bigserial``;
  foreign keys are dropped, as SQLite does not enforce them by default
* ``pragma table_info`` -> ``information_schema.columns``

Transactions follow ``sqlite3``'s default: a transaction starts before the first write and lasts until
``commit()``; reads outside one run in autocommit mode, so idle connections never hold a snapshot.

Databases created by the pre-0.4 ``PostgreSQLStore`` (``jsonb`` columns, foreign keys) are upgraded
in place on first connect.
"""

from __future__ import annotations

import re
import threading
from decimal import Decimal
from typing import Any

from agentmesh.dependencies import optional_import
from agentmesh.storage import SQLiteStore

_WRITE_PREFIXES = ("insert", "update", "delete", "create", "alter", "drop", "replace")
_STRING_OR_CODE = re.compile(r"('(?:[^']|'')*')|(\"(?:[^\"]|\"\")*\")")
_INSERT_OR = re.compile(r"^\s*insert\s+or\s+(replace|ignore)\s+into\s+(\w+)\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL)
_PRAGMA_TABLE_INFO = re.compile(r"^\s*pragma\s+table_info\s*\(\s*(\w+)\s*\)\s*$", re.IGNORECASE)
_FOREIGN_KEY = re.compile(r",\s*foreign\s+key\s*\([^)]*\)\s*references\s+\w+\s*\([^)]*\)", re.IGNORECASE)
_REFERENCES = re.compile(r"\s+references\s+\w+\s*\([^)]*\)", re.IGNORECASE)


class PostgreSQLStore(SQLiteStore):
    """AgentMesh storage on PostgreSQL: runtime traces, OTLP/SDK ingestion, sessions, scores,
    datasets, experiments, and alerts. Requires ``pip install "agentmesh-ai[postgres]"``."""

    def __init__(self, dsn: str) -> None:  # noqa: D107 - intentionally does not call SQLiteStore.__init__
        self.dsn = dsn
        self.path = None  # type: ignore[assignment]
        self._lock = threading.RLock()
        self._conn = PostgresConnection(dsn)  # type: ignore[assignment]
        with self._lock:
            _upgrade_legacy_schema(self._conn)
        self._migrate()

    def _schema_is_ready(self) -> bool:
        rows = self._conn.execute(
            "select table_name as name from information_schema.tables where table_schema = current_schema()"
        ).fetchall()
        names = {str(row["name"]) for row in rows}
        return {"workflows", "events", "workflow_runs", "spans", "schema_migrations", "traces"} <= names


class PostgresConnection:
    """The subset of ``sqlite3.Connection`` AgentMesh uses, backed by psycopg 3."""

    def __init__(self, dsn: str) -> None:
        self._psycopg = optional_import("psycopg", "postgres")
        self.dsn = dsn
        self._raw = self._connect()
        self._in_transaction = False
        self._primary_keys: dict[str, list[str]] = {}
        self._translations: dict[str, str | None] = {}

    def _connect(self) -> Any:
        # No server-side prepared statements: they break behind transaction-pooling proxies
        # (PgBouncer, Supabase/Neon poolers), and the translated SQL is already cached here.
        return self._psycopg.connect(self.dsn, autocommit=True, prepare_threshold=None)

    def execute(self, sql: str, params: Any = ()) -> PostgresCursor:
        translated = self._translate(sql)
        if translated is None:
            return PostgresCursor(None)
        if self._raw.closed or self._raw.broken:
            if self._in_transaction:
                self._in_transaction = False
                raise self._psycopg.OperationalError("PostgreSQL connection lost during a transaction")
            self._raw = self._connect()
        if not self._in_transaction and translated.lstrip()[:7].lower().startswith(_WRITE_PREFIXES):
            self._raw.execute("begin")
            self._in_transaction = True
        cursor = self._raw.cursor(row_factory=_row_factory)
        try:
            cursor.execute(translated, tuple(_adapt(value) for value in params or ()))
        except Exception:
            if self._in_transaction:
                # PostgreSQL aborts the whole transaction on an error; end it so the connection stays usable.
                self.rollback()
            raise
        return PostgresCursor(cursor)

    def commit(self) -> None:
        if self._in_transaction:
            self._in_transaction = False
            self._raw.execute("commit")

    def rollback(self) -> None:
        if self._in_transaction:
            self._in_transaction = False
            if not self._raw.closed:
                try:
                    self._raw.execute("rollback")
                except self._psycopg.Error:
                    self._raw.close()  # reconnect on next use rather than reuse a connection in an unknown state

    def close(self) -> None:
        self._raw.close()

    # -- dialect translation -------------------------------------------------------------

    def _translate(self, sql: str) -> str | None:
        cached = self._translations.get(sql, "")
        if cached != "":
            return cached
        translated = self._translate_uncached(sql)
        if len(self._translations) < 4096:
            self._translations[sql] = translated
        return translated

    def _translate_uncached(self, sql: str) -> str | None:
        stripped = sql.strip().rstrip(";")
        lowered = stripped.lower()
        pragma = _PRAGMA_TABLE_INFO.match(stripped)
        if pragma:
            return (
                "select column_name as name from information_schema.columns "
                f"where table_schema = current_schema() and table_name = '{pragma.group(1).lower()}'"
            )
        if lowered.startswith(("pragma", "vacuum")):
            return "vacuum" if lowered.startswith("vacuum") else None
        suffix = ""
        match = _INSERT_OR.match(stripped)
        if match:
            action, table, columns = match.group(1).lower(), match.group(2), match.group(3)
            stripped = re.sub(r"^\s*insert\s+or\s+(replace|ignore)\s+into", "insert into", stripped, count=1, flags=re.IGNORECASE)
            if action == "ignore":
                suffix = " on conflict do nothing"
            else:
                keys = self._primary_key(table)
                names = [name.strip() for name in columns.split(",") if name.strip()]
                updates = [f"{name} = excluded.{name}" for name in names if name not in keys]
                target = ", ".join(keys)
                suffix = f" on conflict ({target}) do update set {', '.join(updates)}" if updates else f" on conflict ({target}) do nothing"
        is_ddl = lowered.startswith(("create table", "alter table"))
        parts: list[str] = []
        position = 0
        for literal in _STRING_OR_CODE.finditer(stripped):
            parts.append(_translate_code(stripped[position : literal.start()], is_ddl))
            parts.append(literal.group(0).replace("%", "%%"))
            position = literal.end()
        parts.append(_translate_code(stripped[position:], is_ddl))
        return "".join(parts) + suffix

    def _primary_key(self, table: str) -> list[str]:
        if table not in self._primary_keys:
            cursor = self._raw.cursor()
            cursor.execute(
                """
                select a.attname
                from pg_index i
                join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
                where i.indrelid = to_regclass(%s) and i.indisprimary
                """,
                (table,),
            )
            keys = [str(row[0]) for row in cursor.fetchall()]
            if not keys:
                raise ValueError(f"insert or replace into {table}: table has no primary key")
            self._primary_keys[table] = keys
        return self._primary_keys[table]


class PostgresCursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount) if self._cursor is not None else 0

    def fetchone(self) -> Any:
        if self._cursor is None or self._cursor.description is None:
            return None
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        if self._cursor is None or self._cursor.description is None:
            return []
        return self._cursor.fetchall()

    def __iter__(self) -> Any:
        return iter(self.fetchall())


class Row:
    """Behaves like ``sqlite3.Row``: index by position or column name, ``keys()``, iteration."""

    __slots__ = ("_names", "_index", "_values")

    def __init__(self, names: list[str], index: dict[str, int], values: list[Any]) -> None:
        self._names = names
        self._index = index
        self._values = values

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def keys(self) -> list[str]:
        return list(self._names)

    def __iter__(self) -> Any:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._names, self._values, strict=True))!r})"


def _row_factory(cursor: Any) -> Any:
    names = [column.name for column in cursor.description or []]
    index: dict[str, int] = {}
    for position, name in enumerate(names):
        index.setdefault(name, position)
        index.setdefault(name.lower(), position)

    def make_row(values: Any) -> Row:
        return Row(names, index, [_convert(value) for value in values])

    return make_row


def _convert(value: Any) -> Any:
    if isinstance(value, Decimal):  # sum()/avg() over bigint columns return numeric
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _adapt(value: Any) -> Any:
    if isinstance(value, bool):  # SQLite stores booleans in integer columns
        return int(value)
    return value


def _translate_code(code: str, is_ddl: bool) -> str:
    code = code.replace("%", "%%").replace("?", "%s")
    code = re.sub(r"\blike\b", "ilike", code, flags=re.IGNORECASE)
    code = re.sub(r"\browid\b", "ctid", code, flags=re.IGNORECASE)
    if is_ddl:
        code = _FOREIGN_KEY.sub("", code)
        code = _REFERENCES.sub("", code)
        code = re.sub(r"\binteger\s+primary\s+key\s+autoincrement\b", "bigserial primary key", code, flags=re.IGNORECASE)
        code = re.sub(r"\binteger\b", "bigint", code, flags=re.IGNORECASE)
        code = re.sub(r"\breal\b", "double precision", code, flags=re.IGNORECASE)
    return code


# Tables created by the pre-0.4 PostgreSQL store. Only these are upgraded: the database may hold other
# applications' tables, which must never be altered.
_LEGACY_TABLES = ("workflows", "events", "memories", "audit_logs", "documents", "checkpoints", "prompt_versions", "approvals", "task_results")


def _upgrade_legacy_schema(conn: PostgresConnection) -> None:
    """Convert databases created by the pre-0.4 PostgreSQL store (jsonb columns, enforced foreign keys)."""
    raw = conn._raw
    jsonb_columns = raw.execute(
        "select table_name, column_name from information_schema.columns "
        "where table_schema = current_schema() and data_type = 'jsonb' and table_name = any(%s)",
        (list(_LEGACY_TABLES),),
    ).fetchall()
    foreign_keys = raw.execute(
        "select table_name, constraint_name from information_schema.table_constraints "
        "where table_schema = current_schema() and constraint_type = 'FOREIGN KEY' and table_name in ('events', 'checkpoints')"
    ).fetchall()
    if not jsonb_columns and not foreign_keys:
        return
    with raw.transaction():
        for table, constraint in foreign_keys:
            raw.execute(f'alter table "{table}" drop constraint "{constraint}"')
        for table, column in jsonb_columns:
            raw.execute(f'alter table "{table}" alter column "{column}" type text using "{column}"::text')
