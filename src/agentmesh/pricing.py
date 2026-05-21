from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass

from agentmesh.types import JsonObject


@dataclass(frozen=True, slots=True)
class PricingRule:
    provider: str
    model: str
    prompt_per_1k: float
    completion_per_1k: float
    cached_per_1k: float = 0.0
    reasoning_per_1k: float = 0.0
    status: str = "estimated"
    notes: str = ""


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


DEFAULT_PRICING: tuple[PricingRule, ...] = (
    PricingRule("openai-compatible", "gpt-4.1-mini*", 0.0004, 0.0016, cached_per_1k=0.0001),
    PricingRule("openai-compatible", "gpt-4.1*", 0.0020, 0.0080, cached_per_1k=0.0005, reasoning_per_1k=0.0020),
    PricingRule("openai-compatible", "gpt-4o-mini*", 0.00015, 0.0006, cached_per_1k=0.000075),
    PricingRule("openai-compatible", "gpt-4o*", 0.0025, 0.0100, cached_per_1k=0.00125),
    PricingRule("anthropic", "claude*", 0.0030, 0.0150),
    PricingRule("gemini", "gemini*", 0.00125, 0.0050),
    PricingRule("vllm", "*", 0.0, 0.0, status="local/free", notes="vLLM is treated as local infrastructure unless configured."),
    PricingRule("ollama", "*", 0.0, 0.0, status="local/free", notes="Ollama is local by default."),
    PricingRule("mock", "*", 0.0, 0.0, status="local/free", notes="Mock provider has no external model cost."),
)


def estimate_model_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> CostEstimate:
    rule = _find_rule(provider, model)
    if rule is None:
        return CostEstimate(
            cost_usd=0.0,
            status="unknown",
            source="pricing_config",
            notes=f"No pricing configured for provider={provider!r}, model={model!r}.",
        )
    cost = (
        (prompt_tokens * rule.prompt_per_1k)
        + (completion_tokens * rule.completion_per_1k)
        + (cached_tokens * rule.cached_per_1k)
        + (reasoning_tokens * rule.reasoning_per_1k)
    ) / 1000.0
    return CostEstimate(round(cost, 8), rule.status, "pricing_config", rule.notes)


def _find_rule(provider: str, model: str) -> PricingRule | None:
    provider_name = provider or "unknown"
    model_name = model or "unknown"
    for rule in _pricing_rules():
        if rule.provider == provider_name and fnmatch.fnmatch(model_name.lower(), rule.model.lower()):
            return rule
    return None


def _pricing_rules() -> tuple[PricingRule, ...]:
    config = os.getenv("AGENTMESH_PRICING_JSON")
    if not config:
        return DEFAULT_PRICING
    try:
        raw = json.loads(config)
    except json.JSONDecodeError:
        return DEFAULT_PRICING
    if not isinstance(raw, list):
        return DEFAULT_PRICING
    rules: list[PricingRule] = list(DEFAULT_PRICING)
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            rules.insert(
                0,
                PricingRule(
                    provider=str(item["provider"]),
                    model=str(item.get("model", "*")),
                    prompt_per_1k=float(item.get("prompt_per_1k", 0)),
                    completion_per_1k=float(item.get("completion_per_1k", 0)),
                    cached_per_1k=float(item.get("cached_per_1k", 0)),
                    reasoning_per_1k=float(item.get("reasoning_per_1k", 0)),
                    status=str(item.get("status", "estimated")),
                    notes=str(item.get("notes", "configured from AGENTMESH_PRICING_JSON")),
                ),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(rules)
