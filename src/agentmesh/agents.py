from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from agentmesh.messages import AgentMessage
from agentmesh.pricing import estimate_model_cost
from agentmesh.providers import ModelProvider, ModelRequest, ModelResponse
from agentmesh.task import ToolCallRequest
from agentmesh.tools import PermissionLevel, ToolContext, ToolRegistry
from agentmesh.types import JsonObject, JsonValue, safe_json
from agentmesh.errors import classify_error


@dataclass(slots=True)
class AgentResult:
    agent: str
    output: str
    model_response: ModelResponse | None = None
    tool_results: list[JsonObject] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)

    def to_json(self) -> JsonObject:
        return {
            "agent": self.agent,
            "output": self.output,
            "model_response": self.model_response.to_json() if self.model_response else None,
            "tool_results": self.tool_results,
            "messages": [message.to_json() for message in self.messages],
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class Agent:
    name: str
    role: str
    instructions: str
    model_provider: ModelProvider
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    permissions: set[PermissionLevel] = field(default_factory=lambda: {PermissionLevel.READ})
    model: str | None = None
    temperature: float = 0.2
    top_p: float | None = None
    max_tokens: int | None = None

    async def run(self, message: AgentMessage, context: object) -> AgentResult:
        span_id = context.recorder.event(
            context.trace_id,
            "agent.started",
            self.name,
            {"role": self.role, "message": message.to_json()},
            parent_span_id=getattr(context, "active_task_span_id", None),
        )
        previous_agent_span = getattr(context, "active_agent_span_id", None)
        context.active_agent_span_id = span_id
        try:
            tool_results = await self._run_tools(message, context)
        finally:
            context.active_agent_span_id = previous_agent_span
        prompt = self._build_prompt(message, tool_results, context)
        request = ModelRequest(
            prompt=prompt,
            system=self.instructions,
            model=self.model,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
            trace_id=context.trace_id,
            metadata={
                "agent": self.name,
                "role": self.role,
                "task_id": message.task_id,
                **_metadata_payload(message.payload.get("metadata", {})),
            },
        )
        prompt_id = None
        if hasattr(context.store, "save_prompt_version"):
            prompt_id = context.store.save_prompt_version(
                trace_id=context.trace_id,
                agent=self.name,
                task_id=message.task_id,
                system_prompt=request.system,
                user_prompt=request.prompt,
                metadata=request.metadata,
            )
        context.recorder.event(
            context.trace_id,
            "model.call",
            self.name,
            {
                "prompt_id": prompt_id,
                "prompt_version": prompt_id,
                "provider": self.model_provider.name,
                "model": request.model,
                "system": request.system,
                "prompt": request.prompt,
                "temperature": request.temperature,
                "top_p": request.top_p,
                "max_tokens": request.max_tokens,
                "metadata": request.metadata,
            },
            parent_span_id=span_id,
        )
        started = time.perf_counter()
        try:
            response = await self.model_provider.generate(request)
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            classified = classify_error(exc)
            context.recorder.event(
                context.trace_id,
                "model.failed",
                self.name,
                {
                    "prompt_id": prompt_id,
                    "prompt_version": prompt_id,
                    "provider": self.model_provider.name,
                    "model": request.model,
                    "temperature": request.temperature,
                    "top_p": request.top_p,
                    "max_tokens": request.max_tokens,
                    "latency_ms": latency_ms,
                    "error": classified.to_json(),
                    "metadata": request.metadata,
                },
                parent_span_id=span_id,
            )
            raise classified
        latency_ms = (time.perf_counter() - started) * 1000
        cached_tokens = _int(response.raw.get("cached_tokens", 0))
        reasoning_tokens = _int(response.raw.get("reasoning_tokens", 0))
        cost_estimate = estimate_model_cost(
            self.model_provider.name,
            response.model,
            response.prompt_tokens,
            response.completion_tokens,
            cached_tokens,
            reasoning_tokens,
        )
        cost_usd = response.cost_usd if response.cost_usd > 0 else cost_estimate.cost_usd
        cost_status = str(response.raw.get("cost_status") or ("exact" if response.cost_usd > 0 else cost_estimate.status))
        context.budget.reserve(response.prompt_tokens, response.completion_tokens, cost_usd)
        context.recorder.metrics.observe("agentmesh_model_latency_ms", latency_ms, {"agent": self.name})
        context.recorder.event(
            context.trace_id,
            "model.response",
            self.name,
            {
                "provider": self.model_provider.name,
                "model": response.model,
                "prompt_id": prompt_id,
                "prompt_version": prompt_id,
                "output": response.text,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "cached_tokens": cached_tokens,
                "reasoning_tokens": reasoning_tokens,
                "total_tokens": response.prompt_tokens + response.completion_tokens,
                "cost_usd": cost_usd,
                "estimated_cost": cost_usd,
                "cost_status": cost_status,
                "cost_source": str(response.raw.get("cost_source") or cost_estimate.source),
                "cost_notes": str(response.raw.get("cost_notes") or cost_estimate.notes),
                "request_id": str(response.raw.get("request_id") or response.raw.get("id") or ""),
                "latency_ms": latency_ms,
                "temperature": request.temperature,
                "top_p": request.top_p,
                "max_tokens": request.max_tokens,
                "metadata": request.metadata,
            },
            parent_span_id=span_id,
        )
        result = AgentResult(agent=self.name, output=response.text, model_response=response, tool_results=tool_results)
        context.recorder.event(
            context.trace_id,
            "agent.finished",
            self.name,
            result.to_json(),
            parent_span_id=span_id,
        )
        return result

    async def _run_tools(self, message: AgentMessage, context: object) -> list[JsonObject]:
        calls: list[ToolCallRequest] = []
        raw_calls = message.payload.get("tool_calls", [])
        if isinstance(raw_calls, list):
            for raw_call in raw_calls:
                if isinstance(raw_call, dict):
                    arguments_value = raw_call.get("arguments", {})
                    arguments = arguments_value if isinstance(arguments_value, dict) else {}
                    calls.append(ToolCallRequest(name=str(raw_call.get("name", "")), arguments=safe_json(arguments)))
        tool_context = ToolContext(
            trace_id=context.trace_id,
            agent_name=self.name,
            permissions=self.permissions,
            recorder=context.recorder,
            store=context.store,
            parent_span_id=getattr(context, "active_agent_span_id", None),
            approval_callback=context.approval_callback,
        )

        async def _run_one(call: ToolCallRequest) -> JsonObject:
            result = await self.tools.execute(call.name, call.arguments, tool_context)
            return {"name": call.name, "arguments": call.arguments, "result": safe_json(result)}

        # Run independent tool calls concurrently; approval-gated tools still
        # serialize inside ToolRegistry.execute via the approval callback.
        results: list[JsonObject] = list(await asyncio.gather(*(_run_one(call) for call in calls)))
        return results

    def _build_prompt(self, message: AgentMessage, tool_results: list[JsonObject], context: object) -> str:
        payload = message.payload
        lines = [
            f"Agent: {self.name}",
            f"Role: {self.role}",
            f"Task: {payload.get('task', '')}",
            f"Input: {safe_json(payload.get('input', {}))}",
            f"Workflow input: {safe_json(payload.get('workflow_input', {}))}",
            f"Previous outputs: {safe_json(payload.get('previous_outputs', {}))}",
        ]
        if tool_results:
            lines.append(f"Tool results: {tool_results}")
        memory_value: JsonValue = context.workflow_memory.to_json()
        lines.append(f"Workflow memory: {memory_value}")
        lines.append("Return a concise, useful result for the next agent or user.")
        return "\n".join(lines)


def _metadata_payload(value: object) -> JsonObject:
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    return {}


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
