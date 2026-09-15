"""Model pricing and cost estimation.

Prices are expressed in USD per million tokens (MTok), the unit every major
provider publishes. Resolution order for a (provider, model) pair:

1. ``AGENTMESH_PRICING_JSON`` inline overrides (highest priority)
2. local/self-hosted providers (Ollama, vLLM, mock, ...) are always free
3. the synced price file (``agentmesh pricing sync``), if present
4. the built-in table below

Token semantics follow the OpenTelemetry GenAI conventions: ``prompt_tokens``
is the *total* input including cache reads and cache writes, and
``completion_tokens`` already includes reasoning tokens.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import threading
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from agentmesh.types import JsonObject, utc_now

LITELLM_PRICES_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
DEFAULT_PRICING_FILE = ".agentmesh/pricing.json"

LOCAL_PROVIDERS = {"ollama", "vllm", "mock", "lmstudio", "llamacpp", "llama.cpp", "local", "localai", "tgi"}

PROVIDER_ALIASES = {
    "openai-compatible": "openai",
    "azure-openai": "openai",
    "azure.ai.openai": "openai",
    "azure": "openai",
    "gcp.gemini": "gemini",
    "gcp.vertex_ai": "gemini",
    "gcp.gen_ai": "gemini",
    "google": "gemini",
    "vertex_ai": "gemini",
    "aws.bedrock": "bedrock",
}


@dataclass(frozen=True, slots=True)
class PricingRule:
    provider: str
    model: str
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None
    status: str = "estimated"
    notes: str = ""
    source: str = "builtin"

    def to_json(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CostEstimate:
    cost_usd: float
    status: str
    source: str
    notes: str

    def to_json(self) -> JsonObject:
        return {
            "cost_usd": self.cost_usd,
            "cost_status": self.status,
            "cost_source": self.source,
            "cost_notes": self.notes,
        }


_CLAUDE_NOTE = "Claude API global list price; batch, data residency and cloud-partner regional pricing differ."
_OPENAI_NOTE = "OpenAI standard-tier list price; run `agentmesh pricing sync` to refresh."
_GEMINI_NOTE = "Gemini API paid-tier list price."


def _claude(model: str, base: float, output: float, cache_read: float | None = None) -> PricingRule:
    return PricingRule(
        "*", model, base, output, cache_read if cache_read is not None else base * 0.1, base * 1.25, notes=_CLAUDE_NOTE
    )


DEFAULT_PRICING: tuple[PricingRule, ...] = (
    # Anthropic, from platform.claude.com/docs/en/about-claude/pricing (checked 2026-09-11).
    _claude("claude-fable-5-1", 10.0, 50.0, cache_read=0.25),
    _claude("claude-fable-5", 10.0, 50.0),
    _claude("claude-opus-5", 5.0, 25.0),
    _claude("claude-opus-4-8", 5.0, 25.0),
    _claude("claude-opus-4-7", 5.0, 25.0),
    _claude("claude-opus-4-6", 5.0, 25.0),
    _claude("claude-opus-4-5", 5.0, 25.0),
    _claude("claude-opus-4-1", 15.0, 75.0),
    _claude("claude-opus-4", 15.0, 75.0),
    _claude("claude-sonnet-5", 2.0, 10.0),
    _claude("claude-sonnet-4-6", 3.0, 15.0),
    _claude("claude-sonnet-4-5", 3.0, 15.0),
    _claude("claude-sonnet-4", 3.0, 15.0),
    _claude("claude-haiku-4-5", 1.0, 5.0),
    _claude("claude-3-5-haiku", 0.8, 4.0),
    # Google Gemini, from ai.google.dev/gemini-api/docs/pricing (checked 2026-09-11).
    PricingRule("*", "gemini-2.5-pro", 1.25, 10.0, 0.125, notes=_GEMINI_NOTE + " Prompts over 200k tokens cost more."),
    PricingRule("*", "gemini-2.5-flash", 0.30, 2.50, 0.03, notes=_GEMINI_NOTE),
    PricingRule("*", "gemini-2.5-flash-lite", 0.10, 0.40, 0.01, notes=_GEMINI_NOTE),
    # OpenAI.
    PricingRule("*", "gpt-5", 1.25, 10.0, 0.125, notes=_OPENAI_NOTE),
    PricingRule("*", "gpt-5-mini", 0.25, 2.0, 0.025, notes=_OPENAI_NOTE),
    PricingRule("*", "gpt-5-nano", 0.05, 0.40, 0.005, notes=_OPENAI_NOTE),
    PricingRule("*", "gpt-4.1", 2.0, 8.0, 0.50, notes=_OPENAI_NOTE),
    PricingRule("*", "gpt-4.1-mini", 0.40, 1.60, 0.10, notes=_OPENAI_NOTE),
    PricingRule("*", "gpt-4.1-nano", 0.10, 0.40, 0.025, notes=_OPENAI_NOTE),
    PricingRule("*", "gpt-4o", 2.50, 10.0, 1.25, notes=_OPENAI_NOTE),
    PricingRule("*", "gpt-4o-mini", 0.15, 0.60, 0.075, notes=_OPENAI_NOTE),
    PricingRule("*", "o3", 2.0, 8.0, 0.50, notes=_OPENAI_NOTE),
    PricingRule("*", "o4-mini", 1.10, 4.40, 0.275, notes=_OPENAI_NOTE),
)


def normalize_provider(provider: str | None) -> str:
    name = (provider or "unknown").strip().lower()
    return PROVIDER_ALIASES.get(name, name)


def normalize_model_name(model: str | None) -> str:
    """Reduce vendor-specific model identifiers to a comparable base name.

    ``us.anthropic.claude-sonnet-4-5-20250929-v1:0`` -> ``claude-sonnet-4-5``
    ``models/gemini-2.5-pro`` -> ``gemini-2.5-pro``
    ``gpt-4o-2024-08-06`` -> ``gpt-4o``
    """
    name = (model or "").strip().lower()
    if not name:
        return "unknown"
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    name = re.sub(r"^(?:[a-z]{2,6}\.)?anthropic\.", "", name)
    name = name.split("@", 1)[0]
    # Only Bedrock-style "-v1:0" suffixes; "-v3" is part of names like "deepseek-v3".
    name = re.sub(r"-v\d+:\d+$", "", name)
    name = re.sub(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$", "", name)
    name = re.sub(r"-latest$", "", name)
    if name.startswith("claude"):
        name = name.replace(".", "-")
    return name


def pricing_for(provider: str | None, model: str | None) -> PricingRule | None:
    provider_name = normalize_provider(provider)
    model_name = normalize_model_name(model)
    overrides, synced = _configured_rules()
    for rule in _match(overrides, provider_name, model_name):
        return rule
    if provider_name in LOCAL_PROVIDERS:
        return PricingRule(
            provider_name, "*", 0.0, 0.0, 0.0, 0.0, "local/free", f"{provider_name} is treated as local infrastructure."
        )
    for rules in (synced, DEFAULT_PRICING):
        for rule in _match(rules, provider_name, model_name):
            return rule
    return None


def estimate_model_cost(
    provider: str | None,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> CostEstimate:
    """Estimate the USD cost of one model call.

    ``cached_tokens`` (cache reads) and ``cache_write_tokens`` are subsets of
    ``prompt_tokens``; ``reasoning_tokens`` is a subset of ``completion_tokens``
    and is accepted only for signature compatibility.
    """
    del reasoning_tokens
    rule = pricing_for(provider, model)
    if rule is None:
        return CostEstimate(
            cost_usd=0.0,
            status="unknown",
            source="pricing_config",
            notes=f"No pricing configured for provider={provider!r}, model={model!r}. Run `agentmesh pricing sync` or set AGENTMESH_PRICING_JSON.",
        )
    cache_read = max(int(cached_tokens or 0), 0)
    cache_write = max(int(cache_write_tokens or 0), 0)
    uncached = max(int(prompt_tokens or 0) - cache_read - cache_write, 0)
    cache_read_rate = rule.input_per_mtok if rule.cache_read_per_mtok is None else rule.cache_read_per_mtok
    cache_write_rate = rule.input_per_mtok if rule.cache_write_per_mtok is None else rule.cache_write_per_mtok
    cost = (
        uncached * rule.input_per_mtok
        + cache_read * cache_read_rate
        + cache_write * cache_write_rate
        + max(int(completion_tokens or 0), 0) * rule.output_per_mtok
    ) / 1_000_000
    return CostEstimate(round(cost, 10), rule.status, f"pricing:{rule.source}", rule.notes)


def list_pricing_rules() -> list[JsonObject]:
    overrides, synced = _configured_rules()
    return [rule.to_json() for rule in (*overrides, *synced, *DEFAULT_PRICING)]


def convert_litellm_prices(data: object) -> list[JsonObject]:
    """Convert LiteLLM's community price list into AgentMesh pricing rules."""
    if not isinstance(data, dict):
        raise ValueError("LiteLLM price data must be a JSON object")
    rules: dict[str, JsonObject] = {}
    # Prefer bare model keys over provider-routed ones (e.g. "gpt-4o" over "azure/gpt-4o").
    for key in sorted(data, key=lambda item: ("/" in item, item)):
        entry = data[key]
        if not isinstance(entry, dict) or entry.get("mode") not in {"chat", "completion", "responses"}:
            continue
        input_cost = entry.get("input_cost_per_token")
        output_cost = entry.get("output_cost_per_token")
        if not isinstance(input_cost, int | float) or not isinstance(output_cost, int | float):
            continue
        model = normalize_model_name(key)
        if model in rules:
            continue
        rule: JsonObject = {
            "provider": "*",
            "model": model,
            "input_per_mtok": round(float(input_cost) * 1_000_000, 6),
            "output_per_mtok": round(float(output_cost) * 1_000_000, 6),
            "status": "estimated",
            "notes": f"LiteLLM community price list ({entry.get('litellm_provider', 'unknown')})",
            "source": "litellm",
        }
        if isinstance(entry.get("cache_read_input_token_cost"), int | float):
            rule["cache_read_per_mtok"] = round(float(entry["cache_read_input_token_cost"]) * 1_000_000, 6)
        if isinstance(entry.get("cache_creation_input_token_cost"), int | float):
            rule["cache_write_per_mtok"] = round(float(entry["cache_creation_input_token_cost"]) * 1_000_000, 6)
        rules[model] = rule
    return list(rules.values())


