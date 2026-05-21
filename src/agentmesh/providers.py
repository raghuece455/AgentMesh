from __future__ import annotations

import asyncio
import json
import socket
import urllib.parse
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from agentmesh.errors import AgentMeshError, ErrorKind
from agentmesh.types import JsonObject, safe_json


@dataclass(slots=True)
class ModelRequest:
    prompt: str
    system: str | None = None
    model: str | None = None
    temperature: float = 0.2
    top_p: float | None = None
    max_tokens: int | None = None
    trace_id: str = ""
    metadata: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class ModelResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    raw: JsonObject = field(default_factory=dict)

    def to_json(self) -> JsonObject:
        return {
            "text": self.text,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "raw": self.raw,
        }


class ModelProvider(Protocol):
    name: str

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError


def estimate_tokens(text: str) -> int:
    # ~4 characters per token for English prose; better than word-count for
    # code, JSON, and special characters which tokenize more finely.
    return max(1, len(text) // 4)


class MockModelProvider:
    name = "mock"

    def __init__(self, responses: Sequence[str] | None = None, fail_first: bool = False) -> None:
        self.responses = list(responses or [])
        self.fail_first = fail_first
        self.calls = 0
        self._lock = asyncio.Lock()

    async def generate(self, request: ModelRequest) -> ModelResponse:
        async with self._lock:
            self.calls += 1
            if self.fail_first and self.calls == 1:
                raise AgentMeshError("Mock provider configured to fail first call", ErrorKind.MODEL, retryable=True)
            if self.responses:
                text = self.responses.pop(0)
            else:
                text = f"Mock response to: {request.prompt[:160]}"
        return ModelResponse(
            text=text,
            model=request.model or "mock-model",
            prompt_tokens=estimate_tokens(request.prompt),
            completion_tokens=estimate_tokens(text),
            raw={"provider": "mock"},
        )


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return await asyncio.to_thread(self._generate_sync, request)

    def _generate_sync(self, request: ModelRequest) -> ModelResponse:
        messages: list[JsonObject] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        payload = {
            "model": request.model or self.model,
            "messages": messages,
            "temperature": request.temperature,
        }
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        body = json.dumps(payload).encode("utf-8")
        decoded = _post_json(
            f"{self.base_url}/chat/completions",
            body,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            self.timeout_seconds,
        )
        choice = decoded.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = decoded.get("usage", {})
        raw = safe_json(decoded) if isinstance(decoded, dict) else {}
        return ModelResponse(
            text=str(message.get("content", "")),
            model=str(decoded.get("model", request.model or self.model)),
            prompt_tokens=int(usage.get("prompt_tokens", estimate_tokens(request.prompt))),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            raw=raw if isinstance(raw, dict) else {},
        )


class VLLMProvider(OpenAICompatibleProvider):
    name = "vllm"

    def __init__(self, model: str, base_url: str = "http://localhost:8000/v1", api_key: str = "EMPTY") -> None:
        super().__init__(base_url=base_url, api_key=api_key, model=model)


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout_seconds: float = 120.0) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return await asyncio.to_thread(self._generate_sync, request)

    def _generate_sync(self, request: ModelRequest) -> ModelResponse:
        prompt = request.prompt if request.system is None else f"{request.system}\n\n{request.prompt}"
        body = json.dumps({"model": request.model or self.model, "prompt": prompt, "stream": False}).encode("utf-8")
        decoded = _post_json(
            f"{self.base_url}/api/generate",
            body,
            {"Content-Type": "application/json"},
            self.timeout_seconds,
        )
        text = str(decoded.get("response", ""))
        prompt_tokens = int(decoded.get("prompt_eval_count", estimate_tokens(prompt)))
        completion_tokens = int(decoded.get("eval_count", estimate_tokens(text)))
        return ModelResponse(
            text=text,
            model=str(decoded.get("model", request.model or self.model)),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=safe_json(decoded) if isinstance(decoded, dict) else {},
        )


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return await asyncio.to_thread(self._generate_sync, request)

    def _generate_sync(self, request: ModelRequest) -> ModelResponse:
        payload: JsonObject = {
            "model": request.model or self.model,
            "max_tokens": request.max_tokens or 1024,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.system:
            payload["system"] = request.system
        decoded = _post_json(
            f"{self.base_url}/v1/messages",
            json.dumps(payload).encode("utf-8"),
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            self.timeout_seconds,
        )
        content = decoded.get("content", [])
        text = ""
        if isinstance(content, list):
            text = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        usage = decoded.get("usage", {}) if isinstance(decoded.get("usage", {}), dict) else {}
        return ModelResponse(
            text=text,
            model=str(decoded.get("model", request.model or self.model)),
            prompt_tokens=int(usage.get("input_tokens", estimate_tokens(request.prompt))),
            completion_tokens=int(usage.get("output_tokens", estimate_tokens(text))),
            raw=safe_json(decoded) if isinstance(decoded, dict) else {},
        )


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-pro",
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return await asyncio.to_thread(self._generate_sync, request)

    def _generate_sync(self, request: ModelRequest) -> ModelResponse:
        prompt = request.prompt if request.system is None else f"{request.system}\n\n{request.prompt}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": request.temperature},
        }
        if request.top_p is not None:
            payload["generationConfig"]["topP"] = request.top_p
        if request.max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = request.max_tokens
        query = urllib.parse.urlencode({"key": self.api_key})
        decoded = _post_json(
            f"{self.base_url}/v1beta/models/{request.model or self.model}:generateContent?{query}",
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"},
            self.timeout_seconds,
        )
        candidates = decoded.get("candidates", []) if isinstance(decoded, dict) else []
        text = ""
        if candidates and isinstance(candidates[0], dict):
            content = candidates[0].get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            if isinstance(parts, list):
                text = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        usage = decoded.get("usageMetadata", {}) if isinstance(decoded.get("usageMetadata", {}), dict) else {}
        return ModelResponse(
            text=text,
            model=request.model or self.model,
            prompt_tokens=int(usage.get("promptTokenCount", estimate_tokens(prompt))),
            completion_tokens=int(usage.get("candidatesTokenCount", estimate_tokens(text))),
            raw=safe_json(decoded) if isinstance(decoded, dict) else {},
        )


