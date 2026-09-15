"""Instrument any Python agent code, whatever framework it uses.

    import agentmesh

    agentmesh.init(service_name="support-bot")          # local SQLite by default

    @agentmesh.observe(kind="tool")
    def search_docs(query: str) -> list[str]: ...

    @agentmesh.observe(kind="agent")
    async def support_agent(question: str) -> str: ...

    with agentmesh.trace("ticket-1234", session_id="chat-42", user_id="u-7"):
        await support_agent("Where is my order?")

Spans are exported in the background either straight into a local AgentMesh
database or, when ``endpoint`` / ``AGENTMESH_ENDPOINT`` is set, to a remote
AgentMesh server as OTLP/JSON (so any OpenTelemetry collector works too).
Instrumentation never raises into your application: export failures are logged.
"""

from __future__ import annotations

import atexit
import contextvars
import functools
import inspect
import json
import logging
import os
import queue
import secrets
import threading
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from agentmesh.ingest import SpanData
from agentmesh.types import JsonObject, safe_json

logger = logging.getLogger("agentmesh.sdk")

F = TypeVar("F", bound=Callable[..., Any])

KIND_OPERATION = {
    "agent": "invoke_agent",
    "tool": "execute_tool",
    "llm": "chat",
    "embedding": "embeddings",
    "retrieval": "retrieval",
    "workflow": "invoke_workflow",
}
OPENINFERENCE_KIND = {
    "agent": "AGENT",
    "tool": "TOOL",
    "llm": "LLM",
    "embedding": "EMBEDDING",
    "retrieval": "RETRIEVER",
    "guardrail": "GUARDRAIL",
    "evaluator": "EVALUATOR",
}
MAX_CAPTURED_ITEMS = 1000

_current_span: contextvars.ContextVar[Span | None] = contextvars.ContextVar("agentmesh_current_span", default=None)
_trace_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "agentmesh_trace_context", default=None
)


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------


class SpanExporter:
    def export(self, spans: list[SpanData]) -> None:
        raise NotImplementedError

    def send_score(self, payload: JsonObject) -> None:
        raise NotImplementedError

    def shutdown(self) -> None:
        return None


class NoopExporter(SpanExporter):
    def export(self, spans: list[SpanData]) -> None:
        return None

    def send_score(self, payload: JsonObject) -> None:
        return None


@dataclass(slots=True)
class InMemoryExporter(SpanExporter):
    """Collects spans in memory. Useful in tests."""

    spans: list[SpanData] = field(default_factory=list)
    scores: list[JsonObject] = field(default_factory=list)

    def export(self, spans: list[SpanData]) -> None:
        self.spans.extend(spans)

    def send_score(self, payload: JsonObject) -> None:
        self.scores.append(payload)


class LocalStoreExporter(SpanExporter):
    """Writes spans directly into a local AgentMesh database."""

    def __init__(self, db_path: str, capture_content: bool = True) -> None:
        self.db_path = db_path
        self.capture_content = capture_content
        self._store: Any = None
        self._lock = threading.Lock()

    @property
    def store(self) -> Any:
        with self._lock:
            if self._store is None:
                from agentmesh.stores import create_store

                self._store = create_store(self.db_path)
            return self._store

    def export(self, spans: list[SpanData]) -> None:
        self.store.ingest_spans(spans, source="sdk", capture_content=self.capture_content)

    def send_score(self, payload: JsonObject) -> None:
        self.store.save_score(payload)


class HttpExporter(SpanExporter):
    """Sends OTLP/JSON to an AgentMesh server (or any OTLP/HTTP JSON receiver)."""

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        resource: dict[str, Any] | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.resource = resource or {}

    def export(self, spans: list[SpanData]) -> None:
        from agentmesh.otlp import encode_json

        self._post("/v1/traces", encode_json(spans, self.resource))

    def send_score(self, payload: JsonObject) -> None:
        self._post("/api/scores", payload)

    def _post(self, path: str, payload: JsonObject) -> None:
        headers = {"Content-Type": "application/json", "User-Agent": "agentmesh-python-sdk"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.endpoint}{path}", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    response.read()
                    return
            except urllib.error.HTTPError as exc:
                if exc.code < 500 and exc.code != 429:
                    raise
                last_error = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error


