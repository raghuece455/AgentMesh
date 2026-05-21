import asyncio
import json
import urllib.error

import pytest

from agentmesh.errors import AgentMeshError, ErrorKind
from agentmesh.pricing import estimate_model_cost
from agentmesh.providers import ModelRequest, OllamaProvider, OpenAICompatibleProvider
from agentmesh.types import REDACTED, redact_secrets


class _FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _FakeResponse:
    def __init__(self, payload: dict | str, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = _FakeHeaders(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


def test_openai_compatible_provider_success_extracts_usage_and_request_id(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "id": "chatcmpl_test",
                "model": "gpt-4.1-mini",
                "choices": [{"message": {"content": "hello from provider"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
            {"x-request-id": "req_123"},
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider("https://llm.example/v1", "sk-test_abcdefghijklmnopqrstuvwxyz", "gpt-4.1-mini")

    response = asyncio.run(provider.generate(ModelRequest(prompt="hello")))

    assert response.text == "hello from provider"
    assert response.prompt_tokens == 11
    assert response.completion_tokens == 7
    assert response.raw["request_id"] == "req_123"
    assert captured["authorization"].startswith("Bearer ")
    assert estimate_model_cost("openai-compatible", response.model, response.prompt_tokens, response.completion_tokens).cost_usd > 0


def test_openai_compatible_provider_classifies_rate_limit_timeout_auth_and_malformed(monkeypatch):
    provider = OpenAICompatibleProvider("https://llm.example/v1", "sk-test_abcdefghijklmnopqrstuvwxyz", "gpt-4.1-mini", timeout_seconds=0.01)

    def rate_limited(_request, timeout=None):
        raise urllib.error.HTTPError("https://llm.example/v1", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", rate_limited)
    with pytest.raises(AgentMeshError) as rate_error:
        asyncio.run(provider.generate(ModelRequest(prompt="hello")))
    assert rate_error.value.kind == ErrorKind.RATE_LIMIT
    assert rate_error.value.retryable is True

    def auth_failed(_request, timeout=None):
        raise urllib.error.HTTPError("https://llm.example/v1", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", auth_failed)
    with pytest.raises(AgentMeshError) as auth_error:
        asyncio.run(provider.generate(ModelRequest(prompt="hello")))
    assert auth_error.value.kind == ErrorKind.SECURITY
    assert "sk-test" not in str(auth_error.value)

    def timeout(_request, timeout=None):
        raise TimeoutError("slow")

    monkeypatch.setattr("urllib.request.urlopen", timeout)
    with pytest.raises(AgentMeshError) as timeout_error:
        asyncio.run(provider.generate(ModelRequest(prompt="hello")))
    assert timeout_error.value.kind == ErrorKind.TIMEOUT

    def malformed(_request, timeout=None):
        return _FakeResponse("{not-json")

    monkeypatch.setattr("urllib.request.urlopen", malformed)
    with pytest.raises(AgentMeshError) as malformed_error:
        asyncio.run(provider.generate(ModelRequest(prompt="hello")))
    assert "malformed JSON" in malformed_error.value.message


def test_ollama_provider_success_and_unavailable_are_ci_safe(monkeypatch):
    def fake_urlopen(_request, timeout=None):
        return _FakeResponse({"model": "llama3.1", "response": "local answer", "prompt_eval_count": 5, "eval_count": 3})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OllamaProvider("llama3.1", base_url="http://localhost:11434")

    response = asyncio.run(provider.generate(ModelRequest(prompt="hello local")))

    assert response.text == "local answer"
    assert response.prompt_tokens == 5
    assert response.completion_tokens == 3
    assert estimate_model_cost("ollama", response.model, response.prompt_tokens, response.completion_tokens).status == "local/free"

    def unavailable(_request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    with pytest.raises(AgentMeshError) as unavailable_error:
        asyncio.run(provider.generate(ModelRequest(prompt="hello local")))
    assert unavailable_error.value.kind == ErrorKind.MODEL
    assert unavailable_error.value.retryable is True


def test_redaction_covers_release_security_patterns():
    payload = {
        "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz123456",
        "Cookie": "sessionid=secret-cookie",
        "webhook_secret": "whsec_abcdefghijklmnopqrstuvwxyz",
        "url": "postgres://user:password@example.com/db",
        "text": "password=hunter2 api_key=sk-test_abcdefghijklmnopqrstuvwxyz",
    }

    rendered = json.dumps(redact_secrets(payload))

    assert "abcdefghijklmnopqrstuvwxyz123456" not in rendered
    assert "secret-cookie" not in rendered
    assert "whsec_" not in rendered
    assert "hunter2" not in rendered
    assert REDACTED in rendered
