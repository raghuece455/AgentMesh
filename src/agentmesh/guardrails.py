"""Enforce policies on running agents: block calls, pause for approval, and stop on a halt.

Guardrails check each tool call, LLM call, and agent start *before* it runs:

* SDK spans from ``@agentmesh.observe(kind="tool" | "llm" | "agent")``, ``agentmesh.span(...)``,
  and ``agentmesh.trace(...)``;
* OpenAI and Anthropic calls made through ``instrument_openai`` / ``instrument_anthropic``;
* tool calls, model calls, and agents in the AgentMesh runtime.

Policies and halts (the kill switch) come from where traces go: the local database, or the
AgentMesh server set by ``endpoint``. They are refreshed every few seconds (from a server, in a
background thread, so a slow server never delays an agent), so a policy saved or a halt pressed in
the dashboard reaches running agents without a restart. Policies can also be passed in code
(``agentmesh.init(policies=[...])``).

A blocked call raises :class:`~agentmesh.errors.PolicyViolation` (or :class:`AgentHalted`)
into the agent, so the agent's own error handling decides what happens next. Every decision is
recorded on the span and appears on the dashboard's Guardrails page.

If policies cannot be loaded (for example the server is unreachable), guardrails keep using the
last policies they loaded. With no policies loaded yet, calls are allowed unless
``AGENTMESH_GUARDRAILS_FAIL_CLOSED=true``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import weakref
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agentmesh.errors import AgentHalted, ApprovalDenied, PolicyViolation
from agentmesh.policy import ActionContext, Decision, Policy, PolicyEngine, PolicyError, RunState, short_name
from agentmesh.types import JsonObject

logger = logging.getLogger("agentmesh.guardrails")

MAX_TRACKED_TRACES = 2000
DEFAULT_REFRESH_SECONDS = 5.0
DEFAULT_APPROVAL_POLL_SECONDS = 2.0


class GuardrailsBackend(Protocol):
    """Where guardrails load policies and halts from, and where approvals are requested."""

    def runtime_config(self) -> JsonObject: ...

    def create_approval(self, trace_id: str | None, agent: str, target: str, arguments: JsonObject) -> str: ...

    def get_approval(self, approval_id: str) -> JsonObject | None: ...


class StoreBackend:
    """Reads a local AgentMesh store (SQLite or PostgreSQL)."""

    def __init__(self, store: Any) -> None:
        self._store = store

    @property
    def store(self) -> Any:
        return self._store() if callable(self._store) else self._store

    def runtime_config(self) -> JsonObject:
        return self.store.policy_runtime_config()

    def create_approval(self, trace_id: str | None, agent: str, target: str, arguments: JsonObject) -> str:
        return self.store.create_approval(trace_id, agent, target, arguments)

    def get_approval(self, approval_id: str) -> JsonObject | None:
        return self.store.get_approval(approval_id)

    def save_decisions(self, decisions: list[JsonObject]) -> None:
        self.store.save_policy_decisions(decisions)


class HttpBackend:
    """Talks to an AgentMesh server."""

    # Refreshed in a background thread: a network call must never stall the agent that triggers it.
    remote = True

    def __init__(self, endpoint: str, api_key: str | None = None, timeout_seconds: float = 5.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, payload: JsonObject | None = None) -> Any:
        headers = {"Accept": "application/json", "User-Agent": "agentmesh-python-sdk"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, default=str).encode("utf-8")
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(f"{self.endpoint}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read()
        return json.loads(body) if body else None

    def runtime_config(self) -> JsonObject:
        try:
            return self._request("GET", "/api/guardrails/runtime")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            # A server older than 0.5 has no guardrails endpoint: nothing to enforce.
            if not getattr(self, "_warned_unsupported", False):
                logger.info("AgentMesh server at %s does not support guardrails; upgrade it to enforce policies", self.endpoint)
                self._warned_unsupported = True
            return {"policies": [], "halts": []}

    def create_approval(self, trace_id: str | None, agent: str, target: str, arguments: JsonObject) -> str:
        created = self._request("POST", "/api/approvals", {"trace_id": trace_id, "agent": agent, "tool": target, "arguments": arguments})
        return str(created["approval_id"])

    def get_approval(self, approval_id: str) -> JsonObject | None:
        try:
            return self._request("GET", f"/api/approvals/{approval_id}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise


@dataclass(slots=True)
class _Loaded:
    engine: PolicyEngine
    halts: list[JsonObject]
    loaded_at: float
    ok: bool


class Guardrails:
    """Checks actions against policies and halts, and keeps per-trace state for limits."""

    def __init__(
        self,
        backend: GuardrailsBackend | None = None,
        policies: list[Policy | JsonObject | str] | None = None,
        *,
        service: str | None = None,
        environment: str | None = None,
        refresh_seconds: float | None = None,
        approval_poll_seconds: float = DEFAULT_APPROVAL_POLL_SECONDS,
        fail_closed: bool | None = None,
        on_decisions: Callable[[list[JsonObject]], None] | None = None,
        capture_content: bool = True,
    ) -> None:
        self.backend = backend
        self.local_policies = [_as_policy(item) for item in policies or []]
        self.service = service
        self.environment = environment
        self.refresh_seconds = refresh_seconds if refresh_seconds is not None else _env_float("AGENTMESH_GUARDRAILS_REFRESH_SECONDS", DEFAULT_REFRESH_SECONDS)
        self.approval_poll_seconds = approval_poll_seconds
        self.fail_closed = fail_closed if fail_closed is not None else _env_flag("AGENTMESH_GUARDRAILS_FAIL_CLOSED", False)
        self.on_decisions = on_decisions
        # With content capture off, approval requests carry argument names but not values.
        self.capture_content = capture_content
        self._loaded: _Loaded | None = None
        self._load_lock = threading.Lock()
        self._refreshing = False
        self._failing = False
        self._states: OrderedDict[str, RunState] = OrderedDict()
        self._states_lock = threading.Lock()

    # -- configuration --------------------------------------------------------------
    def _config(self) -> _Loaded:
        loaded = self._loaded
        if loaded is not None and time.monotonic() - loaded.loaded_at < self.refresh_seconds:
            return loaded
        if loaded is not None and getattr(self.backend, "remote", False):
            self._refresh_in_background()
            return loaded
        with self._load_lock:
            loaded = self._loaded
            if loaded is not None and time.monotonic() - loaded.loaded_at < self.refresh_seconds:
                return loaded
            self._loaded = self._load(loaded)
            return self._loaded

    def _refresh_in_background(self) -> None:
        with self._load_lock:
            if self._refreshing:
                return
            self._refreshing = True

        def run() -> None:
            try:
                loaded = self._load(self._loaded)
                with self._load_lock:
                    self._loaded = loaded
            finally:
                self._refreshing = False

        threading.Thread(target=run, name="agentmesh-guardrails-refresh", daemon=True).start()

    def _load(self, previous: _Loaded | None) -> _Loaded:
        if self.backend is None:
            return _Loaded(PolicyEngine(self.local_policies), [], time.monotonic(), True)
        try:
            config = self.backend.runtime_config() or {}
            remote: list[Policy] = []
            for item in config.get("policies") or []:
                try:
                    remote.append(Policy.from_spec(item.get("spec") or {}, policy_id=item.get("policy_id")))
                except PolicyError as exc:
                    logger.warning("Skipping invalid policy %s: %s", item.get("policy_id"), exc)
            if self._failing:
                logger.info("Guardrail policies loaded again")
                self._failing = False
            return _Loaded(PolicyEngine([*self.local_policies, *remote]), list(config.get("halts") or []), time.monotonic(), True)
        except Exception as exc:
            # Warn once when loading starts failing, not on every refresh.
            log = logger.debug if self._failing else logger.warning
            self._failing = True
            log("Could not load guardrail policies (%s); %s", exc, "keeping the last loaded policies" if previous else "no policies loaded yet")
            if previous is not None:
                return _Loaded(previous.engine, previous.halts, time.monotonic(), previous.ok)
            return _Loaded(PolicyEngine(self.local_policies), [], time.monotonic(), False)

    def refresh(self) -> None:
        """Reload policies and halts now instead of waiting for the refresh interval."""
        with self._load_lock:
            self._loaded = self._load(self._loaded)

    @property
    def active(self) -> bool:
        """True when there is anything to enforce (cheap enough to call on every span)."""
        loaded = self._config()
        return bool(loaded.engine) or bool(loaded.halts) or (self.fail_closed and not loaded.ok)

    # -- per-trace state ------------------------------------------------------------
    def state(self, trace_id: str) -> RunState:
        with self._states_lock:
            state = self._states.get(trace_id)
            if state is None:
                state = RunState()
                self._states[trace_id] = state
                while len(self._states) > MAX_TRACKED_TRACES:
                    self._states.popitem(last=False)
            else:
                self._states.move_to_end(trace_id)
            return state

    def register_span(self, trace_id: str, span_id: str, parent_span_id: str | None, is_agent: bool = False) -> None:
        self.state(trace_id).register_span(span_id, parent_span_id, is_agent)

    def add_usage(self, trace_id: str, tokens: int = 0, cost_usd: float = 0.0) -> None:
        self.state(trace_id).add_usage(tokens, cost_usd)

    def forget(self, trace_id: str) -> None:
        with self._states_lock:
            self._states.pop(trace_id, None)

    # -- checks -----------------------------------------------------------------------
    def evaluate(self, context: ActionContext) -> tuple[list[Decision], Decision | None]:
        """Decisions for an action without waiting for approval or changing state."""
        context.service = context.service or self.service
        context.environment = context.environment or self.environment
        loaded = self._config()
        halt = self._matching_halt(loaded.halts, context)
        if halt is not None:
            decision = Decision(
                action="deny",
                enforced=True,
                rule="halt",
                reason=halt.get("reason") or f"Stopped by a {halt.get('scope')} halt",
                kind=context.kind,
                target=context.target,
                details={"halt_id": halt.get("halt_id"), "scope": halt.get("scope"), "value": halt.get("value")},
            )
            return [decision], decision
        if not loaded.ok and self.fail_closed and not loaded.engine:
            decision = Decision("deny", True, "fail_closed", "Guardrail policies could not be loaded and AGENTMESH_GUARDRAILS_FAIL_CLOSED is set", context.kind, context.target)
            return [decision], decision
        if not loaded.engine or context.kind not in {"tool", "llm", "agent"}:
            return [], None
        decisions = loaded.engine.evaluate(context, self.state(context.trace_id))
        return decisions, PolicyEngine.verdict(decisions)

    def check(self, context: ActionContext, record: Callable[[Decision], None] | None = None) -> list[Decision]:
        """Enforce policies for an action, blocking on approval if required. Raises when not allowed."""
        decisions, verdict = self.evaluate(context)
        for decision in decisions:
            if record is not None:
                record(decision)
        self._report(context, decisions)
        if verdict is not None and verdict.rule == "halt":
            raise AgentHalted(verdict.reason, _violation_details(context, verdict))
        if verdict is not None and verdict.blocks:
            raise PolicyViolation(verdict.reason, _violation_details(context, verdict))
        if verdict is not None and verdict.needs_approval:
            approved, detail = self._wait_for_approval(context, verdict)
            outcome = Decision(
                action="allow" if approved else "deny",
                enforced=True,
                rule=verdict.rule,
                reason=detail,
                kind=context.kind,
                target=context.target,
                policy_name=verdict.policy_name,
                policy_id=verdict.policy_id,
                details={"approval": True, **verdict.details},
            )
            if record is not None:
                record(outcome)
            self._report(context, [outcome])
            if not approved:
                raise ApprovalDenied(detail, _violation_details(context, verdict))
        if context.kind in {"tool", "llm", "agent"}:
            self.state(context.trace_id).record(context)
        return decisions

    async def acheck(self, context: ActionContext, record: Callable[[Decision], None] | None = None) -> list[Decision]:
        """:meth:`check` for async code: waiting for approval does not block the event loop."""
        decisions, verdict = self.evaluate(context)
        if verdict is not None and verdict.needs_approval:
            return await asyncio.to_thread(self.check, context, record)
        return self.check(context, record)

    def _matching_halt(self, halts: list[JsonObject], context: ActionContext) -> JsonObject | None:
        for halt in halts:
            scope, value = halt.get("scope"), halt.get("value")
            if (
                scope == "all"
                or (scope == "trace" and value == context.trace_id)
                or (scope == "agent" and context.agent is not None and value in {context.agent, short_name(context.agent)})
                or (scope == "agent" and context.kind == "agent" and value in {context.name, short_name(context.name)})
                or (scope == "service" and context.service is not None and value == context.service)
            ):
                return halt
        return None

    def _wait_for_approval(self, context: ActionContext, verdict: Decision) -> tuple[bool, str]:
        if self.backend is None:
            return False, f"{verdict.reason} (no AgentMesh server or database configured to request approval)"
        timeout = next(
            (policy.approval_timeout_seconds for policy in self._config().engine.policies if policy.policy_id == verdict.policy_id and policy.name == verdict.policy_name),
            300.0,
        )
        arguments = context.arguments if isinstance(context.arguments, dict) else {"input": context.arguments}
        if not self.capture_content:
            arguments = {"argument_names": sorted(str(key) for key in arguments), "content": "not captured (AGENTMESH_CAPTURE_CONTENT=false)"}
        try:
            approval_id = self.backend.create_approval(context.trace_id, context.agent or context.name, context.target, {**arguments, "_policy": {"rule": verdict.rule, "reason": verdict.reason}})
        except Exception as exc:
            return False, f"{verdict.reason} (could not request approval: {exc})"
        logger.info("Waiting up to %ss for approval %s (%s %s)", int(timeout), approval_id, context.kind, context.target)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                approval = self.backend.get_approval(approval_id)
            except Exception as exc:  # keep waiting through transient errors
                logger.debug("Approval lookup failed: %s", exc)
                approval = None
            status = (approval or {}).get("status")
            if status == "approved":
                return True, f"Approved ({approval_id})"
            if status == "rejected":
                return False, f"Rejected by a reviewer ({approval_id}){': ' + approval['reason'] if approval and approval.get('reason') else ''}"
            time.sleep(min(self.approval_poll_seconds, max(deadline - time.monotonic(), 0.01)))
        return False, f"No approval within {int(timeout)}s ({approval_id}); denied"

    def _report(self, context: ActionContext, decisions: list[Decision]) -> None:
        if not decisions or self.on_decisions is None:
            return
        try:
            self.on_decisions([decision_record(context, decision, index) for index, decision in enumerate(decisions)])
        except Exception:
            logger.debug("Recording guardrail decisions failed", exc_info=True)


def decision_record(context: ActionContext, decision: Decision, index: int = 0) -> JsonObject:
    from agentmesh.types import new_id, utc_now

    return {
        "decision_id": new_id("decision") if context.span_id is None else f"decision_{context.span_id}_{decision.rule}_{decision.action}_{index}",
        "trace_id": context.trace_id,
        "span_id": context.span_id,
        "agent": context.agent,
        "service": context.service,
        "created_at": utc_now(),
        **decision.to_json(),
    }


def _violation_details(context: ActionContext, decision: Decision) -> JsonObject:
    return {
        "rule": decision.rule,
        "policy": decision.policy_name,
        "kind": context.kind,
        "target": context.target,
        "trace_id": context.trace_id,
        **decision.details,
    }


def _as_policy(item: Policy | JsonObject | str) -> Policy:
    if isinstance(item, Policy):
        return item
    if isinstance(item, str) and "\n" not in item and not item.lstrip().startswith("{"):
        if not os.path.isfile(item):
            raise PolicyError([f"policy file not found: {item}"])
        with open(item, encoding="utf-8") as handle:
            try:
                return Policy.from_spec(handle.read())
            except PolicyError as exc:
                raise PolicyError([f"{item}: {error}" for error in exc.errors]) from exc
    return Policy.from_spec(item)


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


_runtime_guardrails: weakref.WeakKeyDictionary[Any, Guardrails] = weakref.WeakKeyDictionary()
_runtime_lock = threading.Lock()


def for_store(store: Any) -> Guardrails:
    """Guardrails for the AgentMesh runtime, reading policies from its store. One per store."""
    with _runtime_lock:
        guardrails = _runtime_guardrails.get(store)
        if guardrails is None:
            backend = StoreBackend(store)
            guardrails = Guardrails(backend, on_decisions=backend.save_decisions)
            _runtime_guardrails[store] = guardrails
        return guardrails
