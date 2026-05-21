from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Protocol

from agentmesh.event_bus import AsyncEventBus
from agentmesh.errors import AgentMeshError, ErrorKind
from agentmesh.types import JsonObject

if TYPE_CHECKING:
    from agentmesh.agents import AgentResult
    from agentmesh.workflow import RunContext, WorkflowStep


class StepRunner(Protocol):
    def __call__(
        self,
        step: "WorkflowStep",
        context: "RunContext",
        previous_outputs: dict[str, "AgentResult"],
        event: JsonObject | None = None,
    ) -> Awaitable["AgentResult"]:
        raise NotImplementedError


class WorkflowScheduler:
    def __init__(self, event_bus: AsyncEventBus | None = None, max_events: int = 100) -> None:
        self.event_bus = event_bus or AsyncEventBus()
        self.max_events = max_events

    async def run_sequential(
        self,
        steps: Sequence["WorkflowStep"],
        context: "RunContext",
        run_step: StepRunner,
    ) -> dict[str, "AgentResult"]:
        outputs: dict[str, AgentResult] = {}
        for step in steps:
            result = await run_step(step, context, outputs)
            outputs[str(step.id)] = result
            context.workflow_memory.set(str(step.id), result.to_json())
        return outputs

    async def run_parallel(
        self,
        steps: Sequence["WorkflowStep"],
        context: "RunContext",
        run_step: StepRunner,
    ) -> dict[str, "AgentResult"]:
        outputs: dict[str, AgentResult] = {}
        pending = {str(step.id): step for step in steps}
        while pending:
            ready = [
                step
                for step in pending.values()
                if all(dependency in outputs for dependency in step.depends_on)
            ]
            if not ready:
                raise AgentMeshError("Workflow has unsatisfied or cyclic dependencies", ErrorKind.WORKFLOW)
            results = await asyncio.gather(*(run_step(step, context, outputs) for step in ready))
            for step, result in zip(ready, results, strict=True):
                outputs[str(step.id)] = result
                context.workflow_memory.set(str(step.id), result.to_json())
                del pending[str(step.id)]
        return outputs

    async def run_hierarchical(
        self,
        steps: Sequence["WorkflowStep"],
        context: "RunContext",
        run_step: StepRunner,
    ) -> dict[str, "AgentResult"]:
        if not steps:
            return {}
        manager = steps[0]
        outputs: dict[str, AgentResult] = {str(manager.id): await run_step(manager, context, {})}
        context.workflow_memory.set(str(manager.id), outputs[str(manager.id)].to_json())
        child_steps = list(steps[1:])
        if child_steps:
            child_results = await asyncio.gather(*(run_step(step, context, outputs) for step in child_steps))
            for step, result in zip(child_steps, child_results, strict=True):
                outputs[str(step.id)] = result
                context.workflow_memory.set(str(step.id), result.to_json())
        return outputs

    async def run_event_driven(
        self,
        steps: Sequence["WorkflowStep"],
        context: "RunContext",
        run_step: StepRunner,
    ) -> dict[str, "AgentResult"]:
        outputs: dict[str, AgentResult] = {}
        await self.event_bus.publish("workflow.start", {"input": context.workflow_input}, context.trace_id)
        handled = 0
        while not self.event_bus.empty() and handled < self.max_events:
            event = await self.event_bus.next_event()
            context.recorder.event(context.trace_id, "event.received", "workflow", event.to_json(), parent_span_id=context.root_span_id)
            ready = [step for step in steps if step.trigger == event.event_type]
            for step in ready:
                result = await run_step(step, context, outputs, event.to_json())
                outputs[str(step.id)] = result
                context.workflow_memory.set(str(step.id), result.to_json())
                await self.event_bus.publish(f"step.completed.{step.id}", result.to_json(), context.trace_id)
                await self.event_bus.publish("task.completed", result.to_json(), context.trace_id)
            handled += 1
        if handled >= self.max_events and not self.event_bus.empty():
            raise AgentMeshError("Event workflow reached max_events guardrail", ErrorKind.WORKFLOW)
        return outputs
