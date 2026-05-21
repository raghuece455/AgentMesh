from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from agentmesh.agents import Agent, AgentResult
from agentmesh.event_bus import AsyncEventBus
from agentmesh.errors import AgentMeshError, ErrorKind, WorkflowCancelled, classify_error
from agentmesh.memory import SQLiteMemoryStore, WorkflowMemory
from agentmesh.reliability import BudgetLimiter, RetryPolicy
from agentmesh.scheduler import WorkflowScheduler
from agentmesh.storage import SQLiteStore
from agentmesh.task import Task
from agentmesh.tracing import TraceRecorder
from agentmesh.types import JsonObject, JsonValue, dumps_json, safe_json, stable_hash
from agentmesh.messages import AgentMessage
from agentmesh.planning import Planner


class WorkflowMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HIERARCHICAL = "hierarchical"
    EVENT_DRIVEN = "event_driven"


@dataclass(slots=True)
class WorkflowStep:
    agent_name: str
    task: Task
    depends_on: tuple[str, ...] = ()
    trigger: str | None = None
    id: str | None = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = self.task.id

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "task": self.task.to_json(),
            "depends_on": list(self.depends_on),
            "trigger": self.trigger,
        }


@dataclass(slots=True)
class WorkflowResult:
    trace_id: str
    status: str
    outputs: dict[str, AgentResult]
    events: list[JsonObject]

    @property
    def output(self) -> str:
        if not self.outputs:
            return ""
        last_key = list(self.outputs.keys())[-1]
        return self.outputs[last_key].output

    def to_json(self) -> JsonObject:
        return {
            "trace_id": self.trace_id,
            "status": self.status,
            "outputs": {key: value.to_json() for key, value in self.outputs.items()},
            "events": self.events,
        }


@dataclass(slots=True)
class RunContext:
    trace_id: str
    store: SQLiteStore
    recorder: TraceRecorder
    memory_store: SQLiteMemoryStore
    workflow_memory: WorkflowMemory
    budget: BudgetLimiter
    workflow_input: JsonValue
    approval_callback: Callable[[object, JsonObject, object], Awaitable[bool] | bool] | None = None
    cancellation_event: asyncio.Event = field(default_factory=asyncio.Event)
    delegated_tasks: list[tuple[str, Task]] = field(default_factory=list)
    root_span_id: str | None = None
    active_task_span_id: str | None = None
    active_agent_span_id: str | None = None

    def cancel(self) -> None:
        self.cancellation_event.set()

    def delegate(self, agent_name: str, task: Task) -> None:
        self.delegated_tasks.append((agent_name, task))
        self.recorder.event(self.trace_id, "task.delegated", agent_name, {"task": task.to_json()}, parent_span_id=self.root_span_id)


class Workflow:
    def __init__(
        self,
        name: str,
        mode: WorkflowMode = WorkflowMode.SEQUENTIAL,
        store: SQLiteStore | None = None,
        recorder: TraceRecorder | None = None,
        budget: BudgetLimiter | None = None,
        max_events: int = 100,
        planner: Planner | None = None,
        event_bus: AsyncEventBus | None = None,
        scheduler: WorkflowScheduler | None = None,
    ) -> None:
        self.name = name
        self.mode = mode
        self.store = store or SQLiteStore()
        self.recorder = recorder or TraceRecorder(self.store)
        self.memory_store = SQLiteMemoryStore(self.store, self.recorder)
        self.budget = budget or BudgetLimiter()
        self.max_events = max_events
        self.planner = planner
        self.event_bus = event_bus or AsyncEventBus()
        self.scheduler = scheduler or WorkflowScheduler(self.event_bus, max_events)
        self.agents: dict[str, Agent] = {}
        self.steps: list[WorkflowStep] = []

    def add_agent(self, agent: Agent) -> "Workflow":
        self.agents[agent.name] = agent
        return self

    def add_step(
        self,
        agent_name: str,
        task: Task | str,
        depends_on: tuple[str, ...] = (),
        trigger: str | None = None,
        step_id: str | None = None,
    ) -> "Workflow":
        resolved_task = task if isinstance(task, Task) else Task(str(task))
        self.steps.append(WorkflowStep(agent_name, resolved_task, depends_on, trigger, step_id))
        return self

    async def run(
        self,
        input_value: JsonValue | None = None,
        trace_id: str | None = None,
        approval_callback: Callable[[object, JsonObject, object], Awaitable[bool] | bool] | None = None,
    ) -> WorkflowResult:
        resolved_input: JsonValue = input_value if input_value is not None else {}
        if self.planner is not None and not self.steps:
            for planned in await self.planner.plan(resolved_input):
                self.add_step(planned.agent_name, planned.task, planned.depends_on, planned.trigger, planned.step_id)
        resolved_trace_id = self.recorder.start_workflow(self.name, resolved_input, trace_id)
        context = RunContext(
            trace_id=resolved_trace_id,
            store=self.store,
            recorder=self.recorder,
            memory_store=self.memory_store,
            workflow_memory=WorkflowMemory(),
            budget=self.budget,
            workflow_input=resolved_input,
            approval_callback=approval_callback,
            root_span_id=self.recorder.root_span_id(resolved_trace_id),
        )
        outputs: dict[str, AgentResult] = {}
        try:
            if self.mode == WorkflowMode.SEQUENTIAL:
                outputs = await self.scheduler.run_sequential(self.steps, context, self._run_step)
            elif self.mode == WorkflowMode.PARALLEL:
                outputs = await self.scheduler.run_parallel(self.steps, context, self._run_step)
            elif self.mode == WorkflowMode.HIERARCHICAL:
                outputs = await self.scheduler.run_hierarchical(self.steps, context, self._run_step)
            elif self.mode == WorkflowMode.EVENT_DRIVEN:
                outputs = await self.scheduler.run_event_driven(self.steps, context, self._run_step)
            else:
                raise AgentMeshError(f"Unsupported workflow mode: {self.mode}", ErrorKind.WORKFLOW)
            while context.delegated_tasks:
                agent_name, task = context.delegated_tasks.pop(0)
                step = WorkflowStep(agent_name, task)
                outputs[str(step.id)] = await self._run_step(step, context, outputs)
            self.recorder.finish_workflow(resolved_trace_id, "succeeded", safe_json({k: v.to_json() for k, v in outputs.items()}))
            return WorkflowResult(resolved_trace_id, "succeeded", outputs, self.store.list_events(resolved_trace_id))
        except Exception as exc:
            classified = classify_error(exc)
            self.recorder.event(
                resolved_trace_id,
                "workflow.failed",
                "workflow",
                {"error": classified.to_json()},
                parent_span_id=self.recorder.root_span_id(resolved_trace_id),
            )
            self.recorder.finish_workflow(resolved_trace_id, "failed", None, classified.to_json())
            raise classified

    async def run_from_checkpoint(
        self,
        checkpoint_id: str,
        approval_callback: Callable[[object, JsonObject, object], Awaitable[bool] | bool] | None = None,
    ) -> WorkflowResult:
        checkpoint = self.store.get_checkpoint(checkpoint_id)
        if checkpoint is None:
            raise AgentMeshError("Checkpoint not found", ErrorKind.WORKFLOW, {"checkpoint_id": checkpoint_id})
        state = checkpoint.get("state", {})
        if not isinstance(state, dict):
            raise AgentMeshError("Checkpoint state is invalid", ErrorKind.WORKFLOW, {"checkpoint_id": checkpoint_id})
        workflow_input = state.get("workflow_input", {})
        completed = {str(item) for item in state.get("completed_step_ids", []) if item is not None}
        raw_outputs = state.get("outputs", {})
        outputs = _agent_results_from_json(raw_outputs if isinstance(raw_outputs, dict) else {})
        trace_id = self.recorder.start_workflow(f"{self.name}:checkpoint-replay", workflow_input)
        context = RunContext(
            trace_id=trace_id,
            store=self.store,
            recorder=self.recorder,
            memory_store=self.memory_store,
            workflow_memory=WorkflowMemory(),
            budget=self.budget,
            workflow_input=workflow_input,
            approval_callback=approval_callback,
            root_span_id=self.recorder.root_span_id(trace_id),
        )
        memory = state.get("workflow_memory", {})
        if isinstance(memory, dict):
            values = memory.get("values", {})
            if isinstance(values, dict):
                context.workflow_memory.values.update(values)
        try:
            remaining = [step for step in self.steps if str(step.id) not in completed]
            for step in remaining:
                result = await self._run_step(step, context, outputs)
                outputs[str(step.id)] = result
                context.workflow_memory.set(str(step.id), result.to_json())
            self.recorder.finish_workflow(trace_id, "succeeded", safe_json({key: value.to_json() for key, value in outputs.items()}))
            return WorkflowResult(trace_id, "succeeded", outputs, self.store.list_events(trace_id))
        except Exception as exc:
            classified = classify_error(exc)
            self.recorder.event(
                trace_id,
                "workflow.failed",
                "workflow",
                {"error": classified.to_json()},
                parent_span_id=self.recorder.root_span_id(trace_id),
            )
            self.recorder.finish_workflow(trace_id, "failed", None, classified.to_json())
            raise classified

    async def _run_sequential(self, context: RunContext) -> dict[str, AgentResult]:
        outputs: dict[str, AgentResult] = {}
        for step in self.steps:
            result = await self._run_step(step, context, outputs)
            outputs[str(step.id)] = result
            context.workflow_memory.set(str(step.id), result.to_json())
        return outputs

    async def _run_parallel(self, context: RunContext) -> dict[str, AgentResult]:
        tasks = [asyncio.create_task(self._run_step(step, context, {})) for step in self.steps]
        results = await asyncio.gather(*tasks)
        return {str(step.id): result for step, result in zip(self.steps, results, strict=True)}

    async def _run_hierarchical(self, context: RunContext) -> dict[str, AgentResult]:
        if not self.steps:
            return {}
        manager = self.steps[0]
        outputs: dict[str, AgentResult] = {str(manager.id): await self._run_step(manager, context, {})}
        context.workflow_memory.set(str(manager.id), outputs[str(manager.id)].to_json())
        child_steps = self.steps[1:]
        if child_steps:
            child_tasks = [asyncio.create_task(self._run_step(step, context, outputs)) for step in child_steps]
            child_results = await asyncio.gather(*child_tasks)
            for step, result in zip(child_steps, child_results, strict=True):
                outputs[str(step.id)] = result
                context.workflow_memory.set(str(step.id), result.to_json())
        return outputs

    async def _run_event_driven(self, context: RunContext) -> dict[str, AgentResult]:
        outputs: dict[str, AgentResult] = {}
        queue: deque[JsonObject] = deque([{"type": "workflow.start", "payload": safe_json(context.workflow_input)}])
        handled = 0
        while queue and handled < self.max_events:
            event = queue.popleft()
            event_type = str(event.get("type", ""))
            context.recorder.event(context.trace_id, "event.received", "workflow", event, parent_span_id=context.root_span_id)
            ready = [step for step in self.steps if step.trigger == event_type]
            for step in ready:
                result = await self._run_step(step, context, outputs, event)
                outputs[str(step.id)] = result
                context.workflow_memory.set(str(step.id), result.to_json())
                queue.append({"type": f"step.completed.{step.id}", "payload": result.to_json()})
                queue.append({"type": "task.completed", "payload": result.to_json()})
            handled += 1
        if handled >= self.max_events and queue:
            raise AgentMeshError("Event workflow reached max_events guardrail", ErrorKind.WORKFLOW)
        return outputs

    async def _run_step(
        self,
        step: WorkflowStep,
        context: RunContext,
        previous_outputs: dict[str, AgentResult],
        event: JsonObject | None = None,
    ) -> AgentResult:
        if context.cancellation_event.is_set():
            raise WorkflowCancelled()
        if step.agent_name not in self.agents:
            raise AgentMeshError(f"Unknown agent: {step.agent_name}", ErrorKind.WORKFLOW, {"agent": step.agent_name})
        agent = self.agents[step.agent_name]
        idempotency_key = _idempotency_key(step, context.workflow_input)
        if idempotency_key is not None and hasattr(self.store, "get_task_result"):
            cached = self.store.get_task_result(idempotency_key)
            if isinstance(cached, dict):
                context.recorder.event(
                    context.trace_id,
                    "task.cache_hit",
                    step.agent_name,
                    {"step": step.to_json(), "idempotency_key": idempotency_key},
                    parent_span_id=context.root_span_id,
                )
                return _agent_result_from_json(cached)
        attempt = 1
        retry_policy: RetryPolicy = step.task.retry_policy
        while True:
            try:
                self._save_checkpoint(context, "before_step", step, previous_outputs)
                payload: JsonObject = {
                    "task": step.task.description,
                    "input": step.task.input,
                    "workflow_input": safe_json(context.workflow_input),
                    "previous_outputs": {key: value.to_json() for key, value in previous_outputs.items()},
                    "tool_calls": [call.to_json() for call in step.task.tool_calls],
                    "event": event or {},
                    "attempt": attempt,
                    "metadata": step.task.metadata,
                }
                message = AgentMessage(
                    sender="workflow",
                    recipient=step.agent_name,
                    payload=payload,
                    trace_id=context.trace_id,
                    task_id=step.task.id,
                )
                task_span_id = context.recorder.event(
                    context.trace_id,
                    "task.started",
                    step.agent_name,
                    {"step": step.to_json(), "attempt": attempt, "input": payload},
                    parent_span_id=context.root_span_id,
                )
                coroutine = agent.run(message, context)
                previous_task_span = context.active_task_span_id
                context.active_task_span_id = task_span_id
                try:
                    if step.task.timeout_seconds is None:
                        result = await coroutine
                    else:
                        result = await asyncio.wait_for(coroutine, timeout=step.task.timeout_seconds)
                finally:
                    context.active_task_span_id = previous_task_span
                context.recorder.event(
                    context.trace_id,
                    "task.succeeded",
                    step.agent_name,
                    {"step": step.to_json(), "attempt": attempt, "output": result.to_json()},
                    parent_span_id=task_span_id,
                )
                self._save_checkpoint(context, "after_step", step, {**previous_outputs, str(step.id): result})
                if idempotency_key is not None and hasattr(self.store, "save_task_result"):
                    self.store.save_task_result(idempotency_key, context.trace_id, step.task.id, result.to_json())
                    context.recorder.event(
                        context.trace_id,
                        "task.cache_saved",
                        step.agent_name,
                        {"step": step.to_json(), "idempotency_key": idempotency_key},
                        parent_span_id=context.root_span_id,
                    )
                return result
            except Exception as exc:
                classified = classify_error(exc)
                self._save_checkpoint(context, "failed_step", step, previous_outputs, classified.to_json())
                context.recorder.event(
                    context.trace_id,
                    "task.failed",
                    step.agent_name,
                    {"step": step.to_json(), "attempt": attempt, "error": classified.to_json()},
                    parent_span_id=context.root_span_id,
                )
                if not retry_policy.can_retry(classified, attempt):
                    raise classified
                delay = retry_policy.delay_for(attempt)
                context.recorder.event(
                    context.trace_id,
                    "task.retry_scheduled",
                    step.agent_name,
                    {"step": step.to_json(), "attempt": attempt, "delay_seconds": delay},
                    parent_span_id=context.root_span_id,
                )
                attempt += 1
                await asyncio.sleep(delay)

    def _save_checkpoint(
        self,
        context: RunContext,
        checkpoint_type: str,
        step: WorkflowStep,
        outputs: dict[str, AgentResult],
        error: JsonObject | None = None,
    ) -> None:
        completed = list(outputs.keys())
        state: JsonObject = {
            "workflow": self.name,
            "mode": self.mode.value,
            "workflow_input": safe_json(context.workflow_input),
            "workflow_memory": context.workflow_memory.to_json(),
            "completed_step_ids": completed,
            "outputs": {key: value.to_json() for key, value in outputs.items()},
            "current_step": step.to_json(),
        }
        if error is not None:
            state["error"] = error
        checkpoint_id = self.store.save_checkpoint(context.trace_id, checkpoint_type, state, str(step.id))
        context.recorder.event(
            context.trace_id,
            "checkpoint.saved",
            "workflow",
            {"checkpoint_id": checkpoint_id, "checkpoint_type": checkpoint_type, "step_id": step.id},
            parent_span_id=context.active_task_span_id or context.root_span_id,
        )


def _agent_results_from_json(raw_outputs: dict[str, JsonValue]) -> dict[str, AgentResult]:
    outputs: dict[str, AgentResult] = {}
    for key, value in raw_outputs.items():
        if not isinstance(value, dict):
            continue
        result = _agent_result_from_json(value)
        result.metadata["replayed_from_checkpoint"] = True
        outputs[str(key)] = result
    return outputs


def _agent_result_from_json(value: JsonObject) -> AgentResult:
    tool_results = value.get("tool_results", [])
    metadata = value.get("metadata", {})
    return AgentResult(
        agent=str(value.get("agent", "unknown")),
        output=str(value.get("output", "")),
        tool_results=tool_results if isinstance(tool_results, list) else [],
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _idempotency_key(step: WorkflowStep, workflow_input: JsonValue) -> str | None:
    explicit = step.task.metadata.get("idempotency_key")
    if explicit is not None:
        return str(explicit)
    if step.task.metadata.get("idempotent") is True:
        return stable_hash(dumps_json({"step": step.to_json(), "workflow_input": workflow_input}))
    return None
