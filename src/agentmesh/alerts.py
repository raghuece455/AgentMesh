"""Alert rules evaluated against recorded traces, delivered to webhooks (generic JSON, Slack, Discord).

Rule kinds (``threshold`` meaning in brackets):

* ``failure_rate``  - share of runs that failed in the window [0..1]; needs ``min_runs`` runs (default 5)
* ``failure_count`` - failed runs in the window [count]
* ``cost``          - total spend in the window [USD]
* ``trace_cost``    - any single trace in the window costing at least this much [USD]
* ``latency_p95``   - p95 run duration in the window [ms]; needs ``min_runs`` runs (default 5)
* ``loop_detected`` - a trace called the same tool with the same arguments at least N times [count]

Swarm and egress anomalies, for runs that spread over many agents, processes, and traces:

* ``new_destination``  - a host or resource reached for the first time [accesses before alerting]
* ``swarm_agents``     - agents started in one swarm [count]
* ``swarm_spawn_rate`` - agents started per minute in one swarm [count]
* ``swarm_cost``       - spend by one swarm [USD]
* ``swarm_errors``     - failed traces in one swarm [count]
* ``swarm_loop``       - two agents handing work back and forth [messages between the pair]

Aggregate kinds notify when the threshold is crossed, remind every ``cooldown_minutes`` while it
stays crossed, and send a ``resolved`` notification when it recovers. Per-item kinds
(``trace_cost``, ``loop_detected``, ``new_destination``, and every swarm kind) notify once per
offending trace, destination, or swarm, and never resolve: an anomaly happened, it does not unhappen.

A swarm kind measures the swarm's totals across every process in it; the window chooses which
swarms are looked at — those active in it. Alerts tell a person; they stop nothing. To stop a swarm
that is growing out of control, give it ``swarm:`` limits in a policy (see :mod:`agentmesh.swarm_limits`).

The server checks rules every ``AGENTMESH_ALERT_INTERVAL_SECONDS`` (default 60, ``0`` disables);
``agentmesh alerts check`` runs one pass, e.g. from cron.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from agentmesh.access import CHUNK
from agentmesh.access import KINDS as ACCESS_KINDS
from agentmesh.policy import glob_match
from agentmesh.swarm_limits import swarm_usage
from agentmesh.types import JsonObject, dumps_json, loads_json, new_id, utc_now

logger = logging.getLogger("agentmesh.alerts")

ALERT_KINDS: dict[str, str] = {
    "failure_rate": "Share of runs that failed in the window (0-1)",
    "failure_count": "Failed runs in the window",
    "cost": "Total spend in the window (USD)",
    "trace_cost": "Any single trace costing at least this much (USD)",
    "latency_p95": "p95 run duration in the window (ms)",
    "loop_detected": "Same tool called with the same arguments at least N times in one trace",
    "new_destination": "A host or resource reached for the first time, after at least N accesses",
    "swarm_agents": "Agents started in one swarm",
    "swarm_spawn_rate": "Agents started per minute in one swarm",
    "swarm_cost": "Spend by one swarm (USD)",
    "swarm_errors": "Failed traces in one swarm",
    "swarm_loop": "Two agents in a swarm handing work back and forth N times",
}
KIND_GROUPS: dict[str, str] = {
    **{kind: "Runs" for kind in ("failure_rate", "failure_count", "cost", "trace_cost", "latency_p95", "loop_detected")},
    "new_destination": "Access",
    **{kind: "Swarms" for kind in ("swarm_agents", "swarm_spawn_rate", "swarm_cost", "swarm_errors", "swarm_loop")},
}
SWARM_KINDS = {"swarm_agents", "swarm_spawn_rate", "swarm_cost", "swarm_errors", "swarm_loop"}
PER_TRACE_KINDS = {"trace_cost", "loop_detected"}
# Kinds that notify once per offending item rather than firing and resolving on a threshold.
PER_ITEM_KINDS = PER_TRACE_KINDS | SWARM_KINDS | {"new_destination"}
WEBHOOK_FORMATS = {"json", "slack", "discord"}
FILTER_KEYS = {"workflow", "environment", "service", "source", "min_runs", "swarm", "access_kind"}
# Filters that only make sense for some kinds: a workflow name means nothing to a swarm-wide rule.
RUN_FILTER_KEYS = {"workflow", "source", "min_runs"}
MAX_SEEN_KEYS = 1000
MAX_KEY_CHARS = 120  # a remembered offender key; targets can be long file paths
MAX_ITEMS_PER_ALERT = 50  # offenders named in one notification; the rest are reported by the next check
MAX_SWARMS = 200  # most recently active swarms considered in one check


def parse_minutes(value: Any, default: int) -> int:
    """Accept 15, "15", "15m", "2h", or "1d"."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minutes = int(value)
    else:
        match = re.fullmatch(r"\s*(\d+)\s*([mhd]?)\s*", str(value).lower())
        if not match:
            raise ValueError(f"invalid duration: {value!r} (use e.g. 15m, 2h, 1d)")
        minutes = int(match.group(1)) * {"": 1, "m": 1, "h": 60, "d": 1440}[match.group(2)]
    if minutes < 1:
        raise ValueError("durations must be at least 1 minute")
    return minutes


