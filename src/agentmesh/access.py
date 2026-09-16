"""What agents reached: outbound hosts (egress) and the data they read or wrote.

Two questions this answers, both asked after real incidents: *did this agent talk to anything it
should not have?* and *what data did it touch before it did?*

Records come from spans, so any framework that exports OpenTelemetry gets them:

* **network** — ``url.full`` / ``http.url`` / ``server.address`` on HTTP client spans, and URLs in a
  tool call's arguments (not its result: a fetched page's links were never called);
* **retrieval** — RAG spans (the vector store or data source, and how many documents came back);
* **memory** — memory spans (the store and key);
* **db** and **file** — ``db.system`` / ``db.namespace``, ``file.path``;
* anything an agent records itself with :func:`agentmesh.record_access`.

Policies match on ``host``, checked *before* a call runs, so an allowlist actually blocks the
request rather than reporting it afterwards::

    rules:
      - name: approved-domains-only
        match: {kind: tool, host: "*"}     # only calls that reach a host at all
        except: {host: ["*.mycompany.com", "api.openai.com", "duckduckgo.com"]}
        action: deny

A call with no host in its arguments or attributes does not match ``host``, so tools that never
touch the network are left alone.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from agentmesh.types import JsonObject

ACCESS_EVENT = "agentmesh.resource.access"
KINDS = ("network", "retrieval", "memory", "db", "file", "api", "other")
OPERATIONS = ("call", "read", "write", "delete")
MAX_RECORDS_PER_SPAN = 20
CHUNK = 400  # ids per SQL statement, well under SQLite's variable limit
MAX_DETAIL_CHARS = 300
_URL = re.compile(r"https?://[^\s\"'<>)\]}]+", re.IGNORECASE)
_HOST_ATTRIBUTES = ("url.full", "http.url", "server.address", "net.peer.name", "http.host", "peer.service")

ACCESS_SCHEMA = [
    """
    create table if not exists resource_access (
      access_id text primary key,
      trace_id text not null,
      span_id text,
      agent text,
      service text,
      kind text not null,
      operation text not null,
      target text not null,
      detail text,
      status text,
      created_at text not null
    )
    """,
    "create index if not exists idx_resource_access_target on resource_access(kind, target, created_at)",
    "create index if not exists idx_resource_access_trace on resource_access(trace_id, created_at)",
    "create index if not exists idx_resource_access_created on resource_access(created_at)",
]


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------


def host_of(value: Any) -> str | None:
    """The hostname of a URL (or of a bare host), lowercased."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    parsed = urlparse(text if "//" in text else f"//{text}")
    host = (parsed.hostname or "").strip(".").lower()
    return host or None


def hosts_in(value: Any, limit: int = MAX_RECORDS_PER_SPAN) -> list[str]:
    """Every host mentioned by a value: URLs inside strings, lists, or nested mappings."""
    found: list[str] = []

    def walk(item: Any, depth: int = 0) -> None:
        if len(found) >= limit or depth > 6:
            return
        if isinstance(item, str):
            for match in _URL.findall(item[:20_000]):
                host = host_of(match)
                if host and host not in found:
                    found.append(host)
                if len(found) >= limit:
                    return
        elif isinstance(item, dict):
            for key, nested in item.items():
                if len(found) >= limit:
                    return
                if isinstance(nested, str) and str(key).lower() in {"host", "hostname", "domain", "url", "endpoint", "base_url"}:
                    host = host_of(nested)
                    if host and host not in found:
                        found.append(host)
                else:
                    walk(nested, depth + 1)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                walk(nested, depth + 1)

    walk(value)
    return found


