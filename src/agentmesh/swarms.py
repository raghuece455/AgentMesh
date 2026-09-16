"""Agent swarms: many agents, often spread across processes and traces, working as one run.

A swarm is identified by the ``agentmesh.swarm.id`` attribute (on spans or on the resource;
``swarm.id`` is accepted too). Traces join a swarm when any of their spans carries the id, or when
one of their spans links (an OpenTelemetry span link) to a trace that is already in the swarm, so
a worker started from a link needs no extra setup.

Relations between agents:

* **spawn** — an agent span nested under another agent (same trace), or a trace whose span links to
  the span that started it (``agentmesh.link.type = spawned_by``, the default for SDK workers);
* **message** and **handoff** — ``agentmesh.agent.message`` span events with
  ``agentmesh.message.to`` (and optionally the target's trace and span).

Membership, links, and messages are stored when spans are ingested. The swarm graph (agents,
edges, depth, fan-out, per-agent cost, activity over time) is computed when a swarm is read, so it
is correct regardless of the order in which spans arrive.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from agentmesh.access import access_for_traces
from agentmesh.policy import short_name
from agentmesh.policy_store import _halt_json
from agentmesh.swarm_limits import swarm_limit_status
from agentmesh.types import JsonObject, dumps_json, loads_json, utc_now

SWARM_ID_KEYS = ("agentmesh.swarm.id", "swarm.id")
SWARM_NAME_KEYS = ("agentmesh.swarm.name", "swarm.name")
MESSAGE_EVENT = "agentmesh.agent.message"
LINK_TYPE_KEY = "agentmesh.link.type"
AGENT_EVENTS = {"agent.invoke", "agent.started"}
TOOL_EVENTS = {"tool.execute", "tool.started"}
MAX_SWARM_SPANS = 200_000
MAX_NODES = 5_000
MAX_MESSAGES = 5_000
MESSAGE_CONTENT_CHARS = 2_000
TIMELINE_BUCKETS = 60

SWARM_SCHEMA = [
    """
    create table if not exists swarms (
      swarm_id text primary key,
      name text,
      service_name text,
      environment text,
      first_seen_at text not null,
      last_seen_at text not null
    )
    """,
    "create index if not exists idx_swarms_last_seen on swarms(last_seen_at)",
    """
    create table if not exists swarm_traces (
      swarm_id text not null,
      trace_id text not null,
      added_at text not null,
      primary key (swarm_id, trace_id)
    )
    """,
    "create index if not exists idx_swarm_traces_trace on swarm_traces(trace_id)",
    """
    create table if not exists span_links (
      span_id text not null,
      trace_id text not null,
      linked_trace_id text not null,
      linked_span_id text not null,
      link_type text not null,
      attributes_json text not null,
      primary key (span_id, linked_span_id)
    )
    """,
    "create index if not exists idx_span_links_trace on span_links(trace_id)",
    "create index if not exists idx_span_links_linked on span_links(linked_trace_id)",
    """
    create table if not exists agent_messages_log (
      message_id text primary key,
      trace_id text not null,
      span_id text not null,
      from_agent text,
      to_agent text,
      to_trace_id text,
      to_span_id text,
      kind text not null,
      content_json text,
      created_at text not null
    )
    """,
    "create index if not exists idx_agent_messages_log_trace on agent_messages_log(trace_id, created_at)",
]


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def span_swarm(attributes: dict[str, Any], resource: dict[str, Any]) -> tuple[str | None, str | None]:
    """The swarm id and name a span declares, from its attributes or its resource."""
    swarm_id = next((str(source[key]) for source in (attributes, resource) for key in SWARM_ID_KEYS if source.get(key)), None)
    name = next((str(source[key]) for source in (attributes, resource) for key in SWARM_NAME_KEYS if source.get(key)), None)
    return swarm_id, name


def write_trace_swarms(conn: sqlite3.Connection, trace_id: str, items: Iterable[Any]) -> None:
    """Record swarm membership, span links, and agent messages for one trace's batch of spans."""
    items = list(items)
    declared: dict[str, JsonObject] = {}
    for item in items:
        span = item.span
        swarm_id, name = span_swarm(span.attributes, span.resource)
        if swarm_id:
            entry = declared.setdefault(swarm_id, {"name": None, "service": item.service_name, "environment": item.environment, "seen": span.start_time})
            entry["name"] = entry["name"] or name
            entry["seen"] = max(str(entry["seen"]), str(span.end_time or span.start_time))
        for link in span.links:
            _write_link(conn, span, link)
    if not declared:
        # A trace without a swarm id joins the swarm of any trace its spans link to.
        for item in items:
            for link in item.span.links:
                row = conn.execute("select swarm_id from swarm_traces where trace_id = ?", (link["trace_id"],)).fetchone()
                if row is not None:
                    declared.setdefault(str(row["swarm_id"]), {"name": None, "service": item.service_name, "environment": item.environment, "seen": item.span.start_time})
    now = utc_now()
    batch_start = min(str(item.span.start_time) for item in items)
    for swarm_id, entry in declared.items():
        seen = str(entry["seen"])
        conn.execute(
            "insert or ignore into swarms (swarm_id, name, service_name, environment, first_seen_at, last_seen_at) values (?, ?, ?, ?, ?, ?)",
            (swarm_id, entry["name"], entry["service"], entry["environment"], batch_start, seen),
        )
        conn.execute("update swarms set last_seen_at = ? where swarm_id = ? and last_seen_at < ?", (seen, swarm_id, seen))
        conn.execute("update swarms set first_seen_at = ? where swarm_id = ? and first_seen_at > ?", (batch_start, swarm_id, batch_start))
        if entry["name"]:
            conn.execute("update swarms set name = ? where swarm_id = ? and name is null", (entry["name"], swarm_id))
        conn.execute("insert or ignore into swarm_traces (swarm_id, trace_id, added_at) values (?, ?, ?)", (swarm_id, trace_id, now))


