"""Policies: rules and limits that allow, deny, or pause what agents do.

A policy is a YAML or JSON document::

    name: production-guardrails
    mode: enforce            # or "monitor": record what would be blocked, block nothing
    limits:                  # per trace
      max_cost_usd: 5
      max_tool_calls: 100
      max_repeated_calls: 3  # the same tool with the same arguments; stops loops
      max_agent_depth: 4     # agents calling agents calling agents
      max_child_agents: 10   # agents one agent may start
    rules:                   # first matching rule wins
      - name: no-production-deletes
        match: {tool: ["delete_*", "drop_*"], arguments: {environment: production}}
        action: deny
        reason: Deleting production data needs a person.
      - name: refunds-need-approval
        match: {tool: issue_refund}
        action: require_approval
      - name: approved-models-only
        match: {kind: llm}
        except: {model: ["gpt-4.1*", "claude-*"]}
        action: deny
    approval:
      timeout_seconds: 300   # unanswered approvals are denied

This module only decides. :mod:`agentmesh.guardrails` applies decisions to running agents
(SDK spans, OpenAI/Anthropic calls, the AgentMesh runtime), and :func:`simulate` replays
recorded traces through a policy to show what it would have blocked.
"""

from __future__ import annotations

import fnmatch
import json
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agentmesh.types import JsonObject

ACTIONS = ("allow", "warn", "require_approval", "deny")
MODES = ("enforce", "monitor")
KINDS = ("tool", "llm", "agent", "any")
MATCH_KEYS = ("kind", "name", "tool", "model", "provider", "agent", "service", "environment", "host", "arguments", "input_regex")
LIMITS: dict[str, str] = {
    "max_steps": "Tool, LLM, and agent calls in one trace",
    "max_llm_calls": "LLM calls in one trace",
    "max_tool_calls": "Tool calls in one trace",
    "max_calls_per_tool": "Calls to any single tool in one trace",
    "max_repeated_calls": "Calls to the same tool with the same arguments in one trace (loop breaker)",
    "max_cost_usd": "Spend in one trace, in USD",
    "max_tokens": "Tokens used in one trace",
    "max_duration_seconds": "Time since the trace started, in seconds",
    "max_agent_depth": "Agents nested inside agents",
    "max_child_agents": "Agents started directly by one agent",
}
# Limits for a whole swarm, counted across every process and trace in it. Unlike per-trace limits
# they cannot be checked inside one agent, so the server evaluates them from the spans it has and
# halts the swarm when one is broken. See agentmesh.swarm_limits.
SWARM_LIMITS: dict[str, str] = {
    "max_agents": "Agents started in one swarm",
    "max_concurrent_agents": "Agents running at the same time",
    "max_spawn_rate_per_minute": "Agents started per minute",
    "max_cost_usd": "Spend across the swarm, in USD",
    "max_tokens": "Tokens used across the swarm",
    "max_duration_minutes": "Time since the swarm started, in minutes",
}
SWARM_MATCH_KEYS = ("name", "service", "environment")
# Severity when several decisions apply to one call: the strictest wins.
SEVERITY = {"allow": 0, "warn": 1, "require_approval": 2, "deny": 3}
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300.0
MAX_INPUT_CHARS = 20_000