def call_hosts(arguments: Any, attributes: dict[str, Any] | None = None) -> list[str]:
    """Hosts a call is about to reach, from its attributes and its arguments."""
    hosts: list[str] = []
    for key in _HOST_ATTRIBUTES:
        host = host_of((attributes or {}).get(key))
        if host and host not in hosts:
            hosts.append(host)
    for host in hosts_in(arguments):
        if host not in hosts:
            hosts.append(host)
    return hosts


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def records_for(item: Any, capture_content: bool = True) -> list[JsonObject]:
    """Everything one span touched: hosts it called, and data it read or wrote."""
    span = item.span
    attrs = span.attributes
    records: list[JsonObject] = []

    def add(kind: str, operation: str, target: Any, detail: Any = None) -> None:
        text = str(target or "").strip()
        if not text or len(records) >= MAX_RECORDS_PER_SPAN:
            return
        if any(record["kind"] == kind and record["target"] == text for record in records):
            return
        records.append({
            "kind": kind,
            "operation": operation,
            "target": text[:500],
            "detail": (str(detail)[:MAX_DETAIL_CHARS] if detail is not None else None) if capture_content else None,
        })

    for key in _HOST_ATTRIBUTES:
        host = host_of(attrs.get(key))
        if host:
            add("network", "call", host, _path_of(attrs.get("url.full") or attrs.get("http.url")))
    if item.category == "tool":
        # Arguments only: a page the tool returned is full of links the agent never called.
        for host in hosts_in(item.input):
            add("network", "call", host, None)
    if item.category == "retrieval":
        store = item.data_source or _str(attrs.get("gen_ai.retrieval.store.id")) or "retrieval"
        add("retrieval", "read", store, f"{len(item.documents)} documents" if item.documents else None)
    if item.category == "memory":
        add("memory", MEMORY_OPERATION.get(str(item.operation or ""), "read"), item.memory_store or "memory", item.memory_key)
    database = _str(attrs.get("db.namespace")) or _str(attrs.get("db.name")) or _str(attrs.get("db.collection.name"))
    system = _str(attrs.get("db.system.name")) or _str(attrs.get("db.system"))
    if system or database:
        add("db", "read", f"{system}:{database}" if system and database else (database or system), _str(attrs.get("db.operation.name")))
    for key in ("file.path", "code.file.path", "code.filepath"):
        if attrs.get(key):
            add("file", "read", attrs[key], None)
    for event in span.events:
        if event.get("name") != ACCESS_EVENT:
            continue
        event_attrs = event.get("attributes") or {}
        kind = _str(event_attrs.get("agentmesh.access.kind")) or "other"
        add(
            kind if kind in KINDS else "other",
            _str(event_attrs.get("agentmesh.access.operation")) or "read",
            event_attrs.get("agentmesh.access.target"),
            event_attrs.get("agentmesh.access.detail"),
        )
    return records


