"""Shared plumbing for client-library auto-instrumentation."""

from __future__ import annotations

import contextvars
import functools
import logging
from collections.abc import Callable
from typing import Any, Protocol

from agentmesh.sdk import Span

logger = logging.getLogger("agentmesh.integrations")

ORIGINAL_ATTRIBUTE = "__agentmesh_original__"

# Set while an instrumented call is in flight so that a per-client patch layered
# on top of a global patch (or an SDK method calling another patched method)
# produces one span, not two.
_in_call: contextvars.ContextVar[bool] = contextvars.ContextVar("agentmesh_instrumented_call", default=False)


class Accumulator(Protocol):
    def add(self, event: Any) -> None: ...

    def finish(self, span: Span) -> None: ...


class Handler(Protocol):
    def start(self, resource: Any, kwargs: dict[str, Any]) -> Span: ...

    def on_response(self, span: Span, response: Any) -> None: ...

    def accumulator(self) -> Accumulator: ...


def to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            result = dump(mode="json", exclude_none=True)
        except TypeError:
            result = dump()
        return result if isinstance(result, dict) else {}
    return {}


def is_given(value: Any) -> bool:
    """False for None and the SDKs' NOT_GIVEN / Omit sentinels."""
    return value is not None and type(value).__name__ not in {"NotGiven", "Omit"}


def given(kwargs: dict[str, Any], key: str) -> Any:
    value = kwargs.get(key)
    return value if is_given(value) else None


POLICY_REQUEST_KEYS = ("model", "messages", "input", "instructions", "system", "tools", "max_tokens", "max_completion_tokens", "max_output_tokens")


def policy_arguments(kwargs: dict[str, Any]) -> dict[str, Any]:
    """The parts of a model request that guardrail rules can match (``arguments`` / ``input_regex``)."""
    return {key: kwargs[key] for key in POLICY_REQUEST_KEYS if key in kwargs and is_given(kwargs[key])}


def safe(function: Callable[..., None], *args: Any) -> None:
    try:
        function(*args)
    except Exception:
        logger.debug("AgentMesh instrumentation hook failed", exc_info=True)