def create_rule(conn: Any, payload: JsonObject) -> JsonObject:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("alert rule name is required")
    if conn.execute("select 1 from alert_rules where name = ?", (name,)).fetchone() is not None:
        raise ValueError(f"alert rule already exists: {name}")
    values = _validated(payload, partial=False)
    now = utc_now()
    rule_id = new_id("alert")
    conn.execute(
        """
        insert into alert_rules
        (rule_id, name, kind, threshold, window_minutes, cooldown_minutes, filters_json, channel_json, enabled,
         state, state_json, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?, ?)
        """,
        (
            rule_id,
            name,
            values["kind"],
            values["threshold"],
            values["window_minutes"],
            values["cooldown_minutes"],
            json.dumps(values["filters"], sort_keys=True),
            json.dumps(values["channel"], sort_keys=True),
            1 if values["enabled"] else 0,
            "{}",
            now,
            now,
        ),
    )
    return get_rule(conn, rule_id)  # type: ignore[return-value]


def update_rule(conn: Any, ref: str, payload: JsonObject) -> JsonObject | None:
    row = _rule_row(conn, ref)
    if row is None:
        return None
    current = _rule_to_json(row, reveal=True)
    merged = {**current, **{key: value for key, value in payload.items() if value is not None}}
    for short, column in (("window", "window_minutes"), ("cooldown", "cooldown_minutes")):
        if payload.get(short) is not None and payload.get(column) is None:
            merged.pop(column, None)
    if isinstance(payload.get("channel"), dict):
        # Keep the stored URL/secret when the client omits them or echoes back the masked values.
        incoming = dict(payload["channel"])
        if incoming.get("url") is None or "/***" in str(incoming.get("url")):
            incoming["url"] = current["channel"].get("url")
        if incoming.get("secret") is None or incoming.get("secret") == "***":
            incoming["secret"] = current["channel"].get("secret")
        merged["channel"] = {**current["channel"], **incoming}
        if incoming["url"] != current["channel"].get("url") and not payload["channel"].get("format"):
            # A new URL without an explicit format: detect it again (Slack -> Discord needs a different payload).
            merged["channel"].pop("format", None)
    values = _validated(merged, partial=True)
    channel = values["channel"]
    conn.execute(
        """
        update alert_rules set kind = ?, threshold = ?, window_minutes = ?, cooldown_minutes = ?, filters_json = ?,
          channel_json = ?, enabled = ?, updated_at = ?
        where rule_id = ?
        """,
        (
            values["kind"],
            values["threshold"],
            values["window_minutes"],
            values["cooldown_minutes"],
            json.dumps(values["filters"], sort_keys=True),
            json.dumps(channel, sort_keys=True),
            1 if values["enabled"] else 0,
            utc_now(),
            row["rule_id"],
        ),
    )
    return get_rule(conn, str(row["rule_id"]))


def delete_rule(conn: Any, ref: str) -> bool:
    row = _rule_row(conn, ref)
    if row is None:
        return False
    conn.execute("delete from alert_rules where rule_id = ?", (row["rule_id"],))
    return True


def get_rule(conn: Any, ref: str, reveal: bool = False) -> JsonObject | None:
    row = _rule_row(conn, ref)
    return _rule_to_json(row, reveal) if row is not None else None


def list_rules(conn: Any, reveal: bool = False) -> list[JsonObject]:
    rows = conn.execute("select * from alert_rules order by created_at asc").fetchall()
    return [_rule_to_json(row, reveal) for row in rows]


def list_events(conn: Any, limit: int = 100, rule: str | None = None) -> list[JsonObject]:
    params: list[Any] = []
    clause = ""
    if rule:
        clause = "where rule_id = ? or rule_name = ?"
        params.extend([rule, rule])
    rows = conn.execute(
        f"select * from alert_events {clause} order by created_at desc limit ?",
        (*params, max(min(int(limit), 1000), 1)),
    ).fetchall()
    return [_event_to_json(row) for row in rows]