class BatchProcessor:
    """Exports spans from a daemon thread so instrumented code never blocks on I/O."""

    def __init__(
        self,
        exporter: SpanExporter,
        max_batch_size: int = 512,
        flush_interval: float = 1.0,
        max_queue_size: int = 10_000,
    ) -> None:
        self.exporter = exporter
        self.max_batch_size = max_batch_size
        self.flush_interval = flush_interval
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max_queue_size)
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._dropped = 0

    def on_end(self, span: SpanData) -> None:
        self._enqueue(("span", span))

    def on_score(self, payload: JsonObject) -> None:
        self._enqueue(("score", payload))

    def flush(self, timeout: float = 10.0) -> bool:
        if self._thread is None:
            return True
        done = threading.Event()
        self._enqueue(("flush", done), block=True)
        return done.wait(timeout)

    def shutdown(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        try:
            self.exporter.shutdown()
        except Exception:  # pragma: no cover - defensive
            logger.debug("exporter shutdown failed", exc_info=True)

    def _enqueue(self, item: tuple[str, Any], block: bool = False) -> None:
        self._ensure_thread()
        try:
            self._queue.put(item, block=block, timeout=5 if block else None)
        except queue.Full:
            self._dropped += 1
            if self._dropped in {1, 100, 10_000}:
                logger.warning("AgentMesh span queue is full; dropped %s item(s)", self._dropped)

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="agentmesh-exporter", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        batch: list[SpanData] = []
        while True:
            try:
                kind, value = self._queue.get(timeout=self.flush_interval)
            except queue.Empty:
                self._export(batch)
                batch = []
                continue
            if kind == "span":
                batch.append(value)
                if len(batch) >= self.max_batch_size:
                    self._export(batch)
                    batch = []
            elif kind == "score":
                self._export(batch)
                batch = []
                self._safely(self.exporter.send_score, value)
            elif kind == "flush":
                self._export(batch)
                batch = []
                value.set()

    def _export(self, batch: list[SpanData]) -> None:
        if batch:
            self._safely(self.exporter.export, batch)

    def _safely(self, function: Callable[[Any], None], value: Any) -> None:
        try:
            function(value)
        except Exception as exc:
            logger.warning("AgentMesh export failed: %s", exc)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AgentMeshConfig:
    endpoint: str | None = None
    api_key: str | None = None
    db_path: str = ".agentmesh/agentmesh.db"
    service_name: str = "agentmesh-app"
    environment: str | None = None
    enabled: bool = True
    capture_content: bool = True
    flush_interval: float = 1.0
    max_batch_size: int = 512
    guardrails: bool = True
    policies: list[Any] = field(default_factory=list)


class AgentMeshClient:
    def __init__(self, config: AgentMeshConfig, exporter: SpanExporter | None = None) -> None:
        from agentmesh import __version__

        self.config = config
        self.resource: dict[str, Any] = {
            "service.name": config.service_name,
            "telemetry.sdk.name": "agentmesh",
            "telemetry.sdk.language": "python",
            "telemetry.sdk.version": __version__,
        }
        if config.environment:
            self.resource["deployment.environment.name"] = config.environment
        if exporter is None:
            if not config.enabled:
                exporter = NoopExporter()
            elif config.endpoint:
                exporter = HttpExporter(config.endpoint, config.api_key, resource=self.resource)
            else:
                exporter = LocalStoreExporter(config.db_path, config.capture_content)
        self.exporter = exporter
        self.processor = BatchProcessor(exporter, config.max_batch_size, config.flush_interval)
        self.guardrails = self._create_guardrails(config, exporter)

    @staticmethod
    def _create_guardrails(config: AgentMeshConfig, exporter: SpanExporter) -> Any:
        """Guardrails read policies and halts from wherever this client sends traces."""
        if not config.guardrails:
            return None
        from agentmesh.guardrails import Guardrails, HttpBackend, StoreBackend

        backend: Any = None
        if isinstance(exporter, HttpExporter):
            backend = HttpBackend(exporter.endpoint, exporter.api_key)
        elif isinstance(exporter, LocalStoreExporter):
            local = exporter
            backend = StoreBackend(lambda: local.store)
        if backend is None and not config.policies:
            return None
        return Guardrails(
            backend, list(config.policies), service=config.service_name, environment=config.environment, capture_content=config.capture_content
        )

    def export(self, span: SpanData) -> None:
        if self.config.enabled:
            self.processor.on_end(span)

    def score(self, payload: JsonObject) -> None:
        if self.config.enabled:
            self.processor.on_score(payload)

    def flush(self, timeout: float = 10.0) -> bool:
        return self.processor.flush(timeout)

    def shutdown(self, timeout: float = 5.0) -> None:
        self.processor.shutdown(timeout)


_client: AgentMeshClient | None = None
_client_lock = threading.Lock()
_lazy_init_lock = threading.Lock()


def init(
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
    db_path: str | None = None,
    service_name: str | None = None,
    environment: str | None = None,
    enabled: bool | None = None,
    capture_content: bool | None = None,
    flush_interval: float = 1.0,
    max_batch_size: int = 512,
    exporter: SpanExporter | None = None,
    policies: list[Any] | None = None,
    guardrails: bool | None = None,
) -> AgentMeshClient:
    """Configure tracing and guardrails. Every argument falls back to an environment variable.

    ``AGENTMESH_ENDPOINT``, ``AGENTMESH_API_KEY``, ``AGENTMESH_DB_URL``,
    ``AGENTMESH_SERVICE_NAME`` (or ``OTEL_SERVICE_NAME``), ``AGENTMESH_ENVIRONMENT``,
    ``AGENTMESH_TRACING_ENABLED``, ``AGENTMESH_CAPTURE_CONTENT``, ``AGENTMESH_GUARDRAILS``,
    ``AGENTMESH_POLICY_FILE``.

    ``policies`` adds guardrail policies in code (``Policy`` objects, dicts, YAML/JSON text, or
    file paths) on top of the policies saved on the server or in the database.
    """
    policy_file = os.getenv("AGENTMESH_POLICY_FILE")
    configured_policies = list(policies or [])
    if policy_file:
        configured_policies.extend(path.strip() for path in policy_file.split(os.pathsep) if path.strip())
    global _client
    config = AgentMeshConfig(
        endpoint=endpoint if endpoint is not None else os.getenv("AGENTMESH_ENDPOINT") or None,
        api_key=api_key if api_key is not None else os.getenv("AGENTMESH_API_KEY") or None,
        db_path=db_path or os.getenv("AGENTMESH_DB_URL") or os.getenv("AGENTMESH_DB") or ".agentmesh/agentmesh.db",
        service_name=service_name
        or os.getenv("AGENTMESH_SERVICE_NAME")
        or os.getenv("OTEL_SERVICE_NAME")
        or "agentmesh-app",
        environment=environment or os.getenv("AGENTMESH_ENVIRONMENT") or None,
        enabled=enabled if enabled is not None else _env_flag("AGENTMESH_TRACING_ENABLED", True),
        capture_content=capture_content
        if capture_content is not None
        else _env_flag("AGENTMESH_CAPTURE_CONTENT", True),
        flush_interval=flush_interval,
        max_batch_size=max_batch_size,
        guardrails=guardrails if guardrails is not None else _env_flag("AGENTMESH_GUARDRAILS", True),
        policies=configured_policies,
    )
    with _client_lock:
        previous = _client
        _client = AgentMeshClient(config, exporter)
    if previous is not None:
        previous.shutdown()
    return _client


def get_client() -> AgentMeshClient:
    """Return the configured client, initializing from environment variables on first use."""
    client = _client
    if client is not None:
        return client
    with _lazy_init_lock:
        if _client is None:
            init()
    assert _client is not None
    return _client


def flush(timeout: float = 10.0) -> bool:
    """Block until queued spans are exported. Call before a short-lived process exits."""
    return _client.flush(timeout) if _client is not None else True


def shutdown(timeout: float = 5.0) -> None:
    if _client is not None:
        _client.shutdown(timeout)


@atexit.register
def _flush_at_exit() -> None:
    if _client is not None:
        try:
            _client.flush(timeout=5.0)
        except Exception:  # pragma: no cover - interpreter shutdown
            pass


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------


class Span:
    """A unit of work. Use as a (async) context manager, or call :meth:`end`."""

    def __init__(
        self,
        name: str,
        kind: str = "chain",
        attributes: dict[str, Any] | None = None,
        parent: Span | None = None,
        trace_attributes: dict[str, Any] | None = None,
    ) -> None:
        parent = parent if parent is not None else _current_span.get()
        self.name = name
        self.kind = kind
        self.trace_id = parent.trace_id if parent is not None else secrets.token_hex(16)
        self.span_id = secrets.token_hex(8)
        self.parent_span_id = parent.span_id if parent is not None else None
        self.start_time = _now()
        self.end_time: str | None = None
        self.attributes: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.status = "unset"
        self.status_message: str | None = None
        self._tokens: list[tuple[contextvars.ContextVar[Any], contextvars.Token[Any]]] = []
        self._trace_attributes = trace_attributes
        # Guardrails: the agent this span runs under, the raw input policies match against, and
        # whether the span has been checked (spans are checked once, before they first run).
        self._agent_name: str | None = name if kind == "agent" else (parent._agent_name if parent is not None else None)
        self._policy_input: Any = None
        self._policy_checked = False
        guardrails = _guardrails()
        if guardrails is not None and guardrails.active:
            guardrails.register_span(self.trace_id, self.span_id, self.parent_span_id, kind == "agent")

        operation = KIND_OPERATION.get(kind)
        if operation:
            self.attributes["gen_ai.operation.name"] = operation
        if kind in OPENINFERENCE_KIND:
            self.attributes["openinference.span.kind"] = OPENINFERENCE_KIND[kind]
        if kind == "agent":
            self.attributes["gen_ai.agent.name"] = name
        elif kind == "tool":
            self.attributes["gen_ai.tool.name"] = name
        elif kind == "workflow":
            self.attributes["gen_ai.workflow.name"] = name
        inherited = dict(_trace_context.get() or {})
        inherited.update(trace_attributes or {})
        self.set_attributes(inherited)
        self.set_attributes(attributes or {})

    # -- attributes -------------------------------------------------------
    def set_attribute(self, key: str, value: Any) -> Span:
        if value is not None:
            self.attributes[key] = _attribute_value(value)
        return self

    def set_attributes(self, values: dict[str, Any]) -> Span:
        for key, value in values.items():
            self.set_attribute(key, value)
        return self

    def set_input(self, value: Any) -> Span:
        if _capture_content():
            self.attributes["input.value"] = _serialize(value)
            if self.kind == "tool":
                self.attributes["gen_ai.tool.call.arguments"] = self.attributes["input.value"]
        return self

    def set_output(self, value: Any) -> Span:
        if _capture_content():
            self.attributes["output.value"] = _serialize(value)
            if self.kind == "tool":
                self.attributes["gen_ai.tool.call.result"] = self.attributes["output.value"]
        return self

    def set_model(
        self,
        model: str,
        provider: str | None = None,
        *,
        response_model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> Span:
        return self.set_attributes(
            {
                "gen_ai.request.model": model,
                "gen_ai.response.model": response_model,
                "gen_ai.provider.name": provider,
                "gen_ai.request.temperature": temperature,
                "gen_ai.request.top_p": top_p,
                "gen_ai.request.max_tokens": max_tokens,
            }
        )

    def set_usage(
        self,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        *,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> Span:
        """Record token usage. ``input_tokens`` should include cached tokens (OTel GenAI convention)."""
        return self.set_attributes(
            {
                "gen_ai.usage.input_tokens": input_tokens,
                "gen_ai.usage.output_tokens": output_tokens,
                "gen_ai.usage.cache_read.input_tokens": cache_read_tokens,
                "gen_ai.usage.cache_write.input_tokens": cache_write_tokens,
                "gen_ai.usage.reasoning.output_tokens": reasoning_tokens,
                "agentmesh.cost_usd": cost_usd,
            }
        )

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> Span:
        self.events.append(
            {
                "name": name,
                "time": _now(),
                "attributes": {
                    key: _attribute_value(value) for key, value in (attributes or {}).items() if value is not None
                },
            }
        )
        return self

    def record_exception(self, exc: BaseException) -> Span:
        self.add_event(
            "exception",
            {
                "exception.type": type(exc).__name__,
                "exception.message": str(exc),
                "exception.stacktrace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-8000:],
            },
        )
        self.attributes["error.type"] = type(exc).__name__
        return self.set_status("error", str(exc) or type(exc).__name__)

    def set_status(self, status: str, message: str | None = None) -> Span:
        self.status = status if status in {"ok", "error", "unset"} else "unset"
        self.status_message = message
        return self

    def score(
        self, name: str, value: float | bool | str, *, comment: str | None = None, label: str | None = None
    ) -> None:
        score(name, value, trace_id=self.trace_id, span_id=self.span_id, comment=comment, label=label)

    # -- guardrails ----------------------------------------------------------
    def _policy_context(self, arguments: Any = None) -> Any:
        from agentmesh.policy import ActionContext

        kind = {"llm": "llm", "embedding": "llm", "tool": "tool", "agent": "agent"}.get(self.kind, "other")
        return ActionContext(
            kind=kind,
            name=self.name,
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            agent=self._agent_name,
            model=self.attributes.get("gen_ai.request.model"),
            provider=self.attributes.get("gen_ai.provider.name"),
            arguments=arguments if arguments is not None else self._policy_input,
        )

    def _record_decision(self, decision: Any) -> None:
        self.add_event(
            "agentmesh.policy.decision",
            {
                "agentmesh.policy.action": decision.action,
                "agentmesh.policy.enforced": decision.enforced,
                "agentmesh.policy.rule": decision.rule,
                "agentmesh.policy.reason": decision.reason,
                "agentmesh.policy.kind": decision.kind,
                "agentmesh.policy.target": decision.target,
                "agentmesh.policy.name": decision.policy_name,
                "agentmesh.policy.id": decision.policy_id,
                "agentmesh.policy.agent": self._agent_name,
                "agentmesh.policy.details": json.dumps(decision.details, default=str) if decision.details else None,
            },
        )

    def _blocked(self, exc: BaseException) -> None:
        self.set_attribute("agentmesh.policy.blocked", True)
        self.record_exception(exc)
        self.end()

    def enforce(self, arguments: Any = None) -> None:
        """Check this span against guardrail policies before it runs. Raises ``PolicyViolation``.

        Called automatically when the span is entered; call it yourself for spans you never enter.
        """
        if self._policy_checked:
            return
        self._policy_checked = True
        guardrails = _guardrails()
        if guardrails is None or not guardrails.active:
            return
        from agentmesh.errors import PolicyViolation

        try:
            guardrails.check(self._policy_context(arguments), self._record_decision)
        except PolicyViolation as exc:
            self._blocked(exc)
            raise

    async def aenforce(self, arguments: Any = None) -> None:
        """:meth:`enforce` for async code; waiting for an approval does not block the event loop."""
        if self._policy_checked:
            return
        self._policy_checked = True
        guardrails = _guardrails()
        if guardrails is None or not guardrails.active:
            return
        from agentmesh.errors import PolicyViolation

        try:
            await guardrails.acheck(self._policy_context(arguments), self._record_decision)
        except PolicyViolation as exc:
            self._blocked(exc)
            raise

    # -- lifecycle ----------------------------------------------------------
    def end(self) -> None:
        if self.end_time is not None:
            return
        self.end_time = _now()
        guardrails = _guardrails()
        if guardrails is not None and guardrails.active:
            self._account_usage(guardrails)
        client = get_client()
        client.export(
            SpanData(
                trace_id=self.trace_id,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
                name=self.name,
                kind="CLIENT" if self.kind in {"llm", "embedding"} else "INTERNAL",
                start_time=self.start_time,
                end_time=self.end_time,
                status=self.status,
                status_message=self.status_message,
                attributes=dict(self.attributes),
                events=list(self.events),
                resource=client.resource,
                scope="agentmesh.sdk",
            )
        )

    def _account_usage(self, guardrails: Any) -> None:
        """Add an LLM call's tokens and cost to its trace, for cost and token limits."""
        if self.kind not in {"llm", "embedding"}:
            return
        input_tokens = int(self.attributes.get("gen_ai.usage.input_tokens") or 0)
        output_tokens = int(self.attributes.get("gen_ai.usage.output_tokens") or 0)
        cost = self.attributes.get("agentmesh.cost_usd")
        if cost is None and (input_tokens or output_tokens):
            from agentmesh.pricing import estimate_model_cost

            cost = estimate_model_cost(
                self.attributes.get("gen_ai.provider.name"),
                self.attributes.get("gen_ai.response.model") or self.attributes.get("gen_ai.request.model"),
                input_tokens,
                output_tokens,
                int(self.attributes.get("gen_ai.usage.cache_read.input_tokens") or 0),
            ).cost_usd
        if input_tokens or output_tokens or cost:
            guardrails.add_usage(self.trace_id, input_tokens + output_tokens, float(cost or 0.0))

    def activate(self) -> Span:
        if not self._policy_checked:
            self.enforce()
        self._tokens.append((_current_span, _current_span.set(self)))
        if self._trace_attributes is not None or self.parent_span_id is None:
            # Always scope trace-level context to traces and root spans, so values set by
            # update_current_trace() inside them are restored on exit instead of leaking
            # into the next trace on the same thread.
            merged = {**(_trace_context.get() or {}), **(self._trace_attributes or {})}
            self._tokens.append((_trace_context, _trace_context.set(merged)))
        return self

    def deactivate(self) -> None:
        while self._tokens:
            variable, token = self._tokens.pop()
            try:
                variable.reset(token)
            except ValueError:  # reset from a different context; fall back to clearing
                variable.set(None)

    def __enter__(self) -> Span:
        return self.activate()

    def __exit__(self, exc_type: Any, exc: BaseException | None, _tb: Any) -> bool:
        if exc is not None and not isinstance(exc, GeneratorExit):
            self.record_exception(exc)
        self.deactivate()
        self.end()
        return False

    async def __aenter__(self) -> Span:
        await self.aenforce()
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        return self.__exit__(exc_type, exc, tb)


def span(name: str, kind: str = "chain", *, input: Any = None, attributes: dict[str, Any] | None = None) -> Span:
    """Start a span. Use with ``with``/``async with`` so it becomes the parent of nested spans."""
    created = Span(name, kind, attributes)
    if input is not None:
        created.set_input(input)
        created._policy_input = input
    return created


def trace(
    name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    input: Any = None,
    kind: str = "workflow",
) -> Span:
    """Start a trace (a root span) and set session/user/tags for everything inside it."""
    trace_attributes: dict[str, Any] = {}
    if session_id:
        trace_attributes["gen_ai.conversation.id"] = session_id
    if user_id:
        trace_attributes["user.id"] = user_id
    if tags:
        trace_attributes["tag.tags"] = list(tags)
    attributes = {f"agentmesh.metadata.{key}": value for key, value in (metadata or {}).items()}
    created = Span(name, kind, attributes, trace_attributes=trace_attributes)
    if input is not None:
        created.set_input(input)
        created._policy_input = input
    return created


def get_current_span() -> Span | None:
    return _current_span.get()


def get_current_trace_id() -> str | None:
    current = _current_span.get()
    return current.trace_id if current is not None else None


def update_current_trace(
    *, session_id: str | None = None, user_id: str | None = None, tags: list[str] | None = None
) -> None:
    """Set session/user/tags for the current span and any spans started after this call."""
    values: dict[str, Any] = {}
    if session_id:
        values["gen_ai.conversation.id"] = session_id
    if user_id:
        values["user.id"] = user_id
    if tags:
        values["tag.tags"] = list(tags)
    if not values:
        return
    _trace_context.set({**(_trace_context.get() or {}), **values})
    current = _current_span.get()
    if current is not None:
        current.set_attributes(values)


def score(
    name: str,
    value: float | bool | str,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    comment: str | None = None,
    label: str | None = None,
    source: str = "sdk",
) -> None:
    """Attach a score (user feedback, eval metric, judge verdict) to a trace or span."""
    resolved_trace = trace_id or get_current_trace_id()
    if not resolved_trace:
        logger.warning("agentmesh.score(%r) called outside a trace and without trace_id; ignored", name)
        return
    get_client().score(
        {
            "trace_id": resolved_trace,
            "span_id": span_id,
            "name": name,
            "value": value,
            "comment": comment,
            "label": label,
            "source": source,
        }
    )


def observe(
    func: F | None = None,
    *,
    name: str | None = None,
    kind: str = "chain",
    capture_input: bool = True,
    capture_output: bool = True,
    attributes: dict[str, Any] | None = None,
) -> Any:
    """Trace a function. Works with sync, async, generator, and async generator functions.

    ``kind`` is one of ``chain`` (default), ``agent``, ``tool``, ``llm``,
    ``retrieval``, ``embedding``, ``workflow``, ``guardrail``, ``evaluator``.
    """

    def decorator(fn: F) -> F:
        span_name = name or getattr(fn, "__qualname__", getattr(fn, "__name__", "function"))

        def _start(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Span:
            created = Span(span_name, kind, attributes)
            # Guardrails match arguments by name, even when content capture is off.
            created._policy_input = _named_arguments(fn, args, kwargs)
            if capture_input:
                created.set_input(_bind_arguments(fn, args, kwargs))
            return created

        if inspect.isasyncgenfunction(fn):

            @functools.wraps(fn)
            async def async_gen_wrapper(*args: Any, **kwargs: Any) -> Any:
                created = _start(args, kwargs)
                await created.aenforce()
                items: list[Any] = []
                generator = fn(*args, **kwargs)
                try:
                    while True:
                        created.activate()
                        try:
                            item = await generator.__anext__()
                        except StopAsyncIteration:
                            break
                        finally:
                            created.deactivate()
                        if len(items) < MAX_CAPTURED_ITEMS:
                            items.append(item)
                        yield item
                except GeneratorExit:
                    await generator.aclose()
                    raise
                except BaseException as exc:
                    created.record_exception(exc)
                    raise
                finally:
                    if capture_output:
                        created.set_output(items)
                    created.end()

            return async_gen_wrapper  # type: ignore[return-value]

        if inspect.isgeneratorfunction(fn):

            @functools.wraps(fn)
            def gen_wrapper(*args: Any, **kwargs: Any) -> Any:
                created = _start(args, kwargs)
                created.enforce()
                items: list[Any] = []
                generator = fn(*args, **kwargs)
                try:
                    while True:
                        created.activate()
                        try:
                            item = next(generator)
                        except StopIteration as stop:
                            if stop.value is not None and capture_output:
                                items.append(stop.value)
                            break
                        finally:
                            created.deactivate()
                        if len(items) < MAX_CAPTURED_ITEMS:
                            items.append(item)
                        yield item
                except GeneratorExit:
                    generator.close()
                    raise
                except BaseException as exc:
                    created.record_exception(exc)
                    raise
                finally:
                    if capture_output:
                        created.set_output(items)
                    created.end()

            return gen_wrapper  # type: ignore[return-value]

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                started = _start(args, kwargs)
                await started.aenforce()
                with started as created:
                    result = await fn(*args, **kwargs)
                    if capture_output:
                        created.set_output(result)
                    return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _start(args, kwargs) as created:
                result = fn(*args, **kwargs)
                if capture_output:
                    created.set_output(result)
                return result

        return wrapper  # type: ignore[return-value]

    if func is not None and callable(func):
        return decorator(func)
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _guardrails() -> Any:
    return get_client().guardrails


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _capture_content() -> bool:
    return _client.config.capture_content if _client is not None else _env_flag("AGENTMESH_CAPTURE_CONTENT", True)


def _named_arguments(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        return {"args": list(args), "kwargs": kwargs}
    values = dict(bound.arguments)
    for skipped in ("self", "cls"):
        values.pop(skipped, None)
    return values


def _bind_arguments(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    values = _named_arguments(fn, args, kwargs)
    if len(values) == 1:
        return next(iter(values.values()))
    return values


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return str(value)
    return safe_json(value)


def _serialize(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        if isinstance(value, dict):
            return json.dumps({str(key): _jsonable(item) for key, item in value.items()}, default=str)
        if isinstance(value, list | tuple):
            return json.dumps([_jsonable(item) for item in value], default=str)
        return json.dumps(_jsonable(value), default=str)
    except (TypeError, ValueError):
        return str(value)


def _attribute_value(value: Any) -> Any:
    if isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, list | tuple) and all(isinstance(item, str | bool | int | float) for item in value):
        return list(value)
    return _serialize(value)
