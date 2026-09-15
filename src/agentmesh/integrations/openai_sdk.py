"""Auto-instrumentation for the official ``openai`` Python SDK.

Covers Chat Completions, Responses, and Embeddings (sync and async, streaming
included). Works with OpenAI and every OpenAI-compatible endpoint (Azure OpenAI,
vLLM, Ollama, Groq, OpenRouter, LiteLLM proxy, ...).

    import agentmesh
    agentmesh.instrument_openai()            # every client in the process
    agentmesh.instrument_openai(my_client)   # or just one client
"""

from __future__ import annotations

from typing import Any

from agentmesh.integrations._common import (
    given,
    patch_class,
    patch_instance,
    to_dict,
    unpatch_class,
)
from agentmesh.sdk import Span, span

_PATCHED: list[tuple[type, str]] = []


def instrument_openai(client: Any = None) -> None:
    """Record a span for every OpenAI API call. Pass a client to instrument only that client."""
    try:
        import openai
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise ImportError("instrument_openai() requires the openai package: pip install openai") from exc

    handlers = {"chat": _ChatHandler(), "responses": _ResponsesHandler(), "embeddings": _EmbeddingsHandler()}
    if client is not None:
        is_async = isinstance(client, openai.AsyncOpenAI)
        resources = {
            "chat": getattr(getattr(client, "chat", None), "completions", None),
            "responses": getattr(client, "responses", None),
            "embeddings": getattr(client, "embeddings", None),
        }
        for key, resource in resources.items():
            patch_instance(resource, "create", handlers[key], is_async)
        return

    from openai.resources.chat.completions import AsyncCompletions, Completions
    from openai.resources.embeddings import AsyncEmbeddings, Embeddings

    targets: list[tuple[type, Any, bool]] = [
        (Completions, handlers["chat"], False),
        (AsyncCompletions, handlers["chat"], True),
        (Embeddings, handlers["embeddings"], False),
        (AsyncEmbeddings, handlers["embeddings"], True),
    ]
    try:
        from openai.resources.responses import AsyncResponses, Responses

        targets += [(Responses, handlers["responses"], False), (AsyncResponses, handlers["responses"], True)]
    except ImportError:  # pragma: no cover - very old SDKs
        pass
    for owner, handler, is_async in targets:
        if patch_class(owner, "create", handler, is_async):
            _PATCHED.append((owner, "create"))


def uninstrument_openai() -> None:
    while _PATCHED:
        owner, attribute = _PATCHED.pop()
        unpatch_class(owner, attribute)


def _provider(resource: Any) -> str:
    client = getattr(resource, "_client", None)
    base_url = str(getattr(client, "base_url", "") or "").lower()
    if "azure" in base_url:
        return "azure.ai.openai"
    if not base_url or "api.openai.com" in base_url:
        return "openai"
    for marker, name in (
        ("groq.com", "groq"),
        ("deepseek", "deepseek"),
        ("mistral.ai", "mistral_ai"),
        ("x.ai", "x_ai"),
        ("perplexity", "perplexity"),
        ("openrouter", "openrouter"),
    ):
        if marker in base_url:
            return name
    if "localhost" in base_url or "127.0.0.1" in base_url:
        return "openai-compatible"
    return "openai"


