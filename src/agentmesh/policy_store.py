"""Storage for policies, policy decisions, and halts (the kill switch).

Written in the SQL subset shared by SQLite and PostgreSQL. The store methods in
:mod:`agentmesh.storage` wrap these functions with locking and transactions.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from agentmesh.policy import Policy, PolicyError, parse_spec
from agentmesh.types import JsonObject, dumps_json, loads_json, new_id, utc_now

HALT_SCOPES = ("all", "swarm", "trace", "agent", "service")

POLICY_SCHEMA = [
    """
    create table if not exists policies (
      policy_id text primary key,
      name text not null unique,
      description text,
      mode text not null,
      enabled integer not null default 1,
      spec_json text not null,
      source_text text,
      created_at text not null,
      updated_at text not null
    )
    """,
    """
    create table if not exists policy_decisions (
      decision_id text primary key,
      trace_id text,
      span_id text,
      policy_id text,
      policy_name text,
      rule text not null,
      action text not null,
      enforced integer not null,
      kind text,
      target text,
      agent text,
      service text,
      reason text,
      details_json text not null,
      created_at text not null
    )
    """,
    "create index if not exists idx_policy_decisions_created on policy_decisions(created_at)",
    "create index if not exists idx_policy_decisions_trace on policy_decisions(trace_id, created_at)",
    """
    create table if not exists policy_halts (
      halt_id text primary key,
      scope text not null,
      value text,
      reason text,
      created_by text,
      created_at text not null,
      released_at text,
      released_by text
    )
    """,
    "create index if not exists idx_policy_halts_active on policy_halts(released_at, created_at)",
]


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def _policy_json(row: Any, include_source: bool = True) -> JsonObject:
    spec = loads_json(row["spec_json"]) or {}
    rules = spec.get("rules") if isinstance(spec.get("rules"), list) else []
    limits = spec.get("limits") if isinstance(spec.get("limits"), dict) else {}
    payload: JsonObject = {
        "policy_id": row["policy_id"],
        "name": row["name"],
        "description": row["description"],
        "mode": row["mode"],
        "enabled": bool(row["enabled"]),
        "spec": spec,
        "rule_count": len(rules),
        "limits": limits,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_source:
        payload["source_text"] = row["source_text"]
    return payload


def _find(conn: sqlite3.Connection, ref: str) -> Any:
    return conn.execute("select * from policies where policy_id = ? or name = ?", (ref, ref)).fetchone()


def _validated(payload: JsonObject) -> tuple[Policy, str | None]:
    """Accept ``{"spec": {...}}``, ``{"text": "yaml or json"}``, or the spec itself."""
    text = payload.get("text")
    if isinstance(text, str):
        document = parse_spec(text)
    elif isinstance(payload.get("spec"), dict):
        document = payload["spec"]
    else:
        document = {key: value for key, value in payload.items() if key not in {"enabled", "text"}}
    return Policy.from_spec(document), text if isinstance(text, str) else None


def validate_policy(payload: JsonObject) -> JsonObject:
    try:
        policy, _text = _validated(payload)
    except PolicyError as exc:
        return {"valid": False, "errors": exc.errors}
    return {"valid": True, "errors": [], "policy": policy.to_spec()}


def create_policy(conn: sqlite3.Connection, payload: JsonObject) -> JsonObject:
    policy, text = _validated(payload)
    if _find(conn, policy.name) is not None:
        raise PolicyError([f"a policy named '{policy.name}' already exists"])
    now = utc_now()
    policy_id = new_id("policy")
    conn.execute(
        """
        insert into policies (policy_id, name, description, mode, enabled, spec_json, source_text, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (policy_id, policy.name, policy.description, policy.mode, 1 if payload.get("enabled", True) else 0, dumps_json(policy.to_spec()), text, now, now),
    )
    return get_policy(conn, policy_id)  # type: ignore[return-value]


