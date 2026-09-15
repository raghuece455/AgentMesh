"""Auto-instrumentation for the official ``anthropic`` Python SDK.

Covers ``messages.create`` (sync/async, ``stream=True``) and the
``messages.stream(...)`` helper, including prompt-cache token accounting.
Also works for ``AnthropicBedrock`` and ``AnthropicVertex`` clients.

    import agentmesh
    agentmesh.instrument_anthropic()
"""

from __future__ import annotations

import functools
import json
from typing import Any

from agentmesh.integrations._common import (
    ORIGINAL_ATTRIBUTE,
    given,
    patch_class,
    patch_instance,
    safe,
    to_dict,
    unpatch_class,
)
from agentmesh.sdk import Span, span

_PATCHED: list[tuple[type, str]] = []


def instrument_anthropic(client: Any = None) -> None:
    """Record a span for every Claude Messages API call. Pass a client to instrument only that client."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise ImportError("instrument_anthropic() requires the anthropic package: pip install anthropic") from exc

    handler = _MessagesHandler()
    if client is not None:
        is_async = isinstance(client, anthropic.AsyncAnthropic) or type(client).__name__.startswith("Async")
        resource = getattr(client, "messages", None)
        patch_instance(resource, "create", handler, is_async)
        _patch_stream_instance(resource, handler, is_async)
        return

    from anthropic.resources.messages import AsyncMessages, Messages

    for owner, is_async in ((Messages, False), (AsyncMessages, True)):
        if patch_class(owner, "create", handler, is_async):
            _PATCHED.append((owner, "create"))
        if _patch_stream_class(owner, handler, is_async):
            _PATCHED.append((owner, "stream"))


def uninstrument_anthropic() -> None:
    while _PATCHED:
        owner, attribute = _PATCHED.pop()
        unpatch_class(owner, attribute)


def _provider(resource: Any) -> str:
    client_name = type(getattr(resource, "_client", None)).__name__
    if "Bedrock" in client_name:
        return "aws.bedrock"
    if "Vertex" in client_name:
        return "gcp.vertex_ai"
    return "anthropic"


class _MessagesHandler:
    def start(self, resource: Any, kwargs: dict[str, Any]) -> Span:
        model = given(kwargs, "model") or "unknown"
        thinking = given(kwargs, "thinking")
        created = span(
            f"chat {model}",
            kind="llm",
            attributes={
                "gen_ai.provider.name": _provider(resource),
                "gen_ai.request.model": model,
                "gen_ai.request.max_tokens": given(kwargs, "max_tokens"),
                "gen_ai.request.temperature": given(kwargs, "temperature"),
                "gen_ai.request.top_p": given(kwargs, "top_p"),
                "gen_ai.request.top_k": given(kwargs, "top_k"),
                "gen_ai.request.stream": kwargs.get("stream") is True,
                "gen_ai.request.stop_sequences": given(kwargs, "stop_sequences"),
                "gen_ai.request.reasoning.level": thinking.get("type") if isinstance(thinking, dict) else None,
            },
        )
        if _capture():
            created.set_attribute("gen_ai.system_instructions", given(kwargs, "system"))
            created.set_attribute("gen_ai.input.messages", given(kwargs, "messages"))
            created.set_attribute("gen_ai.tool.definitions", given(kwargs, "tools"))
        return created

    def on_response(self, span_: Span, response: Any) -> None:
        data = to_dict(response)
        usage = data.get("usage") or {}
        span_.set_attribute("gen_ai.response.model", data.get("model"))
        span_.set_attribute("gen_ai.response.id", data.get("id"))
        if data.get("stop_reason"):
            span_.set_attribute("gen_ai.response.finish_reasons", [str(data["stop_reason"])])
        if usage:
            cache_read = int(usage.get("cache_read_input_tokens") or 0)
            cache_write = int(usage.get("cache_creation_input_tokens") or 0)
            # Anthropic reports input_tokens *excluding* cache reads/writes; the
            # OTel GenAI convention wants the total.
            span_.set_usage(
                int(usage.get("input_tokens") or 0) + cache_read + cache_write,
                usage.get("output_tokens"),
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            )
        if _capture() and data.get("content") is not None:
            span_.set_attribute("gen_ai.output.messages", [{"role": "assistant", "content": data.get("content")}])

    def accumulator(self) -> _EventAccumulator:
        return _EventAccumulator(self)


class _EventAccumulator:
    def __init__(self, handler: _MessagesHandler) -> None:
        self.handler = handler
        self.message: dict[str, Any] = {}
        self.usage: dict[str, Any] = {}
        self.blocks: dict[int, dict[str, Any]] = {}

    def add(self, event: Any) -> None:
        data = to_dict(event)
        kind = data.get("type")
        if kind == "message_start":
            message = data.get("message") or {}
            self.message = {"id": message.get("id"), "model": message.get("model")}
            self.usage.update(message.get("usage") or {})
        elif kind == "content_block_start":
            self.blocks[int(data.get("index") or 0)] = dict(data.get("content_block") or {})
        elif kind == "content_block_delta":
            block = self.blocks.setdefault(int(data.get("index") or 0), {"type": "text"})
            delta = data.get("delta") or {}
            for delta_type, field in (
                ("text_delta", "text"),
                ("input_json_delta", "partial_json"),
                ("thinking_delta", "thinking"),
            ):
                if delta.get("type") == delta_type:
                    block[field] = str(block.get(field) or "") + str(delta.get(field) or "")
        elif kind == "message_delta":
            delta = data.get("delta") or {}
            if delta.get("stop_reason"):
                self.message["stop_reason"] = delta["stop_reason"]
            self.usage.update({key: value for key, value in (data.get("usage") or {}).items() if value is not None})

    def finish(self, span_: Span) -> None:
        content = []
        for index in sorted(self.blocks):
            block = self.blocks[index]
            if block.get("type") == "tool_use" and "partial_json" in block:
                try:
                    block["input"] = json.loads(block.pop("partial_json") or "{}")
                except json.JSONDecodeError:
                    pass
            content.append(block)
        self.handler.on_response(span_, {**self.message, "content": content, "usage": self.usage})


def _patch_stream_class(owner: type, handler: _MessagesHandler, is_async: bool) -> bool:
    original = owner.__dict__.get("stream")
    if original is None or hasattr(original, ORIGINAL_ATTRIBUTE):
        return False

    @functools.wraps(original)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _start_stream(handler, lambda: original(self, *args, **kwargs), self, kwargs, is_async)

    setattr(wrapper, ORIGINAL_ATTRIBUTE, original)
    owner.stream = wrapper  # type: ignore[attr-defined]
    return True


def _patch_stream_instance(resource: Any, handler: _MessagesHandler, is_async: bool) -> None:
    bound = getattr(resource, "stream", None)
    if bound is None or hasattr(bound, ORIGINAL_ATTRIBUTE):
        return

    @functools.wraps(bound)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _start_stream(handler, lambda: bound(*args, **kwargs), resource, kwargs, is_async)

    setattr(wrapper, ORIGINAL_ATTRIBUTE, bound)
    resource.stream = wrapper


def _start_stream(
    handler: _MessagesHandler, open_manager: Any, resource: Any, kwargs: dict[str, Any], is_async: bool
) -> Any:
    created = handler.start(resource, {**kwargs, "stream": True})
    try:
        manager = open_manager()
    except BaseException as exc:
        created.record_exception(exc)
        created.end()
        raise
    return _AsyncManagerProxy(manager, created, handler) if is_async else _ManagerProxy(manager, created, handler)


class _ManagerProxy:
    def __init__(self, manager: Any, span_: Span, handler: _MessagesHandler) -> None:
        self._manager = manager
        self._span = span_
        self._handler = handler
        self._stream: Any = None

    def __enter__(self) -> Any:
        try:
            self._stream = self._manager.__enter__()
        except BaseException as exc:
            self._span.record_exception(exc)
            self._span.end()
            raise
        return self._stream

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> Any:
        safe(_finish_stream, self._span, self._handler, self._stream, exc)
        return self._manager.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)


class _AsyncManagerProxy(_ManagerProxy):
    async def __aenter__(self) -> Any:
        try:
            self._stream = await self._manager.__aenter__()
        except BaseException as exc:
            self._span.record_exception(exc)
            self._span.end()
            raise
        return self._stream

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> Any:
        safe(_finish_stream, self._span, self._handler, self._stream, exc)
        return await self._manager.__aexit__(exc_type, exc, tb)


def _finish_stream(span_: Span, handler: _MessagesHandler, stream: Any, exc: BaseException | None) -> None:
    if exc is not None and not isinstance(exc, GeneratorExit):
        span_.record_exception(exc)
    snapshot = None
    try:
        snapshot = stream.current_message_snapshot if stream is not None else None
    except (AssertionError, AttributeError):
        snapshot = None
    if snapshot is not None:
        safe(handler.on_response, span_, snapshot)
    span_.end()


def _capture() -> bool:
    from agentmesh.sdk import _capture_content

    return _capture_content()


__all__ = ["instrument_anthropic", "uninstrument_anthropic"]
