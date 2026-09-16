"""Limits for a whole swarm, counted across every process and trace in it.

Per-trace limits (``limits:`` in a policy) are counted inside the agent's own process, so they
cannot see a swarm that spreads over machines: 200 workers each obeying "50 tool calls" still make
10,000 calls. Swarm limits (``swarm:`` in a policy) are evaluated on the server from the spans it
has received::

    name: swarm-safety
    mode: enforce
    swarm:
      max_agents: 500                 # agents started in the swarm
      max_concurrent_agents: 200      # running at the same time
      max_spawn_rate_per_minute: 120  # how fast it is growing
      max_cost_usd: 50
      max_tokens: 5_000_000
      max_duration_minutes: 30
      match: {service: research-*}    # optional: only swarms whose name/service/environment match

When a swarm breaks a limit in ``enforce`` mode, AgentMesh halts the swarm: every agent in it fails
its next call, in every process, and the halt stays until a person releases it on the Guardrails
page. In ``monitor`` mode the breach is recorded and nothing is stopped.

Enforcement is not instant: a swarm is stopped once its spans have been exported (about a second),
the server has evaluated the limits (``AGENTMESH_SWARM_LIMIT_INTERVAL_SECONDS``, default 15), and
the agents have polled the halt (``AGENTMESH_GUARDRAILS_REFRESH_SECONDS``, default 5). Use per-trace
limits for instant, in-process caps and swarm limits for the total.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from agentmesh.policy import SWARM_LIMITS, Policy, glob_match
from agentmesh.policy_store import create_halt, decision_exists, enabled_policies, list_halts, save_decision
from agentmesh.types import JsonObject, utc_now

logger = logging.getLogger("agentmesh.swarm_limits")

# Only swarms that are still running (or were active in the last few minutes) are worth halting.
RECENTLY_ACTIVE_MINUTES = 5
DEFAULT_INTERVAL_SECONDS = 15.0
AGENT_EVENTS_SQL = "('agent.invoke', 'agent.started')"
# Counts must be exceeded ("more than N agents"); spend, tokens, and time are reached ("at $50").
COUNT_LIMITS = {"max_agents", "max_concurrent_agents", "max_spawn_rate_per_minute"}


def swarm_usage(conn: sqlite3.Connection, swarm_ids: list[str] | None = None, now: datetime | None = None) -> dict[str, JsonObject]:
    """What each swarm has used so far: agents, concurrency, spawn rate, spend, tokens, and age."""
    moment = now or datetime.now(UTC)
    minute_ago = (moment - timedelta(minutes=1)).isoformat()
    where, params = "", []
    if swarm_ids is not None:
        if not swarm_ids:
            return {}
        where = f"where st.swarm_id in ({', '.join('?' for _ in swarm_ids)})"
        params = list(swarm_ids)
    rows = conn.execute(
        f"""
        select st.swarm_id,
          sum(case when sp.event_type in {AGENT_EVENTS_SQL} then 1 else 0 end) as agents,
          sum(case when sp.event_type in {AGENT_EVENTS_SQL} and sp.status = 'running' then 1 else 0 end) as concurrent_agents,
          sum(case when sp.event_type in {AGENT_EVENTS_SQL} and sp.started_at >= ? then 1 else 0 end) as spawn_rate_per_minute,
          sum(sp.estimated_cost) as cost_usd,
          sum(sp.total_tokens) as tokens,
          min(sp.started_at) as started_at,
          max(coalesce(sp.ended_at, sp.started_at)) as last_activity
        from swarm_traces st join spans sp on sp.trace_id = st.trace_id
        {where}
        group by st.swarm_id
        """,
        (minute_ago, *params),
    ).fetchall()
    usage = {
        row["swarm_id"]: {
            "swarm_id": row["swarm_id"],
            "agents": int(row["agents"] or 0),
            "concurrent_agents": int(row["concurrent_agents"] or 0),
            "spawn_rate_per_minute": int(row["spawn_rate_per_minute"] or 0),
            "cost_usd": round(float(row["cost_usd"] or 0.0), 6),
            "tokens": int(row["tokens"] or 0),
            "started_at": row["started_at"],
            "last_activity": row["last_activity"],
            "running_traces": 0,
        }
        for row in rows
    }
    if not usage:
        return {}
    marks = ", ".join("?" for _ in usage)
    for row in conn.execute(
        f"""
        select st.swarm_id, sum(case when wr.status = 'running' then 1 else 0 end) as running_traces
        from swarm_traces st join workflow_runs wr on wr.trace_id = st.trace_id
        where st.swarm_id in ({marks})
        group by st.swarm_id
        """,
        list(usage),
    ).fetchall():
        usage[row["swarm_id"]]["running_traces"] = int(row["running_traces"] or 0)
    for entry in usage.values():
        # A finished swarm's age stops at its last span; a running one keeps ageing.
        end = moment if entry["running_traces"] else _timestamp(entry["last_activity"]) or moment
        started = _timestamp(entry["started_at"])
        entry["duration_minutes"] = round(max((end - started).total_seconds(), 0.0) / 60, 3) if started else 0.0
    return usage


def applies_to(policy: Policy, swarm: JsonObject) -> bool:
    """True when a policy's ``swarm.match`` covers this swarm (no match: every swarm)."""
    for key, patterns in policy.swarm_match.items():
        value = swarm.get(key) or swarm.get(f"{key}_name")  # service -> service_name
        if not glob_match(value if value is None else str(value), patterns):
            return False
    return True