def update_policy(conn: sqlite3.Connection, ref: str, payload: JsonObject) -> JsonObject | None:
    row = _find(conn, ref)
    if row is None:
        return None
    changes: dict[str, Any] = {}
    if any(key in payload for key in ("spec", "text", "rules", "limits", "mode", "name")):
        merged = dict(payload)
        if "spec" not in merged and "text" not in merged:
            merged = {**(loads_json(row["spec_json"]) or {}), **{key: value for key, value in payload.items() if key != "enabled"}}
        policy, text = _validated(merged)
        if text is None and set(payload) <= {"mode", "enabled"}:
            text = _with_mode(row["source_text"], policy)
        other = _find(conn, policy.name)
        if other is not None and other["policy_id"] != row["policy_id"]:
            raise PolicyError([f"a policy named '{policy.name}' already exists"])
        changes.update(
            name=policy.name,
            description=policy.description,
            mode=policy.mode,
            spec_json=dumps_json(policy.to_spec()),
            source_text=text,
        )
    if "enabled" in payload:
        changes["enabled"] = 1 if payload["enabled"] else 0
    if changes:
        changes["updated_at"] = utc_now()
        assignments = ", ".join(f"{column} = ?" for column in changes)
        conn.execute(f"update policies set {assignments} where policy_id = ?", (*changes.values(), row["policy_id"]))
    return get_policy(conn, row["policy_id"])


def _with_mode(source: str | None, policy: Policy) -> str | None:
    """Keep a policy's saved text (and its comments) when only its mode changes."""
    if not source:
        return None
    if source.lstrip().startswith("{"):
        return json.dumps(policy.to_spec(), indent=2)
    updated, count = re.subn(r"^mode:[^\n#]*?(?=\s*(#|$))", f"mode: {policy.mode}", source, count=1, flags=re.MULTILINE)
    if count == 0:
        updated, count = re.subn(r"^(name:[^\n]*\n)", lambda match: f"{match.group(1)}mode: {policy.mode}\n", source, count=1, flags=re.MULTILINE)
    return updated if count else None


def delete_policy(conn: sqlite3.Connection, ref: str) -> bool:
    row = _find(conn, ref)
    if row is None:
        return False
    conn.execute("delete from policies where policy_id = ?", (row["policy_id"],))
    return True


def get_policy(conn: sqlite3.Connection, ref: str) -> JsonObject | None:
    row = _find(conn, ref)
    return _policy_json(row) if row is not None else None


def list_policies(conn: sqlite3.Connection) -> list[JsonObject]:
    rows = conn.execute("select * from policies order by created_at asc").fetchall()
    return [_policy_json(row, include_source=False) for row in rows]


def enabled_policies(conn: sqlite3.Connection) -> list[Policy]:
    """Enabled policies as :class:`Policy` objects, skipping any that no longer validate."""
    policies: list[Policy] = []
    for row in conn.execute("select policy_id, spec_json from policies where enabled = 1 order by created_at asc").fetchall():
        try:
            policies.append(Policy.from_spec(loads_json(row["spec_json"]) or {}, policy_id=row["policy_id"]))
        except PolicyError:
            continue
    return policies


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