def check_rules(conn: Any, now: datetime | None = None) -> list[JsonObject]:
    """Evaluate every enabled rule once. Records alert events and returns them, each with its rule's
    unmasked channel and whether to notify. Delivery happens outside so no lock is held during I/O."""
    now = now or datetime.now(UTC)
    fired: list[JsonObject] = []
    for row in conn.execute("select * from alert_rules where enabled = 1 order by created_at asc").fetchall():
        rule = _rule_to_json(row, reveal=True)
        state = loads_json(row["state_json"]) or {}
        try:
            value, details, offenders = _measure(conn, rule, now)
        except Exception as exc:  # a broken rule must not stop the others
            logger.warning("alert rule %s failed to evaluate: %s", rule["name"], exc)
            continue
        last_triggered = _parse_time(row["last_triggered_at"])
        cooled = last_triggered is None or now - last_triggered >= timedelta(minutes=int(rule["cooldown_minutes"]))
        new_state = row["state"]
        event: JsonObject | None = None
        if rule["kind"] in PER_ITEM_KINDS:
            seen = list(state.get("seen") or state.get("seen_trace_ids") or [])
            fresh = [item for item in offenders if _offender_key(item) not in seen]
            new_state = "firing" if offenders else "ok"
            if fresh and cooled:
                details = {**details, "items": fresh, "traces": [item for item in fresh if item.get("trace_id")]}
                event = _record_event(conn, rule, "firing", value, _message(rule, value, details), details, now)
                state["seen"] = (seen + [_offender_key(item) for item in fresh])[-MAX_SEEN_KEYS:]
                state.pop("seen_trace_ids", None)
        else:
            breached = value is not None and value >= float(rule["threshold"])
            if breached and (row["state"] != "firing" or cooled):
                event = _record_event(conn, rule, "firing", value, _message(rule, value, details), details, now)
                new_state = "firing"
            elif not breached and row["state"] == "firing" and value is not None:
                event = _record_event(conn, rule, "resolved", value, _message(rule, value, details, resolved=True), details, now)
                new_state = "ok"
        conn.execute(
            """
            update alert_rules set state = ?, state_json = ?, last_value = ?, last_evaluated_at = ?,
              last_triggered_at = ?
            where rule_id = ?
            """,
            (
                new_state,
                json.dumps(state, sort_keys=True),
                value,
                now.isoformat(),
                now.isoformat() if event is not None and event["status"] == "firing" else row["last_triggered_at"],
                row["rule_id"],
            ),
        )
        if event is not None:
            channel = rule["channel"]
            notify = bool(channel.get("url")) and (event["status"] == "firing" or channel.get("notify_resolved", True))
            fired.append({**event, "channel": channel, "rule": _public_rule(rule), "notify": notify})
    return fired


def mark_delivered(conn: Any, alert_id: str, error: str | None) -> None:
    conn.execute(
        "update alert_events set delivered = ?, delivery_error = ? where alert_id = ?",
        (0 if error else 1, error, alert_id),
    )


def test_payload(rule: JsonObject) -> JsonObject:
    now = utc_now()
    return {
        "alert_id": new_id("alert_test"),
        "rule_id": rule["rule_id"],
        "rule_name": rule["name"],
        "kind": rule["kind"],
        "status": "test",
        "value": None,
        "threshold": rule["threshold"],
        "message": f"Test notification for alert rule '{rule['name']}'. If you can read this, delivery works.",
        "details": {},
        "created_at": now,
        "rule": _public_rule(rule),
        "channel": rule["channel"],
    }


# -- delivery -----------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # never follow redirects to other hosts
        return None