def write_access(conn: sqlite3.Connection, item: Any, capture_content: bool = True) -> None:
    span = item.span
    for position, record in enumerate(records_for(item, capture_content)):
        conn.execute(
            """
            insert or ignore into resource_access
            (access_id, trace_id, span_id, agent, service, kind, operation, target, detail, status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"access_{span.span_id}_{position}",
                span.trace_id,
                span.span_id,
                item.agent_name,
                item.service_name,
                record["kind"],
                record["operation"],
                record["target"],
                record["detail"],
                item.status,
                span.start_time,
            ),
        )


MEMORY_OPERATION = {"create_memory": "write", "update_memory": "write", "upsert_memory": "write", "delete_memory": "delete", "search_memory": "read"}


def _path_of(url: Any) -> str | None:
    parsed = urlparse(str(url or ""))
    return (parsed.path or None) if parsed.scheme else None


def _str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def list_access(
    conn: sqlite3.Connection,
    limit: int = 200,
    kind: str | None = None,
    target: str | None = None,
    trace_id: str | None = None,
    agent: str | None = None,
    since: str | None = None,
    exact: bool = False,
) -> list[JsonObject]:
    """Individual accesses. ``target`` is a substring search unless ``exact`` is set."""
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (("kind", kind), ("trace_id", trace_id), ("agent", agent)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if target:
        clauses.append("target = ?" if exact else "target like ?")
        params.append(target if exact else f"%{target}%")
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"select * from resource_access {where} order by created_at desc limit ?",
        (*params, max(min(int(limit), 1000), 1)),
    ).fetchall()
    return [dict(row) for row in rows]


def access_summary(conn: sqlite3.Connection, since: str | None = None, limit: int = 100, kind: str | None = None) -> list[JsonObject]:
    """Every destination and resource agents touched, most used first."""
    clauses, params = [], []
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        select kind, target,
          count(*) as calls,
          count(distinct trace_id) as traces,
          count(distinct agent) as agents,
          sum(case when status = 'failed' then 1 else 0 end) as errors,
          min(created_at) as first_seen,
          max(created_at) as last_seen
        from resource_access {where}
        group by kind, target
        order by calls desc
        limit ?
        """,
        (*params, max(min(int(limit), 500), 1)),
    ).fetchall()
    summary = [dict(row) for row in rows]
    if not summary:
        return []
    # "First seen in this window" is what makes a destination worth a second look.
    if since:
        targets = [entry["target"] for entry in summary]
        earlier: set[tuple[str, str]] = set()
        for start in range(0, len(targets), CHUNK):
            chunk = targets[start : start + CHUNK]
            marks = ", ".join("?" for _ in chunk)
            earlier.update(
                (row["kind"], row["target"])
                for row in conn.execute(
                    f"select distinct kind, target from resource_access where created_at < ? and target in ({marks})",
                    (since, *chunk),
                ).fetchall()
            )
        for entry in summary:
            entry["is_new"] = (entry["kind"], entry["target"]) not in earlier
    else:
        for entry in summary:
            entry["is_new"] = False
    return summary


def access_for_traces(conn: sqlite3.Connection, trace_ids: Iterable[str], limit: int = 500) -> list[JsonObject]:
    """Destinations and resources touched by a set of traces (one swarm, say), grouped."""
    ids = list(trace_ids)
    if not ids:
        return []
    grouped: dict[tuple[str, str], JsonObject] = {}
    for start in range(0, len(ids), CHUNK):  # a swarm can have more traces than SQLite allows variables
        chunk = ids[start : start + CHUNK]
        marks = ", ".join("?" for _ in chunk)
        for row in conn.execute(
            f"""
            select kind, target, count(*) as calls, count(distinct agent) as agents,
              sum(case when status = 'failed' then 1 else 0 end) as errors,
              min(created_at) as first_seen, max(created_at) as last_seen
            from resource_access where trace_id in ({marks})
            group by kind, target
            """,
            chunk,
        ).fetchall():
            key = (row["kind"], row["target"])
            entry = grouped.get(key)
            if entry is None:
                grouped[key] = dict(row)
                continue
            entry["calls"] += row["calls"]
            entry["agents"] = max(entry["agents"], row["agents"])  # distinct agents cannot be summed across chunks
            entry["errors"] += row["errors"]
            entry["first_seen"] = min(entry["first_seen"], row["first_seen"])
            entry["last_seen"] = max(entry["last_seen"], row["last_seen"])
    ordered = sorted(grouped.values(), key=lambda entry: -entry["calls"])
    return ordered[: max(min(int(limit), 1000), 1)]


def record_payload(target: str, kind: str = "other", operation: str = "read", detail: str | None = None) -> JsonObject:
    """Attributes for the ``agentmesh.resource.access`` span event (used by the SDK)."""
    return {
        "agentmesh.access.target": target,
        "agentmesh.access.kind": kind if kind in KINDS else "other",
        "agentmesh.access.operation": operation if operation in OPERATIONS else "read",
        "agentmesh.access.detail": detail,
    }


__all__ = [
    "ACCESS_EVENT",
    "ACCESS_SCHEMA",
    "KINDS",
    "OPERATIONS",
    "access_for_traces",
    "access_summary",
    "call_hosts",
    "host_of",
    "hosts_in",
    "list_access",
    "record_payload",
    "records_for",
    "write_access",
]