def save_decision(conn: sqlite3.Connection, decision: JsonObject) -> None:
    """Insert one decision; re-delivering the same ``decision_id`` is a no-op."""
    conn.execute(
        """
        insert or ignore into policy_decisions
        (decision_id, trace_id, span_id, policy_id, policy_name, rule, action, enforced, kind, target, agent, service, reason, details_json, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision.get("decision_id") or new_id("decision"),
            decision.get("trace_id"),
            decision.get("span_id"),
            decision.get("policy_id"),
            decision.get("policy_name"),
            decision.get("rule") or "unknown",
            decision.get("action") or "deny",
            1 if decision.get("enforced", True) else 0,
            decision.get("kind"),
            decision.get("target"),
            decision.get("agent"),
            decision.get("service"),
            decision.get("reason"),
            dumps_json(decision.get("details") or {}),
            decision.get("created_at") or utc_now(),
        ),
    )


def decision_exists(conn: sqlite3.Connection, decision_id: str) -> bool:
    return conn.execute("select 1 from policy_decisions where decision_id = ?", (decision_id,)).fetchone() is not None


def list_decisions(
    conn: sqlite3.Connection,
    limit: int = 100,
    trace_id: str | None = None,
    action: str | None = None,
    since: str | None = None,
) -> list[JsonObject]:
    clauses: list[str] = []
    params: list[Any] = []
    if trace_id:
        clauses.append("trace_id = ?")
        params.append(trace_id)
    if action == "blocked":
        clauses.append("action = 'deny' and enforced = 1")
    elif action == "would_block":
        clauses.append("enforced = 0 and action in ('deny', 'require_approval')")
    elif action:
        clauses.append("action = ?")
        params.append(action)
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"select * from policy_decisions {where} order by created_at desc limit ?",
        (*params, max(min(int(limit), 1000), 1)),
    ).fetchall()
    return [
        {
            "decision_id": row["decision_id"],
            "trace_id": row["trace_id"],
            "span_id": row["span_id"],
            "policy_id": row["policy_id"],
            "policy_name": row["policy_name"],
            "rule": row["rule"],
            "action": row["action"],
            "enforced": bool(row["enforced"]),
            "kind": row["kind"],
            "target": row["target"],
            "agent": row["agent"],
            "service": row["service"],
            "reason": row["reason"],
            "details": loads_json(row["details_json"]) or {},
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def decision_summary(conn: sqlite3.Connection, since: str) -> JsonObject:
    row = conn.execute(
        """
        select
          sum(case when action = 'deny' and enforced = 1 then 1 else 0 end) as blocked,
          sum(case when action = 'require_approval' and enforced = 1 then 1 else 0 end) as approvals,
          sum(case when enforced = 0 and action in ('deny', 'require_approval') then 1 else 0 end) as would_block,
          sum(case when action = 'warn' then 1 else 0 end) as warnings,
          count(*) as total
        from policy_decisions
        where created_at >= ?
        """,
        (since,),
    ).fetchone()
    return {key: int(row[key] or 0) for key in ("blocked", "approvals", "would_block", "warnings", "total")}


# ---------------------------------------------------------------------------
# Halts (kill switch)
# ---------------------------------------------------------------------------


def _halt_json(row: Any) -> JsonObject:
    return {
        "halt_id": row["halt_id"],
        "scope": row["scope"],
        "value": row["value"],
        "reason": row["reason"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "released_at": row["released_at"],
        "released_by": row["released_by"],
        "active": row["released_at"] is None,
    }


def create_halt(conn: sqlite3.Connection, payload: JsonObject) -> JsonObject:
    scope = str(payload.get("scope") or "")
    value = payload.get("value")
    if scope not in HALT_SCOPES:
        raise PolicyError([f"scope must be one of {', '.join(HALT_SCOPES)}"])
    if scope != "all" and not (isinstance(value, str) and value.strip()):
        raise PolicyError([f"a '{scope}' halt needs a value (the {scope} to stop)"])
    reason = payload.get("reason")
    created_by = payload.get("created_by")
    halt_id = new_id("halt")
    conn.execute(
        """
        insert into policy_halts (halt_id, scope, value, reason, created_by, created_at, released_at, released_by)
        values (?, ?, ?, ?, ?, ?, null, null)
        """,
        (
            halt_id,
            scope,
            None if scope == "all" else str(value).strip(),
            str(reason)[:500] if reason not in (None, "") else None,
            str(created_by)[:200] if created_by not in (None, "") else None,
            utc_now(),
        ),
    )
    return _halt_json(conn.execute("select * from policy_halts where halt_id = ?", (halt_id,)).fetchone())


def release_halt(conn: sqlite3.Connection, halt_id: str, released_by: str | None = None) -> JsonObject | None:
    row = conn.execute("select * from policy_halts where halt_id = ?", (halt_id,)).fetchone()
    if row is None:
        return None
    if row["released_at"] is None:
        conn.execute("update policy_halts set released_at = ?, released_by = ? where halt_id = ?", (utc_now(), released_by, halt_id))
        row = conn.execute("select * from policy_halts where halt_id = ?", (halt_id,)).fetchone()
    return _halt_json(row)


def list_halts(conn: sqlite3.Connection, active_only: bool = True, limit: int = 100) -> list[JsonObject]:
    where = "where released_at is null" if active_only else ""
    rows = conn.execute(
        f"select * from policy_halts {where} order by created_at desc limit ?", (max(min(int(limit), 1000), 1),)
    ).fetchall()
    return [_halt_json(row) for row in rows]


def runtime_config(conn: sqlite3.Connection) -> JsonObject:
    """What an SDK needs to enforce: enabled policy specs and active halts."""
    rows = conn.execute("select policy_id, spec_json from policies where enabled = 1 order by created_at asc").fetchall()
    return {
        "policies": [{"policy_id": row["policy_id"], "spec": loads_json(row["spec_json"]) or {}} for row in rows],
        "halts": list_halts(conn, active_only=True, limit=1000),
        "generated_at": utc_now(),
    }


def get_approval(conn: sqlite3.Connection, approval_id: str) -> JsonObject | None:
    row = conn.execute(
        "select approval_id, trace_id, agent, tool, arguments_json, status, reason, created_at, resolved_at from approvals where approval_id = ?",
        (approval_id,),
    ).fetchone()
    if row is None:
        return None
    return {
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