class PolicyError(ValueError):
    """A policy document is invalid. ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    action: str
    match: JsonObject
    exclude: JsonObject
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Policy:
    name: str
    mode: str = "enforce"
    rules: tuple[Rule, ...] = ()
    limits: dict[str, float] = field(default_factory=dict)
    swarm_limits: dict[str, float] = field(default_factory=dict)
    swarm_match: JsonObject = field(default_factory=dict)
    approval_timeout_seconds: float = DEFAULT_APPROVAL_TIMEOUT_SECONDS
    description: str | None = None
    policy_id: str | None = None

    @classmethod
    def from_spec(cls, spec: JsonObject | str, policy_id: str | None = None) -> Policy:
        """Build a policy from a dict or from YAML/JSON text, raising :class:`PolicyError` if invalid."""
        document = parse_spec(spec) if isinstance(spec, str) else spec
        errors: list[str] = []
        if not isinstance(document, dict):
            raise PolicyError(["policy must be a mapping"])
        unknown = set(document) - {"name", "description", "mode", "rules", "limits", "swarm", "approval", "enabled"}
        if unknown:
            errors.append(f"unknown top-level keys: {', '.join(sorted(unknown))}")
        name = document.get("name")
        if isinstance(name, (bool, int, float)):
            errors.append("name must be text; quote it (YAML reads values like off, no, and 1 as booleans or numbers)")
        elif not isinstance(name, str) or not name.strip():
            errors.append("name is required")
        elif "/" in name:
            errors.append("name cannot contain '/'")
        mode = document.get("mode", "enforce")
        if mode not in MODES:
            errors.append(f"mode must be one of {', '.join(MODES)}")
        limits = _parse_limits(document.get("limits") or {}, errors)
        swarm_limits, swarm_match = _parse_swarm(document.get("swarm") or {}, errors)
        rules = _parse_rules(document.get("rules") or [], errors)
        approval = document.get("approval") or {}
        timeout = DEFAULT_APPROVAL_TIMEOUT_SECONDS
        if not isinstance(approval, dict):
            errors.append("approval must be a mapping")
        elif "timeout_seconds" in approval:
            timeout_value = approval["timeout_seconds"]
            if not _is_number(timeout_value) or timeout_value <= 0:
                errors.append("approval.timeout_seconds must be a positive number")
            else:
                timeout = float(timeout_value)
        if not rules and not limits and not swarm_limits:
            errors.append("a policy needs at least one rule or limit")
        if errors:
            raise PolicyError(errors)
        return cls(
            name=str(name).strip(),
            mode=str(mode),
            rules=tuple(rules),
            limits=limits,
            swarm_limits=swarm_limits,
            swarm_match=swarm_match,
            approval_timeout_seconds=timeout,
            description=document.get("description"),
            policy_id=policy_id,
        )

    def to_spec(self) -> JsonObject:
        spec: JsonObject = {"name": self.name, "mode": self.mode}
        if self.description:
            spec["description"] = self.description
        if self.limits:
            spec["limits"] = {key: int(value) if value.is_integer() else value for key, value in self.limits.items()}
        if self.swarm_limits or self.swarm_match:
            spec["swarm"] = {
                **{key: int(value) if value.is_integer() else value for key, value in self.swarm_limits.items()},
                **({"match": self.swarm_match} if self.swarm_match else {}),
            }
        if self.rules:
            spec["rules"] = [
                {
                    "name": rule.name,
                    "match": rule.match,
                    **({"except": rule.exclude} if rule.exclude else {}),
                    "action": rule.action,
                    **({"reason": rule.reason} if rule.reason else {}),
                }
                for rule in self.rules
            ]
        if self.approval_timeout_seconds != DEFAULT_APPROVAL_TIMEOUT_SECONDS:
            spec["approval"] = {"timeout_seconds": self.approval_timeout_seconds}
        return spec


def parse_spec(text: str) -> Any:
    """Parse policy text as JSON, or as YAML when PyYAML is available."""
    stripped = text.strip()
    if not stripped:
        raise PolicyError(["policy is empty"])
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise PolicyError([f"invalid JSON: {exc}"]) from exc
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - PyYAML is a dependency
        raise PolicyError(["YAML policies need PyYAML: pip install pyyaml (or write the policy as JSON)"]) from exc
    try:
        return yaml.safe_load(stripped)
    except yaml.YAMLError as exc:
        raise PolicyError([f"invalid YAML: {exc}"]) from exc


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_limits(raw: Any, errors: list[str]) -> dict[str, float]:
    if not isinstance(raw, dict):
        errors.append("limits must be a mapping")
        return {}
    limits: dict[str, float] = {}
    for key, value in raw.items():
        if key not in LIMITS:
            errors.append(f"unknown limit '{key}' (known: {', '.join(LIMITS)})")
        elif not _is_number(value) or value < 0:
            errors.append(f"limits.{key} must be a non-negative number")
        elif key == "max_repeated_calls" and value < 1:
            errors.append("limits.max_repeated_calls must be at least 1")
        else:
            limits[key] = float(value)
    return limits


def _parse_swarm(raw: Any, errors: list[str]) -> tuple[dict[str, float], JsonObject]:
    """Parse the ``swarm:`` block: limits for a whole swarm, plus an optional ``match``."""
    if not isinstance(raw, dict):
        errors.append("swarm must be a mapping")
        return {}, {}
    limits: dict[str, float] = {}
    match: JsonObject = {}
    for key, value in raw.items():
        if key == "match":
            if not isinstance(value, dict):
                errors.append("swarm.match must be a mapping")
                continue
            for match_key, pattern in value.items():
                if match_key not in SWARM_MATCH_KEYS:
                    errors.append(f"swarm.match: unknown key '{match_key}' (known: {', '.join(SWARM_MATCH_KEYS)})")
                elif not (isinstance(pattern, str) or (isinstance(pattern, list) and all(isinstance(item, str) for item in pattern))):
                    errors.append(f"swarm.match.{match_key} must be a pattern or a list of patterns")
                else:
                    match[match_key] = pattern
        elif key not in SWARM_LIMITS:
            errors.append(f"unknown swarm limit '{key}' (known: {', '.join(SWARM_LIMITS)}, match)")
        elif not _is_number(value) or value <= 0:
            errors.append(f"swarm.{key} must be a positive number")
        else:
            limits[key] = float(value)
    return limits, match


def _parse_rules(raw: Any, errors: list[str]) -> list[Rule]:
    if not isinstance(raw, list):
        errors.append("rules must be a list")
        return []
    rules: list[Rule] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        where = f"rules[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where} must be a mapping")
            continue
        unknown = set(item) - {"name", "match", "except", "action", "reason"}
        if unknown:
            errors.append(f"{where}: unknown keys {', '.join(sorted(unknown))}")
        name = str(item.get("name") or f"rule-{index + 1}")
        if name in seen:
            errors.append(f"{where}: duplicate rule name '{name}'")
        seen.add(name)
        action = item.get("action")
        if action not in ACTIONS:
            errors.append(f"{where} ({name}): action must be one of {', '.join(ACTIONS)}")
        match = item.get("match") or {}
        exclude = item.get("except") or {}
        _validate_match(match, f"{where}.match", errors)
        _validate_match(exclude, f"{where}.except", errors)
        rules.append(Rule(name=name, action=str(action), match=dict(match), exclude=dict(exclude), reason=item.get("reason")))
    return rules


def _validate_match(match: Any, where: str, errors: list[str]) -> None:
    if not isinstance(match, dict):
        errors.append(f"{where} must be a mapping")
        return
    for key, value in match.items():
        if key not in MATCH_KEYS:
            errors.append(f"{where}: unknown key '{key}' (known: {', '.join(MATCH_KEYS)})")
        elif key == "kind":
            kinds = value if isinstance(value, list) else [value]
            if any(kind not in KINDS for kind in kinds):
                errors.append(f"{where}.kind must be one of {', '.join(KINDS)}")
        elif key == "arguments":
            if not isinstance(value, dict) or not value:
                errors.append(f"{where}.arguments must be a non-empty mapping of argument name to value or pattern")
        elif key == "input_regex":
            try:
                re.compile(str(value))
            except re.error as exc:
                errors.append(f"{where}.input_regex is not a valid regular expression: {exc}")
        elif not (isinstance(value, str) or (isinstance(value, list) and all(isinstance(entry, str) for entry in value))):
            errors.append(f"{where}.{key} must be a pattern or a list of patterns")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ActionContext:
    """One thing an agent is about to do: call a tool, call a model, or start an agent."""

    kind: str
    name: str
    trace_id: str
    span_id: str | None = None
    parent_span_id: str | None = None
    agent: str | None = None
    model: str | None = None
    provider: str | None = None
    service: str | None = None
    environment: str | None = None
    arguments: Any = None
    swarm_id: str | None = None
    attributes: JsonObject = field(default_factory=dict)
    _hosts: list[str] | None = field(default=None, repr=False, compare=False)

    @property
    def hosts(self) -> list[str]:
        """Hosts this call would reach, read from its arguments and attributes (computed once)."""
        if self._hosts is None:
            from agentmesh.access import call_hosts

            self._hosts = call_hosts(self.arguments, self.attributes)
        return self._hosts

    @property
    def target(self) -> str:
        if self.kind == "llm":
            return self.model or self.name
        return self.name


@dataclass(slots=True)
class Decision:
    action: str
    enforced: bool
    rule: str
    reason: str
    kind: str
    target: str
    policy_name: str | None = None
    policy_id: str | None = None
    details: JsonObject = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return self.enforced and self.action == "deny"

    @property
    def needs_approval(self) -> bool:
        return self.enforced and self.action == "require_approval"

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "enforced": self.enforced,
            "rule": self.rule,
            "reason": self.reason,
            "kind": self.kind,
            "target": self.target,
            "policy_name": self.policy_name,
            "policy_id": self.policy_id,
            "details": self.details,
        }


@dataclass(slots=True)
class _SpanNode:
    agent_depth: int
    agent_span_id: str | None


class RunState:
    """What one trace has done so far, for limits. Thread-safe; one instance per trace."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.started_at = clock()
        self.steps = 0
        self.llm_calls = 0
        self.tool_calls = 0
        self.calls_per_tool: Counter[str] = Counter()
        self.repeated: Counter[str] = Counter()
        self.child_agents: Counter[str] = Counter()
        self.tokens = 0
        self.cost_usd = 0.0
        self._nodes: dict[str, _SpanNode] = {}
        self._lock = threading.Lock()

    def register_span(self, span_id: str, parent_span_id: str | None, is_agent: bool) -> None:
        """Remember a span's place among agents, so nested agents can be counted."""
        with self._lock:
            self._register(span_id, parent_span_id, is_agent)

    def _register(self, span_id: str, parent_span_id: str | None, is_agent: bool) -> _SpanNode:
        parent = self._nodes.get(parent_span_id) if parent_span_id else None
        depth = parent.agent_depth if parent else 0
        agent_span = parent.agent_span_id if parent else None
        node = _SpanNode(depth + 1, span_id) if is_agent else _SpanNode(depth, agent_span)
        self._nodes[span_id] = node
        return node

    def agent_position(self, parent_span_id: str | None) -> tuple[int, str | None]:
        """Depth a new agent under ``parent_span_id`` would have, and the agent that starts it."""
        with self._lock:
            parent = self._nodes.get(parent_span_id) if parent_span_id else None
            return ((parent.agent_depth if parent else 0) + 1, parent.agent_span_id if parent else None)

    def record(self, context: ActionContext) -> None:
        """Count an action that was allowed to run."""
        with self._lock:
            self.steps += 1
            if context.kind == "llm":
                self.llm_calls += 1
            elif context.kind == "tool":
                self.tool_calls += 1
                self.calls_per_tool[context.name] += 1
                self.repeated[_signature(context)] += 1
            if context.kind == "agent":
                parent = self._nodes.get(context.parent_span_id) if context.parent_span_id else None
                if parent is not None and parent.agent_span_id:
                    self.child_agents[parent.agent_span_id] += 1
            if context.span_id:
                self._register(context.span_id, context.parent_span_id, context.kind == "agent")

    def add_usage(self, tokens: int = 0, cost_usd: float = 0.0) -> None:
        with self._lock:
            self.tokens += max(int(tokens or 0), 0)
            self.cost_usd += max(float(cost_usd or 0.0), 0.0)

    def snapshot(self) -> JsonObject:
        with self._lock:
            return {
                "steps": self.steps,
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens": self.tokens,
                "cost_usd": round(self.cost_usd, 6),
                "duration_seconds": round(self.clock() - self.started_at, 3),
            }