def breaches(policies: list[Policy], swarm: JsonObject, usage: JsonObject) -> list[JsonObject]:
    """Every swarm limit this swarm has broken, worst first."""
    found: list[JsonObject] = []
    for policy in policies:
        if not policy.swarm_limits or not applies_to(policy, swarm):
            continue
        for limit, maximum in policy.swarm_limits.items():
            used = float(usage.get(_usage_key(limit), 0) or 0)
            crossed = used > maximum if limit in COUNT_LIMITS else used >= maximum
            if crossed:
                found.append({
                    "swarm_id": swarm["swarm_id"],
                    "swarm_name": swarm.get("name") or swarm["swarm_id"],
                    "policy": policy.name,
                    "policy_id": policy.policy_id,
                    "enforced": policy.mode == "enforce",
                    "rule": f"swarm_limit:{limit}",
                    "limit": limit,
                    "max": maximum,
                    "used": used,
                    "reason": _reason(limit, maximum, used, policy.name),
                })
    return found


def check_swarm_limits(conn: sqlite3.Connection, now: datetime | None = None, enforce: bool = True) -> list[JsonObject]:
    """Evaluate swarm limits once: halt swarms that broke one, record every breach.

    With ``enforce=False`` nothing is written: it reports what a real check would do.
    """
    moment = now or datetime.now(UTC)
    policies = [policy for policy in enabled_policies(conn) if policy.swarm_limits]
    if not policies:
        return []
    cutoff = (moment - timedelta(minutes=RECENTLY_ACTIVE_MINUTES)).isoformat()
    swarms = [
        dict(row)
        for row in conn.execute(
            """
            select s.swarm_id, s.name, s.service_name, s.environment, s.last_seen_at
            from swarms s
            where s.last_seen_at >= ? or exists (
              select 1 from swarm_traces st join workflow_runs wr on wr.trace_id = st.trace_id
              where st.swarm_id = s.swarm_id and wr.status = 'running'
            )
            """,
            (cutoff,),
        ).fetchall()
    ]
    if not swarms:
        return []
    usage = swarm_usage(conn, [swarm["swarm_id"] for swarm in swarms], moment)
    halted = {halt["value"] for halt in list_halts(conn, active_only=True, limit=1000) if halt["scope"] == "swarm"}
    results: list[JsonObject] = []
    for swarm in swarms:
        for breach in breaches(policies, swarm, usage.get(swarm["swarm_id"], {})):
            already = breach["swarm_id"] in halted
            decision_id = f"swarm_{breach['swarm_id']}_{breach['rule']}"
            # Halt on the first breach of a limit only: releasing the halt is a person's decision,
            # and a swarm that stays over the limit must not be halted again behind their back.
            acted = decision_exists(conn, decision_id)
            if breach["enforced"] and enforce and not already and not acted:
                create_halt(conn, {
                    "scope": "swarm",
                    "value": breach["swarm_id"],
                        "reason": breach["reason"],
                    "created_by": f"policy:{breach['policy']}",
                })
                halted.add(breach["swarm_id"])
            if enforce:
                save_decision(conn, {
                    # One row per swarm and limit, however many times the check runs.
                    "decision_id": decision_id,
                    "policy_id": breach["policy_id"],
                    "policy_name": breach["policy"],
                    "rule": breach["rule"],
                    "action": "deny",
                    "enforced": breach["enforced"],
                    "kind": "swarm",
                    "target": breach["swarm_name"],
                "reason": breach["reason"],
                    "details": {"swarm_id": breach["swarm_id"], "limit": breach["limit"], "max": breach["max"], "used": breach["used"]},
                    "created_at": utc_now(),
                })
            results.append({
                **breach,
                "halted": breach["enforced"] and enforce and not already and not acted,
                "already_halted": already,
                "released": acted and not already,  # a person lifted this halt; it is not re-applied
            })
    return results


