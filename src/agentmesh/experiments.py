"""Run a task over a dataset, score every output, and store the results as an experiment.

    import agentmesh
    from agentmesh.evaluators import Contains, LLMJudge

    agentmesh.init()                       # or init(endpoint="http://agentmesh:8787")

    result = agentmesh.run_experiment(
        "refund-questions",                # dataset name, id, or a list of {"input", "expected"} dicts
        task=answer_question,              # sync or async; receives the item input
        evaluators=[Contains(), LLMJudge("correctness", judge=call_my_llm)],
        name="prompt-v3",
    )
    print(result.summary["scores"])

Every item runs inside its own trace (tagged ``experiment``), so a low score links straight to
the spans that produced it. Results go wherever the SDK sends traces: the local database or
the AgentMesh server.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from agentmesh.datasets import _summarize_results, inline_item_id
from agentmesh.evaluators import EvaluationResult, evaluator_name, run_evaluator
from agentmesh.types import JsonObject, new_id, utc_now

logger = logging.getLogger("agentmesh.experiments")

DATASET_PAGE_SIZE = 5000


@dataclass(slots=True)
class ItemResult:
    item_id: str
    input: Any
    expected: Any
    output: Any = None
    error: str | None = None
    trace_id: str | None = None
    duration_ms: float | None = None
    scores: list[EvaluationResult] = field(default_factory=list)

    def to_json(self) -> JsonObject:
        return {
            "item_id": self.item_id,
            "input": _jsonable(self.input),
            "expected": _jsonable(self.expected),
            "output": _jsonable(self.output),
            "error": self.error,
            "status": "failed" if self.error else "completed",
            "trace_id": self.trace_id,
            "duration_ms": self.duration_ms,
            "scores": [score.to_json() for score in self.scores],
        }


@dataclass(slots=True)
class ExperimentResult:
    experiment_id: str
    name: str
    dataset: str | None
    results: list[ItemResult]
    summary: JsonObject
    persisted: bool
    url: str | None = None

    def to_json(self) -> JsonObject:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "dataset": self.dataset,
            "summary": self.summary,
            "persisted": self.persisted,
            "url": self.url,
            "results": [result.to_json() for result in self.results],
        }

    def score(self, name: str) -> float | None:
        """Mean score for one evaluator, or None if it produced no numeric scores."""
        return (self.summary.get("scores", {}).get(name) or {}).get("mean")

    def format_summary(self) -> str:
        lines = [f"Experiment {self.name} ({self.experiment_id})"]
        lines.append(f"  items: {self.summary['items']}   errors: {self.summary['errors']}")
        if self.summary.get("avg_latency_ms") is not None:
            lines.append(f"  avg latency: {self.summary['avg_latency_ms']:.0f} ms")
        for name, stats in sorted(self.summary.get("scores", {}).items()):
            mean = "n/a" if stats.get("mean") is None else f"{stats['mean']:.3f}"
            pass_rate = "" if stats.get("pass_rate") is None else f"   pass rate {stats['pass_rate']:.0%}"
            lines.append(f"  {name}: {mean}{pass_rate}")
        if self.url:
            lines.append(f"  {self.url}")
        return "\n".join(lines)


def run_experiment(
    dataset: str | Sequence[JsonObject],
    task: Callable[..., Any],
    evaluators: Sequence[Any] = (),
    *,
    name: str | None = None,
    description: str | None = None,
    metadata: JsonObject | None = None,
    max_concurrency: int = 4,
    store: Any = None,
) -> ExperimentResult:
    """Synchronous wrapper around :func:`arun_experiment`. Inside a running event loop, await
    ``arun_experiment`` instead."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            arun_experiment(
                dataset,
                task,
                evaluators,
                name=name,
                description=description,
                metadata=metadata,
                max_concurrency=max_concurrency,
                store=store,
            )
        )
    raise RuntimeError("run_experiment() was called inside an event loop; use `await agentmesh.arun_experiment(...)`")