def write_messages(conn: sqlite3.Connection, item: Any, capture_content: bool) -> None:
    span = item.span
    for position, event in enumerate(span.events):
        if event.get("name") != MESSAGE_EVENT:
            continue
        attrs = event.get("attributes") or {}
        content = attrs.get("agentmesh.message.content") if capture_content else None
        if isinstance(content, str) and len(content) > MESSAGE_CONTENT_CHARS:
            content = content[:MESSAGE_CONTENT_CHARS] + "…"
        conn.execute(
            """
            insert or ignore into agent_messages_log
            (message_id, trace_id, span_id, from_agent, to_agent, to_trace_id, to_span_id, kind, content_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"msg_{span.span_id}_{position}",
                span.trace_id,
                span.span_id,
                _text(attrs.get("agentmesh.message.from")) or item.agent_name,
                _text(attrs.get("agentmesh.message.to")),
                _text(attrs.get("agentmesh.message.to_trace_id")),
                _text(attrs.get("agentmesh.message.to_span_id")),
                _text(attrs.get("agentmesh.message.kind")) or "message",
                dumps_json(content) if content is not None else None,
                event.get("time") or span.start_time,
            ),
        )


def _write_link(conn: sqlite3.Connection, span: Any, link: JsonObject) -> None:
    attributes = link.get("attributes") or {}
    conn.execute(
        """
        insert or ignore into span_links (span_id, trace_id, linked_trace_id, linked_span_id, link_type, attributes_json)
        values (?, ?, ?, ?, ?, ?)
        """,
        (span.span_id, span.trace_id, link["trace_id"], link["span_id"], _text(attributes.get(LINK_TYPE_KEY)) or "link", dumps_json(attributes)),
    )


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def list_swarms(conn: sqlite3.Connection, limit: int = 50, offset: int = 0, query: str | None = None, since: str | None = None) -> list[JsonObject]:
    clauses: list[str] = []
    params: list[Any] = []
    if query:
        clauses.append("(s.swarm_id like ? or s.name like ? or s.service_name like ?)")
        params.extend([f"%{query}%"] * 3)
    if since:
        clauses.append("s.last_seen_at >= ?")
        params.append(since)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"select * from swarms s {where} order by s.last_seen_at desc limit ? offset ?",
        (*params, max(min(int(limit), 500), 1), max(int(offset), 0)),
    ).fetchall()
    swarms = [dict(row) for row in rows]
    if not swarms:
        return []
    ids = [swarm["swarm_id"] for swarm in swarms]
    marks = ", ".join("?" for _ in ids)
    stats = {
        row["swarm_id"]: dict(row)
        for row in conn.execute(
            f"""
            select st.swarm_id,
              count(distinct sp.trace_id) as traces,
              sum(case when sp.event_type in ('agent.invoke', 'agent.started') then 1 else 0 end) as agents,
              sum(case when sp.event_type in ('agent.invoke', 'agent.started') and sp.status = 'failed' then 1 else 0 end) as failed_agents,
              sum(case when sp.event_type in ('agent.invoke', 'agent.started') and sp.status = 'running' then 1 else 0 end) as running_agents,
              sum(case when sp.status = 'failed' then 1 else 0 end) as errors,
              sum(case when sp.event_type like 'model.%' then 1 else 0 end) as llm_calls,
              sum(case when sp.event_type in ('tool.execute', 'tool.started') then 1 else 0 end) as tool_calls,
              sum(sp.total_tokens) as tokens,
              sum(sp.estimated_cost) as cost,
              min(sp.started_at) as started_at,
              max(coalesce(sp.ended_at, sp.started_at)) as ended_at
            from swarm_traces st join spans sp on sp.trace_id = st.trace_id
            where st.swarm_id in ({marks})
            group by st.swarm_id
            """,
            ids,
        ).fetchall()
    }
    statuses: dict[str, Counter[str]] = {}
    root_statuses: dict[str, Counter[str]] = {}
    demo: dict[str, bool] = {}
    for row in conn.execute(
        f"""
        select x.swarm_id, x.status, x.is_root, max(x.is_demo) as is_demo, count(*) as total
        from (
          select st.swarm_id, wr.status, wr.is_demo,
            case when exists (select 1 from span_links l where l.trace_id = wr.trace_id and l.link_type = 'spawned_by') then 0 else 1 end as is_root
          from swarm_traces st join workflow_runs wr on wr.trace_id = st.trace_id
          where st.swarm_id in ({marks})
        ) x
        group by x.swarm_id, x.status, x.is_root
        """,
        ids,
    ).fetchall():
        statuses.setdefault(row["swarm_id"], Counter())[row["status"]] += int(row["total"])
        if row["is_root"]:
            root_statuses.setdefault(row["swarm_id"], Counter())[row["status"]] += int(row["total"])
        demo[row["swarm_id"]] = demo.get(row["swarm_id"], False) or bool(row["is_demo"])
    result = []
    for swarm in swarms:
        stat = stats.get(swarm["swarm_id"], {})
        counts = statuses.get(swarm["swarm_id"], Counter())
        result.append({
            "swarm_id": swarm["swarm_id"],
            "name": swarm["name"] or swarm["swarm_id"],
            "service_name": swarm["service_name"],
            "environment": swarm["environment"],
            "is_demo": demo.get(swarm["swarm_id"], False),
            "status": _swarm_status(counts, root_statuses.get(swarm["swarm_id"])),
            "traces": int(stat.get("traces") or 0),
            "agents": int(stat.get("agents") or 0),
            "failed_agents": int(stat.get("failed_agents") or 0),
            "running_agents": int(stat.get("running_agents") or 0),
            "errors": int(stat.get("errors") or 0),
            "llm_calls": int(stat.get("llm_calls") or 0),
            "tool_calls": int(stat.get("tool_calls") or 0),
            "tokens": int(stat.get("tokens") or 0),
            "cost": round(float(stat.get("cost") or 0.0), 6),
            "started_at": stat.get("started_at") or swarm["first_seen_at"],
            "ended_at": stat.get("ended_at") or swarm["last_seen_at"],
            "duration_ms": _duration_ms(stat.get("started_at"), stat.get("ended_at")),
            "last_seen_at": swarm["last_seen_at"],
        })
    return result


def trace_swarms(conn: sqlite3.Connection, trace_id: str) -> list[JsonObject]:
    """The swarms a trace belongs to (usually one)."""
    rows = conn.execute(
        "select s.swarm_id, s.name from swarm_traces st join swarms s on s.swarm_id = st.swarm_id where st.trace_id = ? order by s.first_seen_at",
        (trace_id,),
    ).fetchall()
    return [{"swarm_id": row["swarm_id"], "name": row["name"] or row["swarm_id"]} for row in rows]


def swarm_rows(conn: sqlite3.Connection, swarm_id: str, max_spans: int = MAX_SWARM_SPANS) -> JsonObject | None:
    """Everything a swarm report is built from. Kept separate so the graph is built outside the store lock."""
    swarm = conn.execute("select * from swarms where swarm_id = ?", (swarm_id,)).fetchone()
    if swarm is None:
        return None
    traces = [
        dict(row)
        for row in conn.execute(
            """
            select wr.trace_id, wr.workflow_name, wr.status, wr.started_at, wr.ended_at, wr.duration_ms, wr.service_name, wr.is_demo
            from swarm_traces st join workflow_runs wr on wr.trace_id = st.trace_id
            where st.swarm_id = ? order by wr.started_at
            """,
            (swarm_id,),
        ).fetchall()
    ]
    spans = [
        dict(row)
        for row in conn.execute(
            """
            select sp.span_id, sp.trace_id, sp.parent_span_id, sp.agent_name, sp.name, sp.event_type, sp.status,
              sp.started_at, sp.ended_at, sp.duration_ms, sp.estimated_cost, sp.total_tokens, sp.tool_name, sp.model,
              sp.error_type, sp.error_message
            from swarm_traces st join spans sp on sp.trace_id = st.trace_id
            where st.swarm_id = ? order by sp.started_at limit ?
            """,
            (swarm_id, max_spans + 1),
        ).fetchall()
    ]
    truncated = len(spans) > max_spans
    spans = spans[:max_spans]
    links = [
        dict(row)
        for row in conn.execute(
            """
            select l.span_id, l.trace_id, l.linked_trace_id, l.linked_span_id, l.link_type
            from swarm_traces st join span_links l on l.trace_id = st.trace_id where st.swarm_id = ?
            """,
            (swarm_id,),
        ).fetchall()
    ]
    messages = [
        {**dict(row), "content": loads_json(row["content_json"]) if row["content_json"] else None}
        for row in conn.execute(
            """
            select m.message_id, m.trace_id, m.span_id, m.from_agent, m.to_agent, m.to_trace_id, m.to_span_id, m.kind, m.content_json, m.created_at
            from swarm_traces st join agent_messages_log m on m.trace_id = st.trace_id
            where st.swarm_id = ? order by m.created_at limit ?
            """,
            (swarm_id, MAX_MESSAGES),
        ).fetchall()
    ]
    for message in messages:
        message.pop("content_json", None)
    swarm_json = {
        "swarm_id": swarm["swarm_id"],
        "name": swarm["name"] or swarm["swarm_id"],
        "service_name": swarm["service_name"],
        "environment": swarm["environment"],
    }
    halt = conn.execute(
        "select * from policy_halts where scope = 'swarm' and value = ? and released_at is null order by created_at desc",
        (swarm_id,),
    ).fetchone()
    return {
        "access": access_for_traces(conn, [trace["trace_id"] for trace in traces]),
        "halt": _halt_json(halt) if halt is not None else None,
        **swarm_limit_status(conn, swarm_json),
        "swarm": {
            "swarm_id": swarm["swarm_id"],
            "name": swarm["name"] or swarm["swarm_id"],
            "service_name": swarm["service_name"],
            "environment": swarm["environment"],
            "first_seen_at": swarm["first_seen_at"],
            "last_seen_at": swarm["last_seen_at"],
        },
        "traces": traces,
        "spans": spans,
        "links": links,
        "messages": messages,
        "truncated": truncated,
    }


def swarm_report(rows: JsonObject) -> JsonObject:
    """Turn :func:`swarm_rows` into the swarm report: summary, agents, edges, roles, timeline, insights."""
    traces = rows["traces"]
    report = analyze_swarm(traces, rows["spans"], rows["links"], rows["messages"])
    report["access"] = rows["access"]
    report["summary"]["truncated"] = bool(rows["truncated"])
    return {
        **rows["swarm"],
        "is_demo": any(bool(trace.get("is_demo")) for trace in traces),
        "halt": rows["halt"],
        "usage": rows["usage"],
        "limits": rows["limits"],
        "traces": traces,
        **report,
    }


def get_swarm(conn: sqlite3.Connection, swarm_id: str, max_spans: int = MAX_SWARM_SPANS) -> JsonObject | None:
    """Read and analyze a swarm in one call (the CLI and tests; the store splits the two)."""
    rows = swarm_rows(conn, swarm_id, max_spans)
    return swarm_report(rows) if rows is not None else None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analyze_swarm(traces: list[JsonObject], spans: list[JsonObject], links: list[JsonObject], messages: list[JsonObject]) -> JsonObject:
    """Build the agent graph of a swarm from its spans, links, and messages.

    Nodes are agent spans, plus the root span of any trace whose root is not an agent (an
    orchestrator script, a queue consumer). Every span belongs to its nearest agent ancestor,
    which is how per-agent calls, tokens, and cost are counted.
    """
    by_id = {span["span_id"]: span for span in spans}
    trace_names = {trace["trace_id"]: trace.get("workflow_name") for trace in traces}
    nodes: dict[str, JsonObject] = {}

    def add_node(span: JsonObject, kind: str) -> None:
        if kind == "agent":
            # Python qualified names (``Crew.researcher``, ``main.<locals>.researcher``) show as the bare name.
            name = short_name(str(span.get("agent_name") or span.get("name") or "agent"))
        else:
            name = trace_names.get(span["trace_id"]) or span.get("name") or "trace"
        nodes[span["span_id"]] = {
            "key": span["span_id"],
            "span_id": span["span_id"],
            "trace_id": span["trace_id"],
            "name": name,
            "kind": kind,
            "status": span.get("status") or "unset",
            "started_at": span.get("started_at"),
            "ended_at": span.get("ended_at"),
            "duration_ms": span.get("duration_ms"),
            "parent_key": None,
            "depth": 0,
            "children": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "tokens": 0,
            "cost": 0.0,
            "errors": 0,
            "error_message": None,
            "tools": Counter(),
            "models": Counter(),
        }

    for span in spans:
        if span.get("event_type") in AGENT_EVENTS:
            add_node(span, "agent")
    for span in spans:
        if not span.get("parent_span_id") and span["span_id"] not in nodes:
            add_node(span, "trace")
    trace_roots = {node["trace_id"]: key for key, node in nodes.items() if node["kind"] == "trace"}

    owners: dict[str, str | None] = {}

    def owner(span_id: str | None) -> str | None:
        """Nearest agent (or trace root) at or above ``span_id``."""
        path: list[str] = []
        current = span_id
        found: str | None = None
        for _ in range(512):
            if current is None:
                break
            if current in owners:
                found = owners[current]
                break
            path.append(current)
            if current in nodes:
                found = current
                break
            span = by_id.get(current)
            if span is None:
                break
            current = span.get("parent_span_id")
        if found is None and path:
            # Orphaned spans (their root was not ingested) belong to their trace's root node, if any.
            span = by_id.get(path[0])
            if span is not None:
                found = trace_roots.get(span["trace_id"])
        for item in path:
            owners[item] = found
        return found

    edges: dict[tuple[str, str, str], JsonObject] = {}

    def add_edge(source: str | None, target: str | None, kind: str, at: str | None) -> None:
        if source is None or target is None or source == target:
            return
        edge = edges.setdefault((source, target, kind), {"source": source, "target": target, "kind": kind, "count": 0, "first_at": at})
        edge["count"] += 1
        if at and (edge["first_at"] is None or at < edge["first_at"]):
            edge["first_at"] = at

    for key, node in nodes.items():
        parent = owner(by_id[key].get("parent_span_id"))
        if parent is not None and parent != key:
            node["parent_key"] = parent
            add_edge(parent, key, "spawn", node["started_at"])
    for link in links:
        if link["span_id"] not in by_id or link["linked_span_id"] not in by_id:
            continue
        source = owner(link["linked_span_id"])
        target = owner(link["span_id"])
        kind = {"spawned_by": "spawn", "handoff": "handoff", "handoff_from": "handoff"}.get(str(link.get("link_type")), "link")
        if kind == "spawn" and target is not None and nodes[target]["parent_key"] is None and source != target:
            nodes[target]["parent_key"] = source
        add_edge(source, target, kind, by_id[link["span_id"]].get("started_at"))

    for span in spans:
        key = owner(span["span_id"])
        if key is None:
            continue
        node = nodes[key]
        event_type = str(span.get("event_type") or "")
        if event_type.startswith("model.") and event_type not in {"model.response", "model.failed"}:
            node["llm_calls"] += 1
            if span.get("model"):
                node["models"][span["model"]] += 1
        elif event_type in TOOL_EVENTS:
            node["tool_calls"] += 1
            if span.get("tool_name"):
                node["tools"][span["tool_name"]] += 1
        node["tokens"] += int(span.get("total_tokens") or 0)
        node["cost"] += float(span.get("estimated_cost") or 0.0)
        if span.get("status") == "failed":
            node["errors"] += 1
            node["error_message"] = node["error_message"] or span.get("error_message") or span.get("error_type")

    # A trace that only wraps one agent (``with trace("worker 17"): researcher()``) is not an agent
    # of its own: fold it into that agent, so a 10,000-worker swarm shows 10,000 researchers, not
    # 20,000 nodes with a role per worker trace.
    alias: dict[str, str] = {}
    children_of: dict[str, list[str]] = {}
    for (source, target, kind) in edges:
        if kind == "spawn":
            children_of.setdefault(source, []).append(target)
    for key, node in list(nodes.items()):
        kids = children_of.get(key, [])
        if node["kind"] == "trace" and len(kids) == 1 and not node["llm_calls"] and not node["tool_calls"] and nodes[kids[0]]["kind"] == "agent":
            alias[key] = kids[0]

    def canonical(key: str | None) -> str | None:
        seen: set[str] = set()
        while key in alias and key not in seen:
            seen.add(key)
            key = alias[key]
        return key

    if alias:
        for key, child in alias.items():
            folded, target = nodes[key], nodes[canonical(child)]  # type: ignore[index]
            if target["parent_key"] == key:
                target["parent_key"] = folded["parent_key"]
            target["tokens"] += folded["tokens"]
            target["cost"] += folded["cost"]
            target["errors"] += folded["errors"]
            target["error_message"] = target["error_message"] or folded["error_message"]
            target["folded_trace"] = folded["name"]
        for node in nodes.values():
            node["parent_key"] = canonical(node["parent_key"])
        remapped: dict[tuple[str, str, str], JsonObject] = {}
        for edge in edges.values():
            source, target = canonical(edge["source"]), canonical(edge["target"])
            if source is None or target is None or source == target:
                continue
            entry = remapped.setdefault((source, target, edge["kind"]), {**edge, "source": source, "target": target, "count": 0})
            entry["count"] += edge["count"]
        edges.clear()
        edges.update(remapped)
        for key in alias:
            del nodes[key]

    unresolved = 0
    resolved_messages = []
    by_name: dict[str, list[JsonObject]] = {}
    for node in nodes.values():
        by_name.setdefault(str(node["name"]), []).append(node)
    for message in messages:
        source = canonical(owner(message["span_id"]))
        target = canonical(owner(message["to_span_id"])) if message.get("to_span_id") in by_id else None
        if target is None and message.get("to_agent"):
            target = _closest_by_name(by_name.get(short_name(str(message["to_agent"])), []), message.get("created_at"))
        if target is None:
            unresolved += 1
        kind = "handoff" if message.get("kind") == "handoff" else "message"
        add_edge(source, target, kind, message.get("created_at"))
        resolved_messages.append({**message, "source_key": source, "target_key": target})

    _assign_depths(nodes)
    for node in nodes.values():
        if node["parent_key"] in nodes:
            nodes[node["parent_key"]]["children"] += 1

    ordered = sorted(nodes.values(), key=lambda node: (str(node["started_at"] or ""), node["key"]))
    agent_nodes = [node for node in ordered if node["kind"] == "agent"]
    roles = _roles(ordered, edges)
    summary = _summary(traces, spans, links, ordered, agent_nodes, resolved_messages, len(roles["nodes"]))
    timeline = _timeline(ordered, summary)
    insights = _insights(ordered, agent_nodes, summary, unresolved)
    for node in ordered:
        node["tools"] = [name for name, _count in node["tools"].most_common(3)]
        node["models"] = [name for name, _count in node["models"].most_common(2)]
        node["cost"] = round(node["cost"], 6)
    return {
        "summary": {**summary, "nodes_truncated": len(ordered) > MAX_NODES},
        "nodes": ordered[:MAX_NODES],
        "edges": sorted(edges.values(), key=lambda edge: (str(edge["first_at"] or ""), edge["kind"])),
        "roles": roles,
        "messages": resolved_messages[-500:],
        "timeline": timeline,
        "insights": insights,
    }


def _closest_by_name(candidates: list[JsonObject], at: Any) -> str | None:
    if not candidates:
        return None
    if at is None:
        return str(candidates[0]["key"])
    started = [node for node in candidates if str(node.get("started_at") or "") <= str(at)]
    chosen = max(started, key=lambda node: str(node.get("started_at") or "")) if started else min(candidates, key=lambda node: str(node.get("started_at") or ""))
    return str(chosen["key"])


def _assign_depths(nodes: dict[str, JsonObject]) -> None:
    for node in nodes.values():
        depth = 0
        current = node["parent_key"]
        seen = {node["key"]}
        while current in nodes and current not in seen and depth < 256:
            seen.add(current)
            depth += 1
            current = nodes[current]["parent_key"]
        node["depth"] = depth


def _summary(traces: list[JsonObject], spans: list[JsonObject], links: list[JsonObject], nodes: list[JsonObject], agents: list[JsonObject], messages: list[JsonObject], roles: int) -> JsonObject:
    spawned = {link["trace_id"] for link in links if link.get("link_type") == "spawned_by"}
    starts = [str(span["started_at"]) for span in spans if span.get("started_at")]
    ends = [str(span.get("ended_at") or span.get("started_at")) for span in spans if span.get("started_at")]
    widest = max(nodes, key=lambda node: node["children"], default=None)
    return {
        "status": _swarm_status(
            Counter(str(trace.get("status")) for trace in traces),
            Counter(str(trace.get("status")) for trace in traces if trace["trace_id"] not in spawned),
        ),
        "traces": len(traces),
        "agents": len(agents),
        "running_agents": sum(1 for node in agents if node["status"] == "running"),
        "failed_agents": sum(1 for node in agents if node["status"] == "failed"),
        "roles": roles,  # distinct names in the graph, matching the role view
        "max_depth": max((node["depth"] for node in nodes), default=0),
        "max_fan_out": widest["children"] if widest else 0,
        "max_fan_out_key": widest["key"] if widest and widest["children"] else None,
        "llm_calls": sum(node["llm_calls"] for node in nodes),
        "tool_calls": sum(node["tool_calls"] for node in nodes),
        "tokens": sum(node["tokens"] for node in nodes),
        "cost": round(sum(node["cost"] for node in nodes), 6),
        "errors": sum(1 for span in spans if span.get("status") == "failed"),
        "messages": sum(1 for message in messages if message.get("kind") != "handoff"),
        "handoffs": sum(1 for message in messages if message.get("kind") == "handoff"),
        "spans": len(spans),
        "started_at": min(starts) if starts else None,
        "ended_at": max(ends) if ends else None,
        "duration_ms": _duration_ms(min(starts) if starts else None, max(ends) if ends else None),
    }


def _roles(nodes: list[JsonObject], edges: dict[tuple[str, str, str], JsonObject]) -> JsonObject:
    """The graph grouped by agent name: what a swarm of thousands of agents looks like at a glance."""
    lookup = {node["key"]: node for node in nodes}
    roles: dict[str, JsonObject] = {}
    for node in nodes:
        role = roles.setdefault(str(node["name"]), {"name": node["name"], "kind": node["kind"], "instances": 0, "running": 0, "failed": 0, "llm_calls": 0, "tool_calls": 0, "tokens": 0, "cost": 0.0, "min_depth": node["depth"]})
        role["instances"] += 1
        role["running"] += node["status"] == "running"
        role["failed"] += node["status"] == "failed"
        role["llm_calls"] += node["llm_calls"]
        role["tool_calls"] += node["tool_calls"]
        role["tokens"] += node["tokens"]
        role["cost"] += node["cost"]
        role["min_depth"] = min(role["min_depth"], node["depth"])
    role_edges: dict[tuple[str, str, str], JsonObject] = {}
    for edge in edges.values():
        source, target = lookup.get(edge["source"]), lookup.get(edge["target"])
        if source is None or target is None:
            continue
        key = (str(source["name"]), str(target["name"]), edge["kind"])
        entry = role_edges.setdefault(key, {"source": key[0], "target": key[1], "kind": edge["kind"], "count": 0})
        entry["count"] += edge["count"]
    for role in roles.values():
        role["cost"] = round(role["cost"], 6)
    return {"nodes": sorted(roles.values(), key=lambda role: (role["min_depth"], -role["instances"], str(role["name"]))), "edges": list(role_edges.values())}


def _timeline(nodes: list[JsonObject], summary: JsonObject) -> list[JsonObject]:
    start = _timestamp(summary.get("started_at"))
    end = _timestamp(summary.get("ended_at"))
    if start is None or end is None:
        return []
    span = max(end - start, 1.0)
    buckets = [{"at": None, "active": 0, "started": 0, "failed": 0} for _ in range(TIMELINE_BUCKETS)]
    width = span / TIMELINE_BUCKETS
    for index, bucket in enumerate(buckets):
        bucket["at"] = datetime.fromtimestamp(start + index * width, UTC).isoformat()
    for node in nodes:
        if node["kind"] != "agent":
            continue
        began = _timestamp(node.get("started_at"))
        if began is None:
            continue
        finished = _timestamp(node.get("ended_at")) or end
        first = min(int((began - start) / width), TIMELINE_BUCKETS - 1)
        last = min(int((finished - start) / width), TIMELINE_BUCKETS - 1)
        buckets[first]["started"] += 1
        for index in range(max(first, 0), max(last, first) + 1):
            buckets[index]["active"] += 1
        if node["status"] == "failed":
            buckets[last]["failed"] += 1
    return buckets


def _insights(nodes: list[JsonObject], agents: list[JsonObject], summary: JsonObject, unresolved: int) -> list[JsonObject]:
    insights: list[JsonObject] = []
    failed = [node for node in agents if node["status"] == "failed"]
    if failed:
        insights.append({
            "kind": "failed_agents",
            "severity": "danger",
            "title": f"{len(failed)} agent{'s' if len(failed) != 1 else ''} failed",
            "detail": failed[0]["error_message"] or f"{failed[0]['name']} failed",
            "node_key": failed[0]["key"],
        })
    widest = next((node for node in nodes if node["key"] == summary.get("max_fan_out_key")), None)
    if widest is not None and widest["children"] >= 5:
        insights.append({
            "kind": "fan_out",
            "severity": "warning" if widest["children"] >= 25 else "info",
            "title": f"{widest['name']} started {widest['children']} agents",
            "detail": "The widest fan-out in this swarm. Guardrails can cap it with max_child_agents.",
            "node_key": widest["key"],
        })
    if summary["max_depth"] >= 4:
        deepest = max(nodes, key=lambda node: node["depth"])
        insights.append({
            "kind": "depth",
            "severity": "warning",
            "title": f"Agents nested {summary['max_depth']} levels deep",
            "detail": f"{deepest['name']} is the deepest agent. Deep nesting is hard to follow and to stop; guardrails can cap it with max_agent_depth.",
            "node_key": deepest["key"],
        })
    total = summary["cost"]
    if total > 0 and agents:
        costly = max(agents, key=lambda node: node["cost"])
        share = costly["cost"] / total
        if share >= 0.4 and len(agents) > 1:
            insights.append({
                "kind": "cost_hotspot",
                "severity": "info",
                "title": f"{costly['name']} spent {round(share * 100)}% of the swarm's cost",
                "detail": f"${costly['cost']:.4f} of ${total:.4f} across {len(agents)} agents.",
                "node_key": costly["key"],
            })
    if unresolved:
        insights.append({
            "kind": "unknown_recipients",
            "severity": "info",
            "title": f"{unresolved} message{'s' if unresolved != 1 else ''} to agents outside this swarm",
            "detail": "The recipient never appeared in this swarm's traces: an external agent, or a worker that was not traced.",
            "node_key": None,
        })
    return insights


def _swarm_status(counts: Counter[str], roots: Counter[str] | None = None) -> str:
    """Running while any trace runs; otherwise the outcome of the traces that started the swarm.

    A worker that failed does not fail a swarm that recovered from it (failed agents are counted
    separately); a swarm with no top-level trace in view falls back to all of its traces.
    """
    if counts.get("running"):
        return "running"
    decisive = roots if roots else counts
    if decisive.get("failed"):
        return "failed"
    if not decisive:
        return "unknown"
    return "succeeded"


def _timestamp(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _duration_ms(start: Any, end: Any) -> float | None:
    began, finished = _timestamp(start), _timestamp(end)
    if began is None or finished is None:
        return None
    return round(max(finished - began, 0.0) * 1000, 3)