def swarm_limit_status(conn: sqlite3.Connection, swarm: JsonObject, now: datetime | None = None) -> JsonObject:
    """Usage and every swarm limit that applies to one swarm, for the dashboard. Writes nothing."""
    usage = swarm_usage(conn, [swarm["swarm_id"]], now).get(swarm["swarm_id"], {})
    policies = [policy for policy in enabled_policies(conn) if policy.swarm_limits and applies_to(policy, swarm)]
    limits = [
        {
            "policy": policy.name,
            "policy_id": policy.policy_id,
            "enforced": policy.mode == "enforce",
            "limit": limit,
            "label": SWARM_LIMITS[limit],
            "max": maximum,
            "used": float(usage.get(_usage_key(limit), 0) or 0),
            "breached": (float(usage.get(_usage_key(limit), 0) or 0) > maximum) if limit in COUNT_LIMITS else (float(usage.get(_usage_key(limit), 0) or 0) >= maximum),
        }
        for policy in policies
        for limit, maximum in policy.swarm_limits.items()
    ]
    limits.sort(key=lambda item: (not item["breached"], -(item["used"] / item["max"] if item["max"] else 0)))
    return {"usage": usage, "limits": limits}


def _usage_key(limit: str) -> str:
    return limit.removeprefix("max_")


def _reason(limit: str, maximum: float, used: float, policy: str) -> str:
    text = {
        "max_agents": f"Swarm started {int(used):,} agents, past its limit of {int(maximum):,}",
        "max_concurrent_agents": f"Swarm has {int(used):,} agents running at once, past its limit of {int(maximum):,}",
        "max_spawn_rate_per_minute": f"Swarm started {int(used):,} agents in the last minute, past its limit of {int(maximum):,} a minute",
        "max_cost_usd": f"Swarm spent ${used:,.2f}, reaching its limit of ${maximum:,.2f}",
        "max_tokens": f"Swarm used {int(used):,} tokens, reaching its limit of {int(maximum):,}",
        "max_duration_minutes": f"Swarm has run {used:,.0f} minutes, reaching its limit of {maximum:,.0f}",
    }[limit]
    return f"{text} (policy {policy})"


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class SwarmLimitScheduler:
    """Background thread that evaluates swarm limits every ``interval`` seconds."""

    def __init__(self, store: Any, interval: float) -> None:
        self.store = store
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.interval <= 0 or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="agentmesh-swarm-limits", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                for breach in self.store.check_swarm_limits():
                    if breach["halted"]:
                        logger.warning("Halted swarm %s: %s", breach["swarm_id"], breach["reason"])
            except Exception:
                logger.exception("swarm limit check failed")


def scheduler_interval() -> float:
    try:
        return float(os.getenv("AGENTMESH_SWARM_LIMIT_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)))
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS
