"""Automatic trace insights: the questions you ask first when an agent misbehaves.

* Where did it fail first (the deepest failing span, not the wrapper that re-raised)?
* Is the agent stuck in a loop calling the same tool with the same arguments?
* Is it re-sending identical prompts?
* Is the context window growing unchecked from call to call?
* Is prompt caching working?
* Where did the time and money go?
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from agentmesh.types import JsonObject, dumps_json, stable_hash

LOOP_THRESHOLD = 3
CONTEXT_GROWTH_FACTOR = 3.0
CONTEXT_GROWTH_MIN_TOKENS = 20_000
CACHE_HINT_MIN_PROMPT_TOKENS = 50_000


def trace_insights(store: Any, trace_id: str) -> JsonObject:
    getter = getattr(store, "get_observable_trace", None) or store.get_trace
    trace = getter(trace_id)
    if trace is None:
        return {"trace_id": trace_id, "found": False, "findings": []}
    spans: list[JsonObject] = store.list_spans(trace_id) if hasattr(store, "list_spans") else []
    model_calls: list[JsonObject] = store.list_model_calls(trace_id, 5000) if hasattr(store, "list_model_calls") else []
    tool_calls: list[JsonObject] = store.list_tool_calls(trace_id, 5000) if hasattr(store, "list_tool_calls") else []
    model_calls = sorted(model_calls, key=lambda call: str(call.get("started_at") or ""))

    by_id = {str(span["span_id"]): span for span in spans}
    children: dict[str, list[JsonObject]] = defaultdict(list)
    for span in spans:
        parent = span.get("parent_span_id")
        if parent and parent in by_id:
            children[str(parent)].append(span)

    findings: list[JsonObject] = []
    root_cause = _root_cause(spans, children, by_id)
    if root_cause is not None:
        findings.append(root_cause)
    findings.extend(_tool_loops(tool_calls))
    findings.extend(_repeated_prompts(model_calls))
    findings.extend(_context_growth(model_calls))
    findings.extend(_cache_usage(model_calls))
    findings.extend(_pricing_gaps(model_calls))

    trace_duration = _num(trace.get("duration_ms")) or _num(trace.get("max_latency_ms"))
    slowest = _slowest_spans(spans, children, trace_duration)
    costliest = sorted(
        (call for call in model_calls if _num(call.get("estimated_cost")) > 0),
        key=lambda call: _num(call.get("estimated_cost")),
        reverse=True,
    )[:5]
    total_cost = sum(_num(call.get("estimated_cost")) for call in model_calls)
    if costliest and total_cost > 0 and len(model_calls) >= 3:
        share = _num(costliest[0].get("estimated_cost")) / total_cost
        if share >= 0.5:
            findings.append(
                {
                    "kind": "cost_hotspot",
                    "severity": "info",
                    "message": f"One model call ({costliest[0].get('model')}) accounts for {share:.0%} of this trace's cost.",
                    "span_id": costliest[0].get("span_id"),
                }
            )

    stats = {
        "span_count": len(spans),
        "llm_calls": len(model_calls),
        "tool_calls": len(tool_calls),
        "failed_spans": sum(1 for span in spans if span.get("status") == "failed"),
        "input_tokens": sum(int(_num(call.get("prompt_tokens"))) for call in model_calls),
        "output_tokens": sum(int(_num(call.get("completion_tokens"))) for call in model_calls),
        "cache_read_tokens": sum(int(_num(call.get("cached_tokens"))) for call in model_calls),
        "total_tokens": sum(int(_num(call.get("total_tokens"))) for call in model_calls),
        "estimated_cost": round(total_cost, 8),
        "duration_ms": trace_duration,
        "models": sorted({str(call.get("model")) for call in model_calls if call.get("model")}),
    }
    severity_rank = {"high": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda item: severity_rank.get(str(item.get("severity")), 3))
    return {
        "trace_id": trace_id,
        "found": True,
        "status": trace.get("status"),
        "name": trace.get("workflow_name") or trace.get("name"),
        "summary": _summary(trace, stats, findings),
        "stats": stats,
        "findings": findings,
        "slowest_spans": slowest,
        "costliest_calls": [
            {
                "span_id": call.get("span_id"),
                "model": call.get("model"),
                "agent": call.get("agent_name"),
                "estimated_cost": call.get("estimated_cost"),
                "prompt_tokens": call.get("prompt_tokens"),
                "completion_tokens": call.get("completion_tokens"),
                "duration_ms": call.get("duration_ms"),
            }
            for call in costliest
        ],
    }


def span_label(span: JsonObject) -> str:
    return str(
        span.get("name")
        or span.get("tool_name")
        or span.get("task_name")
        or span.get("model")
        or span.get("event_type")
        or "span"
    )


def _root_cause(
    spans: list[JsonObject], children: dict[str, list[JsonObject]], by_id: dict[str, JsonObject]
) -> JsonObject | None:
    failed = [span for span in spans if span.get("status") == "failed"]
    if not failed:
        return None
    leaves = [
        span
        for span in failed
        if not any(child.get("status") == "failed" for child in children.get(str(span["span_id"]), []))
    ]
    first = sorted(leaves or failed, key=lambda span: str(span.get("started_at") or ""))[0]
    path: list[str] = []
    cursor: JsonObject | None = first
    for _ in range(32):
        if cursor is None:
            break
        path.append(span_label(cursor))
        parent = cursor.get("parent_span_id")
        cursor = by_id.get(str(parent)) if parent else None
    error = first.get("error_message") or first.get("error_type") or "no error message recorded"
    return {
        "kind": "root_cause",
        "severity": "high",
        "message": f"First failure: {span_label(first)} -> {error}",
        "span_id": first.get("span_id"),
        "error_type": first.get("error_type"),
        "path": list(reversed(path)),
        "failed_span_count": len(failed),
    }


def _tool_loops(tool_calls: list[JsonObject]) -> list[JsonObject]:
    findings: list[JsonObject] = []
    # Calls with unknown arguments (content capture disabled) cannot be judged identical.
    identical = Counter(
        (str(call.get("tool_name")), dumps_json(call.get("input"))) for call in tool_calls if call.get("input") is not None
    )
    for (tool_name, _arguments), count in identical.most_common():
        if count < LOOP_THRESHOLD:
            break
        findings.append(
            {
                "kind": "tool_loop",
                "severity": "warning",
                "message": f"Tool '{tool_name}' was called {count} times with identical arguments; the agent may be looping.",
                "tool_name": tool_name,
                "count": count,
            }
        )
    return findings


def _repeated_prompts(model_calls: list[JsonObject]) -> list[JsonObject]:
    hashes = Counter(
        stable_hash(dumps_json([call.get("model"), call.get("prompt")]))
        for call in model_calls
        if call.get("prompt") not in (None, {}, {"system": None, "prompt": None})
    )
    repeated = [count for count in hashes.values() if count >= LOOP_THRESHOLD]
    if not repeated:
        return []
    return [
        {
            "kind": "repeated_llm_call",
            "severity": "warning",
            "message": f"An identical prompt was sent {max(repeated)} times. Consider caching the result or checking for a retry/loop bug.",
            "count": max(repeated),
        }
    ]


def _context_growth(model_calls: list[JsonObject]) -> list[JsonObject]:
    sizes = [int(_num(call.get("prompt_tokens"))) for call in model_calls if _num(call.get("prompt_tokens")) > 0]
    if len(sizes) < 3 or sizes[0] <= 0:
        return []
    factor = sizes[-1] / sizes[0]
    if factor < CONTEXT_GROWTH_FACTOR or sizes[-1] < CONTEXT_GROWTH_MIN_TOKENS:
        return []
    return [
        {
            "kind": "context_growth",
            "severity": "warning",
            "message": (
                f"Input context grew {factor:.1f}x across {len(sizes)} model calls ({sizes[0]:,} -> {sizes[-1]:,} tokens). "
                "Consider summarizing history, trimming tool results, or context compaction."
            ),
            "first_prompt_tokens": sizes[0],
            "last_prompt_tokens": sizes[-1],
        }
    ]


def _cache_usage(model_calls: list[JsonObject]) -> list[JsonObject]:
    cacheable = [
        call
        for call in model_calls
        if str(call.get("provider") or "").split(".")[0]
        in {"anthropic", "openai", "openai-compatible", "gemini", "gcp", "aws", "azure"}
    ]
    prompt_tokens = sum(_num(call.get("prompt_tokens")) for call in cacheable)
    cache_read = sum(_num(call.get("cached_tokens")) for call in cacheable)
    if len(cacheable) < 2 or prompt_tokens < CACHE_HINT_MIN_PROMPT_TOKENS:
        return []
    if cache_read == 0:
        return [
            {
                "kind": "no_cache_hits",
                "severity": "info",
                "message": f"{int(prompt_tokens):,} input tokens across {len(cacheable)} calls with zero prompt-cache reads. Stable system prompts and tool definitions are good caching candidates.",
            }
        ]
    return [
        {
            "kind": "cache_hit_rate",
            "severity": "info",
            "message": f"Prompt cache served {cache_read / prompt_tokens:.0%} of input tokens.",
            "cache_read_tokens": int(cache_read),
        }
    ]


def _pricing_gaps(model_calls: list[JsonObject]) -> list[JsonObject]:
    unknown = sorted(
        {
            str(call.get("model"))
            for call in model_calls
            if call.get("cost_status") == "unknown" and _num(call.get("total_tokens")) > 0
        }
    )
    if not unknown:
        return []
    return [
        {
            "kind": "unpriced_models",
            "severity": "info",
            "message": f"No pricing for {', '.join(unknown[:5])}; costs are under-reported. Run `agentmesh pricing sync` or set AGENTMESH_PRICING_JSON.",
            "models": unknown,
        }
    ]


def _slowest_spans(
    spans: list[JsonObject], children: dict[str, list[JsonObject]], trace_duration: float
) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for span in spans:
        duration = _num(span.get("duration_ms"))
        if duration <= 0:
            continue
        child_time = sum(_num(child.get("duration_ms")) for child in children.get(str(span["span_id"]), []))
        self_time = max(duration - child_time, 0.0)
        rows.append(
            {
                "span_id": span.get("span_id"),
                "label": span_label(span),
                "event_type": span.get("event_type"),
                "duration_ms": round(duration, 3),
                "self_time_ms": round(self_time, 3),
                "share_of_trace": round(self_time / trace_duration, 4) if trace_duration else None,
            }
        )
    return sorted(rows, key=lambda row: row["self_time_ms"], reverse=True)[:5]


def _summary(trace: JsonObject, stats: JsonObject, findings: list[JsonObject]) -> str:
    parts = [
        f"{trace.get('status', 'unknown')} trace",
        f"{stats['llm_calls']} LLM call(s)",
        f"{stats['tool_calls']} tool call(s)",
        f"{stats['total_tokens']:,} tokens",
        f"${stats['estimated_cost']:.4f}",
    ]
    if stats.get("duration_ms"):
        parts.append(f"{float(stats['duration_ms']) / 1000:.2f}s")
    headline = next((item["message"] for item in findings if item.get("severity") in {"high", "warning"}), None)
    return ", ".join(parts) + (f". {headline}" if headline else ".")


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