def deliver(event: JsonObject, timeout: float = 10.0) -> str | None:
    """POST an alert to its webhook. Returns None on success or an error message."""
    channel = event.get("channel") or {}
    url = str(channel.get("url") or "")
    if not url:
        return None
    body = json.dumps(render_payload(event, str(channel.get("format") or "json"))).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "agentmesh-alerts"}
    secret = channel.get("secret")
    if secret:
        timestamp = str(int(time.time()))
        digest = hmac.new(str(secret).encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()
        headers["X-AgentMesh-Timestamp"] = timestamp
        headers["X-AgentMesh-Signature"] = f"sha256={digest}"
    opener = urllib.request.build_opener(_NoRedirect)
    error: str | None = None
    for attempt in range(2):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with opener.open(request, timeout=timeout) as response:
                response.read(4096)
                return None
        except urllib.error.HTTPError as exc:
            error = f"HTTP {exc.code}"
            if exc.code < 500 and exc.code != 429:
                return error
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
        if attempt == 0:
            time.sleep(1.0)
    return error


def render_payload(event: JsonObject, fmt: str) -> JsonObject:
    rule = event.get("rule") or {}
    status = str(event.get("status"))
    base_url = os.getenv("AGENTMESH_PUBLIC_URL", "").rstrip("/")
    details = event.get("details") or {}
    traces = [item["trace_id"] for item in details.get("traces", [])][:5]
    swarms = [item["swarm_id"] for item in details.get("items", []) if item.get("swarm_id")][:5]
    links = (
        [f"{base_url}/?trace={trace_id}" for trace_id in traces] + [f"{base_url}/?page=swarms&swarm={swarm_id}" for swarm_id in swarms]
        if base_url
        else []
    )
    title = f"[AgentMesh] {status.upper()}: {event.get('rule_name')}"
    if fmt == "slack":
        text = f"*{title}*\n{event.get('message')}"
        if links:
            text += "\n" + "\n".join(f"<{link}|{link.rsplit('=', 1)[-1]}>" for link in links)
        elif traces:
            text += "\nTraces: " + ", ".join(f"`{trace_id}`" for trace_id in traces)
        return {"text": text}
    if fmt == "discord":
        description = str(event.get("message"))
        if links or traces:
            description += "\n" + "\n".join(links or [f"`{trace_id}`" for trace_id in traces])
        color = {"firing": 0xE5484D, "resolved": 0x30A46C}.get(status, 0x3E63DD)
        return {"embeds": [{"title": title, "description": description[:4000], "color": color, "timestamp": event.get("created_at")}]}
    return {
        "type": "agentmesh.alert",
        "alert_id": event.get("alert_id"),
        "status": status,
        "rule": rule,
        "value": event.get("value"),
        "threshold": event.get("threshold"),
        "message": event.get("message"),
        "details": event.get("details") or {},
        "created_at": event.get("created_at"),
        "links": links,
    }


class AlertScheduler:
    """Background thread that runs ``store.check_alerts()`` every ``interval`` seconds."""

    def __init__(self, store: Any, interval: float) -> None:
        self.store = store
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.interval <= 0 or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="agentmesh-alerts", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.store.check_alerts()
            except Exception:
                logger.exception("alert check failed")


def scheduler_interval() -> float:
    try:
        return float(os.getenv("AGENTMESH_ALERT_INTERVAL_SECONDS", "60"))
    except ValueError:
        return 60.0


# -- measurement ------------------------------------------------------------------------------


def _measure(conn: Any, rule: JsonObject, now: datetime) -> tuple[float | None, JsonObject, list[JsonObject]]:
    kind = str(rule["kind"])
    since = (now - timedelta(minutes=int(rule["window_minutes"]))).isoformat()
    filters = rule["filters"]
    if kind == "new_destination":
        return _new_destinations(conn, rule, since)
    if kind in SWARM_KINDS:
        return _swarm_anomalies(conn, rule, since, now)
    run_where, run_params = _run_filters(filters)
    min_runs = int(filters.get("min_runs") or 5)
    if kind in {"failure_rate", "failure_count"}:
        row = conn.execute(
            f"""
            select count(*) as total, coalesce(sum(case when wr.status = 'failed' then 1 else 0 end), 0) as failed
            from workflow_runs wr where wr.started_at >= ? {run_where}
            """,
            (since, *run_params),
        ).fetchone()
        total, failed = int(row["total"] or 0), int(row["failed"] or 0)
        details = {"runs": total, "failed": failed}
        if kind == "failure_count":
            return float(failed), details, []
        return (failed / total if total >= min_runs else None), details, []
    if kind == "latency_p95":
        rows = conn.execute(
            f"select wr.duration_ms from workflow_runs wr where wr.started_at >= ? and wr.duration_ms is not null {run_where}",
            (since, *run_params),
        ).fetchall()
        durations = sorted(float(row["duration_ms"]) for row in rows)
        if len(durations) < min_runs:
            return None, {"runs": len(durations)}, []
        index = min(len(durations) - 1, int(round((len(durations) - 1) * 0.95)))
        return durations[index], {"runs": len(durations)}, []
    scope = f"and cr.trace_id in (select wr.trace_id from workflow_runs wr where 1 = 1 {run_where})" if run_where else ""
    if kind == "cost":
        row = conn.execute(
            f"select coalesce(sum(cr.estimated_cost), 0) as cost, count(distinct cr.trace_id) as traces from cost_records cr where cr.timestamp >= ? {scope}",
            (since, *run_params),
        ).fetchone()
        return float(row["cost"] or 0), {"traces": int(row["traces"] or 0)}, []
    if kind == "trace_cost":
        rows = conn.execute(
            f"""
            select wr.trace_id, wr.workflow_name, coalesce(sum(cr.estimated_cost), 0) as cost
            from workflow_runs wr join cost_records cr on cr.trace_id = wr.trace_id
            where wr.started_at >= ? {run_where}
            group by wr.trace_id, wr.workflow_name
            having coalesce(sum(cr.estimated_cost), 0) >= ?
            order by cost desc
            limit 50
            """,
            (since, *run_params, float(rule["threshold"])),
        ).fetchall()
        offenders = [{"trace_id": row["trace_id"], "workflow_name": row["workflow_name"], "cost": float(row["cost"])} for row in rows]
        return (max((item["cost"] for item in offenders), default=0.0)), {}, offenders
    if kind == "loop_detected":
        scope = f"and tc.trace_id in (select wr.trace_id from workflow_runs wr where 1 = 1 {run_where})" if run_where else ""
        rows = conn.execute(
            f"""
            select tc.trace_id, tc.tool_name, count(*) as repeats
            from tool_calls tc
            where tc.started_at >= ? and tc.input_json is not null {scope}
            group by tc.trace_id, tc.tool_name, tc.input_json
            having count(*) >= ?
            order by repeats desc
            limit 50
            """,
            (since, *run_params, int(float(rule["threshold"]))),
        ).fetchall()
        offenders: list[JsonObject] = []
        for row in rows:
            if all(item["trace_id"] != row["trace_id"] for item in offenders):
                offenders.append({"trace_id": row["trace_id"], "tool_name": row["tool_name"], "repeats": int(row["repeats"])})
        return float(max((item["repeats"] for item in offenders), default=0)), {}, offenders
    raise ValueError(f"unknown alert kind: {kind}")


def _offender_key(item: JsonObject) -> str:
    """What makes an offender the same one next time: a destination, a swarm, or a trace.

    Kept short, because every key a rule has seen is stored on the rule: a long target is replaced
    by a prefix and a digest rather than truncated, so two long paths cannot collide.
    """
    key = str(item.get("key") or item["trace_id"])
    if len(key) <= MAX_KEY_CHARS:
        return key
    return f"{key[: MAX_KEY_CHARS - 17]}#{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _new_destinations(conn: Any, rule: JsonObject, since: str) -> tuple[float | None, JsonObject, list[JsonObject]]:
    """Hosts and resources reached in the window that this AgentMesh had never recorded before."""
    filters = rule["filters"]
    clauses: list[str] = []
    params: list[Any] = []
    for key, column in (("access_kind", "kind"), ("service", "service")):
        if filters.get(key):
            clauses.append(f"and ra.{column} = ?")
            params.append(str(filters[key]))
    if filters.get("swarm"):
        swarm_ids = [swarm["swarm_id"] for swarm in _active_swarms(conn, rule, since)]
        if not swarm_ids:
            return 0.0, {"destinations": 0}, []
        marks = ", ".join("?" for _ in swarm_ids)
        clauses.append(f"and ra.trace_id in (select st.trace_id from swarm_traces st where st.swarm_id in ({marks}))")
        params.extend(swarm_ids)
    # The busiest 500 destinations in the window: more distinct destinations than that is a traffic
    # pattern, not an anomaly, and the rest surface on later checks as they keep being reached.
    rows = conn.execute(
        f"""
        select ra.kind, ra.target, count(*) as accesses, count(distinct ra.agent) as agents,
          min(ra.trace_id) as trace_id, min(ra.created_at) as first_seen
        from resource_access ra where ra.created_at >= ? {' '.join(clauses)}
        group by ra.kind, ra.target
        order by accesses desc
        limit 500
        """,
        (since, *params),
    ).fetchall()
    candidates = [dict(row) for row in rows if int(row["accesses"] or 0) >= int(float(rule["threshold"]))]
    if not candidates:
        return 0.0, {"destinations": 0}, []
    # "New" means never seen before anywhere, not just inside this rule's scope.
    earlier: set[tuple[str, str]] = set()
    targets = [str(item["target"]) for item in candidates]
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
    new_targets = [
        {
            "key": f"{item['kind']}:{item['target']}",
            "kind": item["kind"],
            "target": item["target"],
            "accesses": int(item["accesses"] or 0),
            "agents": int(item["agents"] or 0),
            "trace_id": item["trace_id"],  # one of the traces that reached it, for the link
            "first_seen": item["first_seen"],
        }
        for item in candidates
        if (item["kind"], item["target"]) not in earlier
    ]
    return float(len(new_targets)), {"destinations": len(new_targets)}, new_targets[:MAX_ITEMS_PER_ALERT]


def _swarm_anomalies(conn: Any, rule: JsonObject, since: str, now: datetime) -> tuple[float | None, JsonObject, list[JsonObject]]:
    """Swarms active in the window whose totals have crossed the threshold."""
    kind = str(rule["kind"])
    swarms = _active_swarms(conn, rule, since)
    if not swarms:
        return 0.0, {"swarms": 0}, []
    ids = [str(swarm["swarm_id"]) for swarm in swarms]
    if kind == "swarm_loop":
        measured = _message_loops(conn, ids, since)
    elif kind == "swarm_errors":
        measured = _failed_traces(conn, ids)
    else:
        column = {"swarm_agents": "agents", "swarm_spawn_rate": "spawn_rate_per_minute", "swarm_cost": "cost_usd"}[kind]
        measured = {
            swarm_id: (float(entry.get(column) or 0), {})
            for swarm_id, entry in swarm_usage(conn, ids, now).items()
        }
    threshold = float(rule["threshold"])
    offenders: list[JsonObject] = []
    for swarm in swarms:
        value, extra = measured.get(str(swarm["swarm_id"]), (0.0, {}))
        if value <= 0 or value < threshold:
            continue
        offenders.append({
            "key": f"{kind}:{swarm['swarm_id']}",
            "swarm_id": swarm["swarm_id"],
            "swarm_name": swarm.get("name") or swarm["swarm_id"],
            "value": value,
            **extra,
        })
    offenders.sort(key=lambda item: -float(item["value"]))
    # The reported value is the highest across every swarm looked at, so a rule that is not firing
    # still shows how close the busiest swarm came.
    highest = max((measured_value for measured_value, _ in measured.values()), default=0.0)
    return float(highest), {"swarms": len(swarms)}, offenders[:MAX_ITEMS_PER_ALERT]


def _active_swarms(conn: Any, rule: JsonObject, since: str) -> list[JsonObject]:
    """Swarms with activity in the window, most recent first, narrowed by the rule's filters."""
    filters = rule["filters"]
    clauses: list[str] = []
    params: list[Any] = []
    for key, column in (("service", "service_name"), ("environment", "environment")):
        if filters.get(key):
            clauses.append(f"and {column} = ?")
            params.append(str(filters[key]))
    rows = conn.execute(
        f"select swarm_id, name, service_name, environment from swarms where last_seen_at >= ? {' '.join(clauses)} order by last_seen_at desc limit ?",
        (since, *params, MAX_SWARMS),
    ).fetchall()
    swarms = [dict(row) for row in rows]
    pattern = filters.get("swarm")
    if pattern:
        patterns = [str(pattern)]
        swarms = [swarm for swarm in swarms if glob_match(str(swarm["swarm_id"]), patterns) or glob_match(str(swarm["name"] or ""), patterns)]
    return swarms


def _message_loops(conn: Any, swarm_ids: list[str], since: str) -> dict[str, tuple[float, JsonObject]]:
    """The busiest pair of agents in each swarm that sent work *both* ways: delegation going in circles."""
    worst: dict[str, tuple[float, JsonObject]] = {}
    for start in range(0, len(swarm_ids), CHUNK):
        chunk = swarm_ids[start : start + CHUNK]
        marks = ", ".join("?" for _ in chunk)
        pairs: dict[tuple[str, str, str], JsonObject] = {}
        for row in conn.execute(
            f"""
            select st.swarm_id, m.from_agent, m.to_agent, count(*) as messages
            from agent_messages_log m join swarm_traces st on st.trace_id = m.trace_id
            where m.created_at >= ? and m.from_agent is not null and m.to_agent is not null
              and st.swarm_id in ({marks})
            group by st.swarm_id, m.from_agent, m.to_agent
            """,
            (since, *chunk),
        ).fetchall():
            sender, receiver = str(row["from_agent"]), str(row["to_agent"])
            if sender == receiver:
                continue
            first, second = sorted((sender, receiver))
            entry = pairs.setdefault((str(row["swarm_id"]), first, second), {"messages": 0, "directions": 0})
            entry["messages"] += int(row["messages"] or 0)
            entry["directions"] += 1
        for (swarm_id, first, second), entry in pairs.items():
            if entry["directions"] < 2:  # one-way fan-out is delegation, not a loop
                continue
            messages = float(entry["messages"])
            if messages > worst.get(swarm_id, (0.0, {}))[0]:
                worst[swarm_id] = (messages, {"between": [first, second], "messages": int(messages)})
    return worst


def _failed_traces(conn: Any, swarm_ids: list[str]) -> dict[str, tuple[float, JsonObject]]:
    """Failed traces per swarm, over the whole swarm rather than just the window."""
    counts: dict[str, tuple[float, JsonObject]] = {}
    for start in range(0, len(swarm_ids), CHUNK):
        chunk = swarm_ids[start : start + CHUNK]
        marks = ", ".join("?" for _ in chunk)
        for row in conn.execute(
            f"""
            select st.swarm_id, sum(case when wr.status = 'failed' then 1 else 0 end) as failed, count(*) as runs
            from swarm_traces st join workflow_runs wr on wr.trace_id = st.trace_id
            where st.swarm_id in ({marks})
            group by st.swarm_id
            """,
            chunk,
        ).fetchall():
            counts[str(row["swarm_id"])] = (float(row["failed"] or 0), {"failed": int(row["failed"] or 0), "runs": int(row["runs"] or 0)})
    return counts


def _run_filters(filters: JsonObject) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for key, column in (("workflow", "workflow_name"), ("environment", "environment"), ("service", "service_name"), ("source", "source")):
        if filters.get(key):
            clauses.append(f"and wr.{column} = ?")
            params.append(str(filters[key]))
    return " ".join(clauses), params


def _message(rule: JsonObject, value: float | None, details: JsonObject, resolved: bool = False) -> str:
    kind = rule["kind"]
    threshold = float(rule["threshold"])
    window = _window_text(int(rule["window_minutes"]))
    scope = ", ".join(f"{key}={value}" for key, value in rule["filters"].items() if key != "min_runs")
    suffix = f" [{scope}]" if scope else ""
    if kind == "failure_rate":
        text = f"Failure rate {value or 0:.0%} ({details.get('failed', 0)} of {details.get('runs', 0)} runs) in the last {window}; threshold {threshold:.0%}"
    elif kind == "failure_count":
        text = f"{int(value or 0)} failed runs in the last {window}; threshold {int(threshold)}"
    elif kind == "cost":
        text = f"Spent ${value or 0:.4f} across {details.get('traces', 0)} traces in the last {window}; threshold ${threshold:.4f}"
    elif kind == "latency_p95":
        text = f"p95 run latency {value or 0:.0f} ms over {details.get('runs', 0)} runs in the last {window}; threshold {threshold:.0f} ms"
    elif kind == "trace_cost":
        traces = details.get("traces") or []
        text = f"{len(traces)} trace(s) cost at least ${threshold:.4f}; most expensive ${value or 0:.4f}"
    elif kind == "new_destination":
        items = details.get("items") or []
        names = ", ".join(str(item.get("target")) for item in items[:3]) + ("..." if len(items) > 3 else "")
        text = f"{len(items)} destination(s) reached for the first time in the last {window}: {names}"
    elif kind in SWARM_KINDS:
        items = details.get("items") or []
        worst = items[0] if items else {}
        name = worst.get("swarm_name", "a swarm")
        reported = float(worst.get("value", value or 0))  # the swarm this alert is about, not the busiest one seen
        if kind == "swarm_agents":
            text = f"Swarm {name} has started {int(reported)} agents; threshold {int(threshold)}"
        elif kind == "swarm_spawn_rate":
            text = f"Swarm {name} is starting {int(reported)} agents per minute; threshold {int(threshold)}"
        elif kind == "swarm_cost":
            text = f"Swarm {name} has spent ${reported:.4f}; threshold ${threshold:.4f}"
        elif kind == "swarm_errors":
            text = f"Swarm {name} has {int(reported)} failed traces out of {worst.get('runs', 0)}; threshold {int(threshold)}"
        else:
            pair = " and ".join(str(agent) for agent in worst.get("between") or []) or "two agents"
            text = f"Swarm {name}: {pair} exchanged {int(reported)} messages back and forth; threshold {int(threshold)}"
        if len(items) > 1:
            text += f" (and {len(items) - 1} more swarm(s))"
    else:
        traces = details.get("traces") or []
        worst = traces[0] if traces else {}
        text = f"Tool loop in {len(traces)} trace(s): {worst.get('tool_name', 'a tool')} called {int(value or 0)}x with the same arguments"
    return ("Resolved: " if resolved else "") + text + suffix


def _window_text(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _record_event(
    conn: Any, rule: JsonObject, status: str, value: float | None, message: str, details: JsonObject, now: datetime
) -> JsonObject:
    alert_id = new_id("alertev")
    created_at = now.isoformat()
    conn.execute(
        """
        insert into alert_events
        (alert_id, rule_id, rule_name, kind, status, value, threshold, message, details_json, delivered, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (alert_id, rule["rule_id"], rule["name"], rule["kind"], status, value, rule["threshold"], message, dumps_json(details), created_at),
    )
    return {
        "alert_id": alert_id,
        "rule_id": rule["rule_id"],
        "rule_name": rule["name"],
        "kind": rule["kind"],
        "status": status,
        "value": value,
        "threshold": rule["threshold"],
        "message": message,
        "details": details,
        "created_at": created_at,
    }


def _validated(payload: JsonObject, partial: bool) -> JsonObject:
    kind = str(payload.get("kind") or "")
    if kind not in ALERT_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(ALERT_KINDS)}")
    try:
        threshold = float(payload.get("threshold"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError("threshold must be a number") from None
    if threshold < 0 or (kind == "failure_rate" and threshold > 1):
        raise ValueError("failure_rate thresholds are a fraction between 0 and 1" if kind == "failure_rate" else "threshold must be >= 0")
    if kind == "loop_detected" and threshold < 2:
        raise ValueError("loop_detected thresholds count repeated calls and must be at least 2")
    if kind == "swarm_loop" and threshold < 2:
        raise ValueError("swarm_loop thresholds count messages between two agents and must be at least 2")
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    unknown = set(filters) - FILTER_KEYS
    if unknown:
        raise ValueError(f"unknown filter(s): {', '.join(sorted(unknown))}; allowed: {', '.join(sorted(FILTER_KEYS))}")
    filters = {key: value for key, value in filters.items() if value not in (None, "")}
    swarm_scoped = kind in SWARM_KINDS or kind == "new_destination"
    misplaced = (set(filters) & RUN_FILTER_KEYS) if swarm_scoped else (set(filters) & {"swarm", "access_kind"})
    if misplaced:
        allowed = "service, environment, swarm" if swarm_scoped else ", ".join(sorted(FILTER_KEYS - {"swarm", "access_kind"}))
        raise ValueError(f"{kind} rules cannot filter by {', '.join(sorted(misplaced))}; allowed: {allowed}")
    if kind != "new_destination" and "access_kind" in filters:
        raise ValueError("access_kind only applies to new_destination rules")
    if filters.get("access_kind") and str(filters["access_kind"]) not in ACCESS_KINDS:
        raise ValueError(f"access_kind must be one of: {', '.join(ACCESS_KINDS)}")
    channel = dict(payload.get("channel")) if isinstance(payload.get("channel"), dict) else {}
    url = str(channel.get("url") or "").strip()
    if url:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("webhook url must be an http(s) URL")
    fmt = str(channel.get("format") or _guess_format(url))
    if fmt not in WEBHOOK_FORMATS:
        raise ValueError(f"webhook format must be one of: {', '.join(sorted(WEBHOOK_FORMATS))}")
    cleaned_channel: JsonObject = {"type": "webhook" if url else "none", "url": url or None, "format": fmt}
    if channel.get("secret"):
        cleaned_channel["secret"] = str(channel["secret"])
    if channel.get("notify_resolved") is not None:
        cleaned_channel["notify_resolved"] = bool(channel["notify_resolved"])
    return {
        "kind": kind,
        "threshold": threshold,
        "window_minutes": parse_minutes(payload.get("window_minutes", payload.get("window")), 15),
        "cooldown_minutes": parse_minutes(payload.get("cooldown_minutes", payload.get("cooldown")), 30),
        "filters": filters,
        "channel": cleaned_channel,
        "enabled": bool(payload.get("enabled", True)),
    }


def _guess_format(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if host.endswith("hooks.slack.com"):
        return "slack"
    if host.endswith("discord.com") or host.endswith("discordapp.com"):
        return "discord"
    return "json"


def _rule_row(conn: Any, ref: str) -> Any:
    return conn.execute("select * from alert_rules where rule_id = ? or name = ?", (ref, ref)).fetchone()


def _rule_to_json(row: Any, reveal: bool = False) -> JsonObject:
    channel = loads_json(row["channel_json"]) or {}
    if not reveal:
        channel = {**channel, "url": _mask_url(channel.get("url")), "secret": "***" if channel.get("secret") else None}
    return {
        "rule_id": row["rule_id"],
        "name": row["name"],
        "kind": row["kind"],
        "description": ALERT_KINDS.get(str(row["kind"])),
        "threshold": float(row["threshold"]),
        "window_minutes": int(row["window_minutes"]),
        "cooldown_minutes": int(row["cooldown_minutes"]),
        "filters": loads_json(row["filters_json"]) or {},
        "channel": channel,
        "enabled": bool(row["enabled"]),
        "state": row["state"],
        "last_value": row["last_value"],
        "last_evaluated_at": row["last_evaluated_at"],
        "last_triggered_at": row["last_triggered_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _public_rule(rule: JsonObject) -> JsonObject:
    return {key: rule[key] for key in ("rule_id", "name", "kind", "threshold", "window_minutes", "filters")}


def _event_to_json(row: Any) -> JsonObject:
    return {
        "alert_id": row["alert_id"],
        "rule_id": row["rule_id"],
        "rule_name": row["rule_name"],
        "kind": row["kind"],
        "status": row["status"],
        "value": row["value"],
        "threshold": row["threshold"],
        "message": row["message"],
        "details": loads_json(row["details_json"]) or {},
        "delivered": bool(row["delivered"]),
        "delivery_error": row["delivery_error"],
        "created_at": row["created_at"],
    }


def _mask_url(url: Any) -> str | None:
    if not url:
        return None
    parsed = urllib.parse.urlparse(str(url))
    tail = parsed.path[-4:] if len(parsed.path) > 8 else ""
    host = parsed.hostname or ""  # never echo user:password@ from the URL
    if ":" in host:
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}/***{tail}"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