async def arun_experiment(
    dataset: str | Sequence[JsonObject],
    task: Callable[..., Any],
    evaluators: Sequence[Any] = (),
    *,
    name: str | None = None,
    description: str | None = None,
    metadata: JsonObject | None = None,
    max_concurrency: int = 4,
    store: Any = None,
) -> ExperimentResult:
    from agentmesh import sdk

    client = sdk.get_client()
    backend = _backend(client, store)
    dataset_label, dataset_ref, items = await asyncio.to_thread(_load_items, backend, dataset)
    experiment_id = new_id("exp")
    experiment_name = name or f"{dataset_label or 'experiment'}-{time.strftime('%Y%m%d-%H%M%S')}"
    header: JsonObject = {
        "experiment_id": experiment_id,
        "name": experiment_name,
        "description": description,
        "dataset": dataset_ref,
        "dataset_name": dataset_label,
        "status": "running",
        "started_at": utc_now(),
        "evaluators": [evaluator_name(item) for item in evaluators],
        "metadata": {**(metadata or {}), "task": getattr(task, "__qualname__", getattr(task, "__name__", "task"))},
    }
    await asyncio.to_thread(backend.save_experiment, {**header, "results": []})

    semaphore = asyncio.Semaphore(max(int(max_concurrency), 1))
    try:
        # The first parameter always receives the input, whatever it is called.
        passes_item = any(parameter.name == "item" for parameter in list(inspect.signature(task).parameters.values())[1:])
    except (TypeError, ValueError):
        passes_item = False

    async def run_item(item: JsonObject) -> ItemResult:
        async with semaphore:
            return await _run_one(item, task, evaluators, experiment_id, experiment_name, dataset_label, passes_item)

    results = await asyncio.gather(*(run_item(item) for item in items))
    await asyncio.to_thread(sdk.flush)
    for result in results:
        for score in result.scores:
            if score.score is None and score.passed is None:
                continue
            client.score(
                {
                    "trace_id": result.trace_id,
                    "name": score.name,
                    "value": score.score if score.score is not None else score.passed,
                    "passed": score.passed,
                    "label": score.label,
                    "comment": score.comment,
                    "source": "experiment",
                    "metadata": {"experiment_id": experiment_id, "item_id": result.item_id, **score.metadata},
                }
            )
    await asyncio.to_thread(sdk.flush)
    final = {**header, "status": "completed", "ended_at": utc_now()}
    batch = [result.to_json() for result in results]
    saved: JsonObject = {}
    for start in range(0, max(len(batch), 1), 200):
        saved = await asyncio.to_thread(backend.save_experiment, {**final, "results": batch[start : start + 200]}) or {}
    summary = saved.get("summary") or _summarize_results(batch)
    return ExperimentResult(
        experiment_id=experiment_id,
        name=experiment_name,
        dataset=dataset_label,
        results=list(results),
        summary=summary,
        persisted=backend.persistent,
        url=backend.experiment_url(experiment_id),
    )


async def _run_one(
    item: JsonObject,
    task: Callable[..., Any],
    evaluators: Sequence[Any],
    experiment_id: str,
    experiment_name: str,
    dataset_label: str | None,
    passes_item: bool,
) -> ItemResult:
    from agentmesh import sdk

    input_value = item.get("input")
    expected = item.get("expected")
    item_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    result = ItemResult(item_id=str(item.get("item_id") or inline_item_id(input_value)), input=input_value, expected=expected)
    root = sdk.trace(
        f"experiment:{experiment_name}",
        tags=["experiment"],
        metadata={"experiment_id": experiment_id, "item_id": result.item_id, "dataset": dataset_label},
        input=input_value,
    )
    started = time.perf_counter()
    with root:
        result.trace_id = root.trace_id
        try:
            kwargs = {"item": item} if passes_item else {}
            if inspect.iscoroutinefunction(task):
                output = await task(input_value, **kwargs)
            else:
                output = await asyncio.to_thread(task, input_value, **kwargs)
                if inspect.isawaitable(output):
                    output = await output
            result.output = output
            root.set_output(output)
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            root.record_exception(exc)
    result.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    if result.error is None:
        for evaluator in evaluators:
            result.scores.append(
                await run_evaluator(
                    evaluator, input=input_value, output=result.output, expected=expected, metadata=item_metadata
                )
            )
    return result