def _post_json(url: str, body: bytes, headers: dict[str, str], timeout_seconds: float) -> JsonObject:
    http_request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw_data = response.read().decode("utf-8")
            request_id = (
                response.headers.get("x-request-id")
                or response.headers.get("openai-request-id")
                or response.headers.get("request-id")
            )
    except urllib.error.HTTPError as exc:
        kind = ErrorKind.RATE_LIMIT if exc.code == 429 else ErrorKind.SECURITY if exc.code in {401, 403} else ErrorKind.MODEL
        retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
        raise AgentMeshError(f"Provider HTTP {exc.code}: {exc.reason}", kind, {"status_code": exc.code}, retryable=retryable) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise AgentMeshError("Provider request timed out", ErrorKind.TIMEOUT, {}, retryable=True) from exc
    except urllib.error.URLError as exc:
        raise AgentMeshError(str(exc.reason), ErrorKind.MODEL, {}, retryable=True) from exc
    except Exception as exc:
        raise AgentMeshError(str(exc), ErrorKind.MODEL, retryable=True) from exc
    try:
        decoded = json.loads(raw_data)
    except json.JSONDecodeError as exc:
        raise AgentMeshError("Provider returned malformed JSON", ErrorKind.MODEL, retryable=True) from exc
    if not isinstance(decoded, dict):
        raise AgentMeshError("Provider returned non-object JSON", ErrorKind.MODEL, retryable=True)
    if request_id:
        decoded.setdefault("request_id", request_id)
    return decoded