def _signature(context: ActionContext) -> str:
    try:
        arguments = json.dumps(context.arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        arguments = str(context.arguments)
    return f"{context.name}\x00{arguments}"


class PolicyEngine:
    """Evaluates actions against a set of policies. Holds no per-trace state itself."""

    def __init__(self, policies: Iterable[Policy] = ()) -> None:
        self.policies = tuple(policies)

    def __bool__(self) -> bool:
        return bool(self.policies)

    def evaluate(self, context: ActionContext, state: RunState) -> list[Decision]:
        """Every non-allow decision for this action, strictest first. Does not change ``state``."""
        decisions: list[Decision] = []
        for policy in self.policies:
            enforced = policy.mode == "enforce"
            rule_decision = self._match_rules(policy, context, enforced)
            if rule_decision is not None and rule_decision.action == "allow":
                continue  # an explicit allow exempts this action from the policy's limits too
            if rule_decision is not None:
                decisions.append(rule_decision)
            decisions.extend(self._check_limits(policy, context, state, enforced))
        decisions.sort(key=lambda decision: (not decision.enforced, -SEVERITY[decision.action]))
        return decisions

    @staticmethod
    def verdict(decisions: list[Decision]) -> Decision | None:
        """The decision that governs the action: the strictest enforced one, if any."""
        enforced = [decision for decision in decisions if decision.enforced and decision.action != "warn"]
        return max(enforced, key=lambda decision: SEVERITY[decision.action]) if enforced else None

    def _match_rules(self, policy: Policy, context: ActionContext, enforced: bool) -> Decision | None:
        for rule in policy.rules:
            if matches(rule.match, context) and not (rule.exclude and matches(rule.exclude, context)):
                return Decision(
                    action=rule.action,
                    enforced=enforced,
                    rule=rule.name,
                    reason=rule.reason or _default_reason(rule, context),
                    kind=context.kind,
                    target=context.target,
                    policy_name=policy.name,
                    policy_id=policy.policy_id,
                )
        return None

    def _check_limits(self, policy: Policy, context: ActionContext, state: RunState, enforced: bool) -> list[Decision]:
        """Every limit this action would break. All are reported, so a loop is not hidden behind a spend limit."""
        limits = policy.limits
        if not limits or context.kind not in {"tool", "llm", "agent"}:
            return []

        def breach(limit: str, used: float, reason: str) -> Decision:
            return Decision(
                action="deny",
                enforced=enforced,
                rule=f"limit:{limit}",
                reason=reason,
                kind=context.kind,
                target=context.target,
                policy_name=policy.name,
                policy_id=policy.policy_id,
                details={"limit": limit, "max": limits[limit], "used": used},
            )

        checks: list[tuple[str, float, str]] = []
        if "max_cost_usd" in limits:
            checks.append(("max_cost_usd", state.cost_usd, f"Trace spend ${state.cost_usd:.4f} reached the ${limits['max_cost_usd']:.2f} limit"))
        if "max_tokens" in limits:
            checks.append(("max_tokens", state.tokens, f"Trace used {state.tokens:,} tokens, reaching the {int(limits['max_tokens']):,} limit"))
        if "max_duration_seconds" in limits:
            elapsed = state.clock() - state.started_at
            checks.append(("max_duration_seconds", elapsed, f"Trace has run {elapsed:.0f}s, past the {limits['max_duration_seconds']:.0f}s limit"))
        breaches: list[Decision] = []
        for limit, used, reason in checks:
            # Spend and tokens are only known after a call finishes, so the call that crosses the
            # limit completes; every later call is stopped.
            crossed = used > limits[limit] if limit == "max_duration_seconds" else used >= limits[limit]
            if crossed:
                breaches.append(breach(limit, used, reason))

        counted: list[tuple[str, float]] = [("max_steps", state.steps + 1)]
        if context.kind == "llm":
            counted.append(("max_llm_calls", state.llm_calls + 1))
        if context.kind == "tool":
            counted.append(("max_tool_calls", state.tool_calls + 1))
            counted.append(("max_calls_per_tool", state.calls_per_tool[context.name] + 1))
            counted.append(("max_repeated_calls", state.repeated[_signature(context)] + 1))
        if context.kind == "agent":
            depth, starting_agent = state.agent_position(context.parent_span_id)
            counted.append(("max_agent_depth", depth))
            if starting_agent is not None:
                counted.append(("max_child_agents", state.child_agents[starting_agent] + 1))
        messages = {
            "max_steps": "Trace reached its limit of {max} steps",
            "max_llm_calls": "Trace reached its limit of {max} LLM calls",
            "max_tool_calls": "Trace reached its limit of {max} tool calls",
            "max_calls_per_tool": "Tool '{name}' reached its limit of {max} calls in this trace",
            "max_repeated_calls": "Tool '{name}' was already called {max} times with the same arguments; stopping a likely loop",
            "max_agent_depth": "Starting agent '{name}' would nest agents {used} deep, past the limit of {max}",
            "max_child_agents": "The calling agent already started {max} agents, its limit",
        }
        for limit, would_be in counted:
            if limit in limits and would_be > limits[limit]:
                breaches.append(breach(limit, would_be, messages[limit].format(max=int(limits[limit]), name=context.name, used=int(would_be))))
        return breaches


def _default_reason(rule: Rule, context: ActionContext) -> str:
    verb = {"deny": "blocked", "require_approval": "needs approval", "warn": "flagged", "allow": "allowed"}[rule.action]
    return f"{context.kind} '{context.target}' {verb} by rule '{rule.name}'"


def matches(match: JsonObject, context: ActionContext) -> bool:
    """True when every condition in ``match`` holds for ``context``. An empty match matches everything."""
    for key, expected in match.items():
        if key == "kind":
            kinds = expected if isinstance(expected, list) else [expected]
            if "any" not in kinds and context.kind not in kinds:
                return False
        elif key == "tool":
            if context.kind != "tool" or not _glob_name(context.name, expected):
                return False
        elif key == "model":
            if context.kind != "llm" or not _glob(context.model, expected):
                return False
        elif key == "name":
            if not _glob_name(context.name, expected):
                return False
        elif key == "agent":
            if not _glob_name(context.agent, expected):
                return False
        elif key in {"provider", "service", "environment"}:
            if not _glob(getattr(context, key), expected):
                return False
        elif key == "host":
            if not any(_glob(host, expected) for host in context.hosts):
                return False
        elif key == "arguments":
            if not _arguments_match(context.arguments, expected):
                return False
        elif key == "input_regex":
            if not re.search(str(expected), _text(context.arguments), flags=re.IGNORECASE):
                return False
    return True


def glob_match(value: str | None, patterns: Any) -> bool:
    """Case-insensitive ``*`` matching against one pattern or a list of them."""
    return _glob(value, patterns)


def _glob(value: str | None, patterns: Any) -> bool:
    if value is None:
        return False
    candidates = patterns if isinstance(patterns, list) else [patterns]
    lowered = value.lower()
    return any(fnmatch.fnmatchcase(lowered, str(pattern).lower()) for pattern in candidates)


def short_name(value: str) -> str:
    """``delete_user`` for a Python qualified name such as ``Tools.delete_user`` or ``main.<locals>.delete_user``."""
    parts = value.split(".")
    if len(parts) > 1 and all(part.isidentifier() or part == "<locals>" for part in parts):
        return parts[-1]
    return value


def _glob_name(value: str | None, patterns: Any) -> bool:
    """Match a function-derived name by its full name or by its bare name."""
    if value is None:
        return False
    short = short_name(value)
    return _glob(value, patterns) or (short != value and _glob(short, patterns))


def _arguments_match(arguments: Any, expected: JsonObject) -> bool:
    if not isinstance(arguments, dict):
        return False
    for path, pattern in expected.items():
        found, value = _lookup(arguments, str(path))
        if not found:
            return False
        patterns = pattern if isinstance(pattern, list) else [pattern]
        if not any(_value_matches(value, candidate) for candidate in patterns):
            return False
    return True


def _lookup(data: Any, path: str) -> tuple[bool, Any]:
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _value_matches(value: Any, pattern: Any) -> bool:
    if isinstance(pattern, str) and isinstance(value, str):
        return fnmatch.fnmatchcase(value.lower(), pattern.lower())
    if isinstance(pattern, str):
        return fnmatch.fnmatchcase(json.dumps(value, default=str).lower(), pattern.lower())
    return value == pattern


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value[:MAX_INPUT_CHARS]
    try:
        return json.dumps(value, default=str, ensure_ascii=False)[:MAX_INPUT_CHARS]
    except (TypeError, ValueError):
        return str(value)[:MAX_INPUT_CHARS]


# ---------------------------------------------------------------------------
# Simulation against recorded traces
# ---------------------------------------------------------------------------


def span_action(span: JsonObject, trace_id: str) -> ActionContext | None:
    """Rebuild the action a recorded span represents, or ``None`` for bookkeeping spans."""
    event_type = str(span.get("event_type") or "")
    span_kind = str(span.get("span_kind") or "").lower()
    name = str(span.get("name") or "")
    model = span.get("model")
    tool = span.get("tool_name")
    if event_type == "model.call" or event_type.endswith((".finished", ".succeeded", ".failed", ".saved", ".resolved")):
        return None  # the runtime records a call and its outcome as separate events; count the call once
    if tool or event_type.startswith("tool."):
        kind, target = "tool", str(tool or name or event_type)
    elif model or event_type.startswith("model.") or span_kind in {"llm", "generation"}:
        kind, target = "llm", str(name or model or event_type)
    elif event_type.startswith("agent.") or span_kind == "agent":
        kind, target = "agent", str(span.get("agent_name") or name or event_type)
    else:
        return None
    return ActionContext(
        kind=kind,
        name=target,
        trace_id=trace_id,
        span_id=span.get("span_id"),
        parent_span_id=span.get("parent_span_id"),
        agent=span.get("agent_name"),
        model=model,
        provider=span.get("provider"),
        arguments=span.get("input"),
    )


def simulate(policies: Iterable[Policy], traces: Iterable[tuple[JsonObject, list[JsonObject]]]) -> JsonObject:
    """Replay recorded traces through ``policies`` as if they were enforced.

    ``traces`` yields ``(trace_summary, spans)``. Blocked calls do not stop the replay (the
    recording continues past them), so the report counts every call a policy would have stopped.
    """
    enforced_policies = [
        Policy(policy.name, "enforce", policy.rules, policy.limits, policy.approval_timeout_seconds, policy.description, policy.policy_id)
        for policy in policies
    ]
    engine = PolicyEngine(enforced_policies)
    by_rule: dict[str, dict[str, Any]] = {}
    affected: list[JsonObject] = []
    evaluated = 0
    actions = 0
    for trace, spans in traces:
        evaluated += 1
        ordered = sorted(spans, key=lambda item: str(item.get("started_at") or ""))
        trace_id = str(trace.get("trace_id"))
        clock_value = [_timestamp(ordered[0].get("started_at")) if ordered else 0.0]
        state = RunState(clock=lambda current=clock_value: current[0])
        first: JsonObject | None = None
        counts: Counter[str] = Counter()
        for span in ordered:
            clock_value[0] = _timestamp(span.get("started_at")) or clock_value[0]
            context = span_action(span, trace_id)
            if context is None:
                if span.get("span_id"):
                    state.register_span(str(span["span_id"]), span.get("parent_span_id"), False)
                continue
            actions += 1
            decisions = engine.evaluate(context, state)
            verdict = PolicyEngine.verdict(decisions)
            for decision in decisions:
                key = f"{decision.policy_name}::{decision.rule}"
                entry = by_rule.setdefault(key, {"policy": decision.policy_name, "rule": decision.rule, "action": decision.action, "calls": 0, "traces": set()})
                entry["calls"] += 1
                entry["traces"].add(trace_id)
            if verdict is not None:
                counts[verdict.action] += 1
                if first is None:
                    first = {"span_id": context.span_id, **verdict.to_json()}
            state.record(context)
            usage_tokens = int(span.get("total_tokens") or 0)
            usage_cost = float(span.get("estimated_cost") or 0.0)
            if context.kind == "llm" and (usage_tokens or usage_cost):
                state.add_usage(usage_tokens, usage_cost)
        if first is not None:
            affected.append({
                "trace_id": trace_id,
                "name": trace.get("workflow_name") or trace.get("name"),
                "status": trace.get("status"),
                "started_at": trace.get("started_at"),
                "blocked_calls": counts.get("deny", 0),
                "approval_calls": counts.get("require_approval", 0),
                "first": first,
            })
    rules = [
        {**{key: value for key, value in entry.items() if key != "traces"}, "traces": len(entry["traces"])}
        for entry in by_rule.values()
    ]
    rules.sort(key=lambda entry: (-entry["traces"], -entry["calls"]))
    return {
        "traces_evaluated": evaluated,
        "actions_evaluated": actions,
        "traces_affected": len(affected),
        "blocked_calls": sum(item["blocked_calls"] for item in affected),
        "approval_calls": sum(item["approval_calls"] for item in affected),
        "rules": rules,
        "traces": affected,
    }


def _timestamp(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