def evaluate_traces(
    evaluators: Sequence[Any],
    *,
    store: Any = None,
    limit: int = 50,
    filters: JsonObject | None = None,
    skip_scored: bool = True,
) -> list[JsonObject]:
    """Score recorded traces (online evaluation): each evaluator gets the trace's input and output
    with ``expected=None``, and the scores are saved on the trace with ``source='evaluator'``."""
    if store is None:
        from agentmesh import sdk

        backend = _backend(sdk.get_client(), None)
        if not isinstance(backend, _LocalBackend):
            raise RuntimeError("evaluate_traces() needs a local store; pass store=create_store(...)")
        store = backend.store
    traces = store.list_observable_traces(limit=limit, filters=filters or {})
    names = [evaluator_name(item) for item in evaluators]

    async def score_all() -> list[JsonObject]:
        scored: list[JsonObject] = []
        for trace in traces:
            existing = {score["name"] for score in store.list_scores(trace_id=trace["trace_id"])} if skip_scored else set()
            pending = [item for item, item_name in zip(evaluators, names, strict=True) if item_name not in existing]
            if not pending or trace.get("output") is None:
                continue
            results = []
            for evaluator in pending:
                outcome = await run_evaluator(evaluator, input=trace.get("input"), output=trace.get("output"), expected=None)
                if outcome.score is None and outcome.passed is None:
                    continue
                store.save_score(
                    {
                        "trace_id": trace["trace_id"],
                        "name": outcome.name,
                        "value": outcome.score if outcome.score is not None else outcome.passed,
                        "passed": outcome.passed,
                        "label": outcome.label,
                        "comment": outcome.comment,
                        "source": "evaluator",
                        "metadata": outcome.metadata,
                    }
                )
                results.append(outcome.to_json())
            scored.append({"trace_id": trace["trace_id"], "scores": results})
        return scored

    return asyncio.run(score_all())


# -- backends --------------------------------------------------------------------------


class _LocalBackend:
    persistent = True

    def __init__(self, store: Any) -> None:
        self.store = store

    def load_dataset(self, ref: str) -> JsonObject | None:
        return self.store.get_dataset(ref, limit=None)

    def save_experiment(self, payload: JsonObject) -> JsonObject:
        return self.store.save_experiment(payload)

    def experiment_url(self, experiment_id: str) -> str | None:
        return None


class _RemoteBackend:
    persistent = True

    def __init__(self, endpoint: str, api_key: str | None, timeout: float = 30.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def load_dataset(self, ref: str) -> JsonObject | None:
        path = f"/api/datasets/{urllib.parse.quote(ref, safe='')}"
        items: list[JsonObject] = []
        while True:  # the server returns items a page at a time
            try:
                page = self._request("GET", f"{path}?limit={DATASET_PAGE_SIZE}&offset={len(items)}")
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and not items:
                    return None
                raise
            batch = list(page.get("items") or [])
            items.extend(batch)
            if not batch or len(items) >= int(page.get("item_count") or 0):
                return {**page, "items": items}

    def save_experiment(self, payload: JsonObject) -> JsonObject:
        return self._request("POST", "/api/experiments", payload)

    def experiment_url(self, experiment_id: str) -> str | None:
        return f"{self.endpoint}/?page=datasets&experiment={experiment_id}"

    def _request(self, method: str, path: str, payload: JsonObject | None = None) -> JsonObject:
        headers = {"Accept": "application/json", "User-Agent": "agentmesh-python-sdk"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, default=str).encode("utf-8")
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(f"{self.endpoint}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")


class _MemoryBackend:
    persistent = False

    def load_dataset(self, ref: str) -> JsonObject | None:
        return None

    def save_experiment(self, payload: JsonObject) -> JsonObject:
        return {}

    def experiment_url(self, experiment_id: str) -> str | None:
        return None


def _backend(client: Any, store: Any) -> Any:
    from agentmesh.sdk import HttpExporter, LocalStoreExporter

    if store is not None:
        return _LocalBackend(store)
    exporter = client.exporter
    if isinstance(exporter, HttpExporter):
        return _RemoteBackend(exporter.endpoint, exporter.api_key)
    if isinstance(exporter, LocalStoreExporter):
        return _LocalBackend(exporter.store)
    return _MemoryBackend()


def _load_items(backend: Any, dataset: str | Sequence[JsonObject]) -> tuple[str | None, str | None, list[JsonObject]]:
    if isinstance(dataset, str):
        loaded = backend.load_dataset(dataset)
        if loaded is None:
            raise KeyError(f"dataset not found: {dataset}")
        return str(loaded["name"]), str(loaded["dataset_id"]), list(loaded.get("items") or [])
    items = []
    for index, item in enumerate(dataset):
        if not isinstance(item, dict) or "input" not in item:
            raise ValueError(f"dataset item {index} needs an 'input' key")
        items.append(item)
    return None, None, items


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        from agentmesh.types import safe_json

        return safe_json(value)