def _request_attributes(resource: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    reasoning = given(kwargs, "reasoning")
    return {
        "gen_ai.provider.name": _provider(resource),
        "gen_ai.request.model": given(kwargs, "model"),
        "gen_ai.request.temperature": given(kwargs, "temperature"),
        "gen_ai.request.top_p": given(kwargs, "top_p"),
        "gen_ai.request.max_tokens": given(kwargs, "max_completion_tokens")
        or given(kwargs, "max_tokens")
        or given(kwargs, "max_output_tokens"),
        "gen_ai.request.seed": given(kwargs, "seed"),
        "gen_ai.request.stream": kwargs.get("stream") is True,
        "gen_ai.request.reasoning.level": given(kwargs, "reasoning_effort")
        or (reasoning.get("effort") if isinstance(reasoning, dict) else None),
    }


class _ChatHandler:
    def start(self, resource: Any, kwargs: dict[str, Any]) -> Span:
        model = given(kwargs, "model") or "unknown"
        created = span(f"chat {model}", kind="llm", attributes=_request_attributes(resource, kwargs))
        created.attributes["gen_ai.operation.name"] = "chat"
        if _capture():
            created.set_attribute("gen_ai.input.messages", given(kwargs, "messages"))
            created.set_attribute("gen_ai.tool.definitions", given(kwargs, "tools"))
        return created

    def on_response(self, span_: Span, response: Any) -> None:
        data = to_dict(response)
        choices = data.get("choices") or []
        _finish_chat(
            span_,
            model=data.get("model"),
            response_id=data.get("id"),
            usage=data.get("usage") or {},
            messages=[choice.get("message") for choice in choices],
            finish_reasons=[choice.get("finish_reason") for choice in choices if choice.get("finish_reason")],
        )

    def accumulator(self) -> _ChatAccumulator:
        return _ChatAccumulator()


class _ChatAccumulator:
    def __init__(self) -> None:
        self.model: str | None = None
        self.response_id: str | None = None
        self.usage: dict[str, Any] = {}
        self.text: dict[int, list[str]] = {}
        self.tool_calls: dict[int, dict[int, dict[str, Any]]] = {}
        self.finish_reasons: dict[int, str] = {}

    def add(self, chunk: Any) -> None:
        data = to_dict(chunk)
        self.model = data.get("model") or self.model
        self.response_id = data.get("id") or self.response_id
        if data.get("usage"):
            self.usage = data["usage"]
        for choice in data.get("choices") or []:
            index = int(choice.get("index") or 0)
            delta = choice.get("delta") or {}
            if delta.get("content"):
                self.text.setdefault(index, []).append(str(delta["content"]))
            for call in delta.get("tool_calls") or []:
                entry = self.tool_calls.setdefault(index, {}).setdefault(
                    int(call.get("index") or 0),
                    {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
                )
                entry["id"] = call.get("id") or entry["id"]
                function = call.get("function") or {}
                entry["function"]["name"] += function.get("name") or ""
                entry["function"]["arguments"] += function.get("arguments") or ""
            if choice.get("finish_reason"):
                self.finish_reasons[index] = choice["finish_reason"]

    def finish(self, span_: Span) -> None:
        indexes = sorted(set(self.text) | set(self.tool_calls) | set(self.finish_reasons))
        messages = []
        for index in indexes:
            message: dict[str, Any] = {"role": "assistant", "content": "".join(self.text.get(index, []))}
            if index in self.tool_calls:
                message["tool_calls"] = [
                    self.tool_calls[index][position] for position in sorted(self.tool_calls[index])
                ]
            messages.append(message)
        _finish_chat(
            span_,
            model=self.model,
            response_id=self.response_id,
            usage=self.usage,
            messages=messages,
            finish_reasons=[self.finish_reasons[index] for index in indexes if index in self.finish_reasons],
        )


def _finish_chat(
    span_: Span, *, model: Any, response_id: Any, usage: dict[str, Any], messages: list[Any], finish_reasons: list[Any]
) -> None:
    span_.set_attribute("gen_ai.response.model", model)
    span_.set_attribute("gen_ai.response.id", response_id)
    if finish_reasons:
        span_.set_attribute("gen_ai.response.finish_reasons", [str(reason) for reason in finish_reasons])
    if usage:
        span_.set_usage(
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            cache_read_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        )
    if _capture() and messages:
        span_.set_attribute("gen_ai.output.messages", messages)


class _ResponsesHandler:
    def start(self, resource: Any, kwargs: dict[str, Any]) -> Span:
        model = given(kwargs, "model") or "unknown"
        created = span(f"chat {model}", kind="llm", attributes=_request_attributes(resource, kwargs))
        created.attributes["gen_ai.operation.name"] = "chat"
        created.set_attribute("gen_ai.request.previous_response.id", given(kwargs, "previous_response_id"))
        conversation = given(kwargs, "conversation")
        if isinstance(conversation, str):
            created.set_attribute("gen_ai.conversation.id", conversation)
        if _capture():
            created.set_attribute("gen_ai.system_instructions", given(kwargs, "instructions"))
            created.set_attribute("gen_ai.input.messages", given(kwargs, "input"))
            created.set_attribute("gen_ai.tool.definitions", given(kwargs, "tools"))
        return created

    def on_response(self, span_: Span, response: Any) -> None:
        data = to_dict(response)
        usage = data.get("usage") or {}
        span_.set_attribute("gen_ai.response.model", data.get("model"))
        span_.set_attribute("gen_ai.response.id", data.get("id"))
        span_.set_attribute("gen_ai.response.status", data.get("status"))
        if usage:
            span_.set_usage(
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                cache_read_tokens=(usage.get("input_tokens_details") or {}).get("cached_tokens"),
                reasoning_tokens=(usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
            )
        if data.get("status") == "failed" and data.get("error"):
            span_.set_status("error", str((data.get("error") or {}).get("message") or data.get("error")))
        if _capture():
            span_.set_attribute("gen_ai.output.messages", data.get("output"))

    def accumulator(self) -> _ResponsesAccumulator:
        return _ResponsesAccumulator(self)


class _ResponsesAccumulator:
    def __init__(self, handler: _ResponsesHandler) -> None:
        self.handler = handler
        self.final: Any = None

    def add(self, event: Any) -> None:
        data = to_dict(event)
        if data.get("type") in {"response.completed", "response.failed", "response.incomplete"}:
            self.final = data.get("response")

    def finish(self, span_: Span) -> None:
        if self.final is not None:
            self.handler.on_response(span_, self.final)


class _EmbeddingsHandler:
    def start(self, resource: Any, kwargs: dict[str, Any]) -> Span:
        model = given(kwargs, "model") or "unknown"
        created = span(f"embeddings {model}", kind="embedding", attributes=_request_attributes(resource, kwargs))
        created.set_attribute(
            "gen_ai.request.encoding_formats",
            [given(kwargs, "encoding_format")] if given(kwargs, "encoding_format") else None,
        )
        return created

    def on_response(self, span_: Span, response: Any) -> None:
        data = to_dict(response)
        usage = data.get("usage") or {}
        span_.set_attribute("gen_ai.response.model", data.get("model"))
        span_.set_usage(usage.get("prompt_tokens"), 0)
        vectors = data.get("data") or []
        if vectors and isinstance(vectors[0], dict) and isinstance(vectors[0].get("embedding"), list):
            span_.set_attribute("gen_ai.embeddings.dimension.count", len(vectors[0]["embedding"]))

    def accumulator(self) -> Any:  # embeddings never stream
        raise NotImplementedError


def _capture() -> bool:
    from agentmesh.sdk import _capture_content

    return _capture_content()


__all__ = ["instrument_openai", "uninstrument_openai"]