def sync_pricing(
    url: str = LITELLM_PRICES_URL, dest: str | Path | None = None, timeout_seconds: float = 30.0
) -> JsonObject:
    """Download community prices and write them to the local pricing file."""
    request = urllib.request.Request(url, headers={"User-Agent": "agentmesh-pricing-sync"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    rules = convert_litellm_prices(data)
    path = Path(dest or pricing_file_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source": url, "synced_at": utc_now(), "rules": rules}, indent=2), encoding="utf-8")
    _cache.clear()
    return {"path": str(path), "rules": len(rules), "source": url}


def pricing_file_path() -> Path:
    return Path(os.getenv("AGENTMESH_PRICING_FILE", DEFAULT_PRICING_FILE))


def _match(rules: tuple[PricingRule, ...], provider: str, model: str):
    for exact in (True, False):
        for rule in rules:
            if rule.provider not in {"*", provider}:
                continue
            pattern = rule.model.lower()
            if exact and pattern == model:
                yield rule
            elif not exact and any(char in pattern for char in "*?[") and fnmatch.fnmatch(model, pattern):
                yield rule


_cache: dict[tuple[object, ...], tuple[tuple[PricingRule, ...], tuple[PricingRule, ...]]] = {}
_cache_lock = threading.Lock()


def _configured_rules() -> tuple[tuple[PricingRule, ...], tuple[PricingRule, ...]]:
    inline = os.getenv("AGENTMESH_PRICING_JSON") or ""
    path = pricing_file_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    key = (inline, str(path), mtime)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
    override_payload = _loads(inline)
    if override_payload is None and inline and Path(inline).is_file():
        override_payload = _loads(Path(inline).read_text(encoding="utf-8-sig"))
    if isinstance(override_payload, dict) and isinstance(override_payload.get("rules"), list):
        override_payload = override_payload["rules"]
    overrides = tuple(_parse_rules(override_payload, "override"))
    synced: tuple[PricingRule, ...] = ()
    if mtime is not None:
        payload = _loads(path.read_text(encoding="utf-8-sig"))
        synced = tuple(_parse_rules(payload.get("rules") if isinstance(payload, dict) else payload, "synced"))
    with _cache_lock:
        _cache.clear()
        _cache[key] = (overrides, synced)
    return overrides, synced


def _loads(text: str) -> object:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_rules(raw: object, default_source: str) -> list[PricingRule]:
    if isinstance(raw, dict):
        # Shorthand: {"my-model": {"prompt": 0.002, "completion": 0.006}} in USD per 1K tokens,
        # or {"my-model": {"input_per_mtok": 2, "output_per_mtok": 6}}.
        raw = [
            {"model": model, **({"prompt_per_1k": value.get("prompt", 0), "completion_per_1k": value.get("completion", 0)} if "input_per_mtok" not in value else value)}
            for model, value in raw.items()
            if isinstance(value, dict)
        ]
    if not isinstance(raw, list):
        return []
    rules: list[PricingRule] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            if "input_per_mtok" in item:
                input_rate = float(item["input_per_mtok"])
                output_rate = float(item.get("output_per_mtok", 0))
                cache_read = item.get("cache_read_per_mtok")
                cache_write = item.get("cache_write_per_mtok")
            else:
                # Backwards compatible with the v0.3 per-1k format.
                input_rate = float(item.get("prompt_per_1k", 0)) * 1000
                output_rate = float(item.get("completion_per_1k", 0)) * 1000
                cache_read = float(item["cached_per_1k"]) * 1000 if "cached_per_1k" in item else None
                cache_write = None
            provider = str(item.get("provider", "*"))
            rules.append(
                PricingRule(
                    provider="*" if provider == "*" else normalize_provider(provider),
                    model=str(item.get("model", "*")).lower(),
                    input_per_mtok=input_rate,
                    output_per_mtok=output_rate,
                    cache_read_per_mtok=float(cache_read) if cache_read is not None else None,
                    cache_write_per_mtok=float(cache_write) if cache_write is not None else None,
                    status=str(item.get("status", "estimated")),
                    notes=str(item.get("notes", f"configured ({default_source})")),
                    source=str(item.get("source", default_source)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rules
