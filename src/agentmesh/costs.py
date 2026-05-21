from __future__ import annotations

from dataclasses import dataclass

from agentmesh.storage import SQLiteStore
from agentmesh.types import JsonObject


@dataclass(slots=True)
class CostSummary:
    trace_id: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    model_calls: int
    by_agent: dict[str, JsonObject]
    by_model: dict[str, JsonObject]

    def to_json(self) -> JsonObject:
        return {
            "trace_id": self.trace_id,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "model_calls": self.model_calls,
            "by_agent": self.by_agent,
            "by_model": self.by_model,
        }


class CostTracker:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def summarize(self, trace_id: str | None = None) -> CostSummary:
        if hasattr(self.store, "list_model_calls"):
            calls = self.store.list_model_calls(trace_id, 10_000)
            if calls:
                return _summarize_model_calls(trace_id, calls)
        events = self.store.list_events(trace_id) if trace_id else self.store.list_all_events()
        prompt_tokens = 0
        completion_tokens = 0
        cost_usd = 0.0
        model_calls = 0
        by_agent: dict[str, JsonObject] = {}
        by_model: dict[str, JsonObject] = {}
        for event in events:
            if event.get("event_type") != "model.response":
                continue
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            model_calls += 1
            prompt = _int(payload.get("prompt_tokens"))
            completion = _int(payload.get("completion_tokens"))
            cost = _float(payload.get("estimated_cost") or payload.get("cost_usd"))
            model = str(payload.get("model", "unknown"))
            agent = str(event.get("actor", "unknown"))
            prompt_tokens += prompt
            completion_tokens += completion
            cost_usd += cost
            _accumulate(by_agent, agent, prompt, completion, cost)
            _accumulate(by_model, model, prompt, completion, cost)
        return CostSummary(
            trace_id=trace_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost_usd,
            model_calls=model_calls,
            by_agent=by_agent,
            by_model=by_model,
        )


def _summarize_model_calls(trace_id: str | None, calls: list[JsonObject]) -> CostSummary:
    prompt_tokens = 0
    completion_tokens = 0
    cost_usd = 0.0
    by_agent: dict[str, JsonObject] = {}
    by_model: dict[str, JsonObject] = {}
    for call in calls:
        prompt = _int(call.get("prompt_tokens"))
        completion = _int(call.get("completion_tokens"))
        cached = _int(call.get("cached_tokens"))
        reasoning = _int(call.get("reasoning_tokens"))
        cost = _float(call.get("estimated_cost"))
        model = str(call.get("model") or "unknown")
        agent = str(call.get("agent_name") or "unknown")
        prompt_tokens += prompt
        completion_tokens += completion
        cost_usd += cost
        _accumulate(by_agent, agent, prompt, completion, cost, cached, reasoning)
        _accumulate(by_model, model, prompt, completion, cost, cached, reasoning)
    return CostSummary(
        trace_id=trace_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=sum(_int(call.get("total_tokens")) for call in calls),
        cost_usd=cost_usd,
        model_calls=len(calls),
        by_agent=by_agent,
        by_model=by_model,
    )


def _accumulate(
    bucket: dict[str, JsonObject],
    key: str,
    prompt: int,
    completion: int,
    cost: float,
    cached: int = 0,
    reasoning: int = 0,
) -> None:
    current = bucket.setdefault(
        key,
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "model_calls": 0,
        },
    )
    current["prompt_tokens"] = _int(current["prompt_tokens"]) + prompt
    current["completion_tokens"] = _int(current["completion_tokens"]) + completion
    current["cached_tokens"] = _int(current["cached_tokens"]) + cached
    current["reasoning_tokens"] = _int(current["reasoning_tokens"]) + reasoning
    current["total_tokens"] = _int(current["total_tokens"]) + prompt + completion + cached + reasoning
    current["cost_usd"] = _float(current["cost_usd"]) + cost
    current["model_calls"] = _int(current["model_calls"]) + 1


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