def call_sync(
    handler: Handler, original: Callable[..., Any], resource: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    if _in_call.get():
        return original(resource, *args, **kwargs)
    span = handler.start(resource, kwargs)
    span.enforce(policy_arguments(kwargs))  # guardrails: raises PolicyViolation before the request is sent
    token = _in_call.set(True)
    try:
        response = original(resource, *args, **kwargs)
    except BaseException as exc:
        span.record_exception(exc)
        span.end()
        raise
    finally:
        _in_call.reset(token)
    if kwargs.get("stream") is True:
        return SyncStreamProxy(response, span, handler.accumulator())
    safe(handler.on_response, span, response)
    span.end()
    return response


async def call_async(
    handler: Handler, original: Callable[..., Any], resource: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    if _in_call.get():
        return await original(resource, *args, **kwargs)
    span = handler.start(resource, kwargs)
    await span.aenforce(policy_arguments(kwargs))
    token = _in_call.set(True)
    try:
        response = await original(resource, *args, **kwargs)
    except BaseException as exc:
        span.record_exception(exc)
        span.end()
        raise
    finally:
        _in_call.reset(token)
    if kwargs.get("stream") is True:
        return AsyncStreamProxy(response, span, handler.accumulator())
    safe(handler.on_response, span, response)
    span.end()
    return response


def patch_class(owner: type, attribute: str, handler: Handler, is_async: bool) -> bool:
    original = owner.__dict__.get(attribute)
    if original is None or hasattr(original, ORIGINAL_ATTRIBUTE):
        return False
    if is_async:

        @functools.wraps(original)
        async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            return await call_async(handler, original, self, args, kwargs)

        wrapper: Any = async_wrapper
    else:

        @functools.wraps(original)
        def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            return call_sync(handler, original, self, args, kwargs)

        wrapper = sync_wrapper
    setattr(wrapper, ORIGINAL_ATTRIBUTE, original)
    setattr(owner, attribute, wrapper)
    return True


def patch_instance(resource: Any, attribute: str, handler: Handler, is_async: bool) -> bool:
    if resource is None:
        return False
    bound = getattr(resource, attribute, None)
    if bound is None or hasattr(bound, ORIGINAL_ATTRIBUTE):
        return False

    def unbound(_self: Any, *args: Any, **kwargs: Any) -> Any:
        return bound(*args, **kwargs)

    if is_async:

        @functools.wraps(bound)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await call_async(handler, unbound, resource, args, kwargs)

        wrapper: Any = async_wrapper
    else:

        @functools.wraps(bound)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return call_sync(handler, unbound, resource, args, kwargs)

        wrapper = sync_wrapper
    setattr(wrapper, ORIGINAL_ATTRIBUTE, bound)
    setattr(resource, attribute, wrapper)
    return True


def unpatch_class(owner: type, attribute: str) -> bool:
    current = owner.__dict__.get(attribute)
    original = getattr(current, ORIGINAL_ATTRIBUTE, None)
    if original is None:
        return False
    setattr(owner, attribute, original)
    return True


class SyncStreamProxy:
    """Wraps a streaming response; ends the span when the stream is exhausted or closed."""

    def __init__(self, stream: Any, span: Span, accumulator: Accumulator) -> None:
        self._stream = stream
        self._span = span
        self._accumulator = accumulator
        self._iterator: Any = None
        self._done = False

    def __iter__(self) -> SyncStreamProxy:
        return self

    def __next__(self) -> Any:
        if self._iterator is None:
            self._iterator = iter(self._stream)
        try:
            event = next(self._iterator)
        except StopIteration:
            self._finish()
            raise
        except BaseException as exc:
            self._finish(exc)
            raise
        safe(self._accumulator.add, event)
        return event

    def __enter__(self) -> SyncStreamProxy:
        enter = getattr(self._stream, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, *exc_info: Any) -> Any:
        self._finish(exc_info[1] if len(exc_info) > 1 else None)
        exit_ = getattr(self._stream, "__exit__", None)
        return exit_(*exc_info) if exit_ is not None else False

    def close(self) -> None:
        self._finish()
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

    def __del__(self) -> None:
        _finish_abandoned(self)

    def _finish(self, exc: BaseException | None = None) -> None:
        if self._done:
            return
        self._done = True
        if exc is not None and not isinstance(exc, GeneratorExit | StopIteration):
            self._span.record_exception(exc)
        safe(self._accumulator.finish, self._span)
        self._span.end()


class AsyncStreamProxy:
    def __init__(self, stream: Any, span: Span, accumulator: Accumulator) -> None:
        self._stream = stream
        self._span = span
        self._accumulator = accumulator
        self._iterator: Any = None
        self._done = False

    def __aiter__(self) -> AsyncStreamProxy:
        return self

    async def __anext__(self) -> Any:
        if self._iterator is None:
            self._iterator = self._stream.__aiter__()
        try:
            event = await self._iterator.__anext__()
        except StopAsyncIteration:
            self._finish()
            raise
        except BaseException as exc:
            self._finish(exc)
            raise
        safe(self._accumulator.add, event)
        return event

    async def __aenter__(self) -> AsyncStreamProxy:
        enter = getattr(self._stream, "__aenter__", None)
        if enter is not None:
            await enter()
        return self

    async def __aexit__(self, *exc_info: Any) -> Any:
        self._finish(exc_info[1] if len(exc_info) > 1 else None)
        exit_ = getattr(self._stream, "__aexit__", None)
        return await exit_(*exc_info) if exit_ is not None else False

    async def close(self) -> None:
        self._finish()
        close = getattr(self._stream, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

    def __del__(self) -> None:
        _finish_abandoned(self)

    def _finish(self, exc: BaseException | None = None) -> None:
        if self._done:
            return
        self._done = True
        if exc is not None and not isinstance(exc, GeneratorExit | StopAsyncIteration):
            self._span.record_exception(exc)
        safe(self._accumulator.finish, self._span)
        self._span.end()


def _finish_abandoned(proxy: Any) -> None:
    """Record a stream the caller stopped reading (e.g. ``break``) without closing it."""
    state = proxy.__dict__
    if state.get("_done", True):
        return
    try:
        state["_span"].set_attribute("agentmesh.stream.abandoned", True)
        proxy._finish()
    except Exception:  # pragma: no cover - finalizers must never raise
        pass
