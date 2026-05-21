from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from agentmesh.errors import AgentMeshError, ErrorKind, PermissionDenied, classify_error
from agentmesh.types import JsonObject, JsonValue, safe_json


class PermissionLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SENSITIVE = "sensitive"


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: JsonObject = field(default_factory=dict)
    permission: PermissionLevel = PermissionLevel.READ
    requires_approval: bool = False
    timeout_seconds: float = 30.0

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "permission": self.permission.value,
            "requires_approval": self.requires_approval,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(slots=True)
class ToolContext:
    trace_id: str
    agent_name: str
    permissions: set[PermissionLevel]
    recorder: object
    store: object
    parent_span_id: str | None = None
    approval_callback: Callable[[ToolDefinition, JsonObject, "ToolContext"], Awaitable[bool] | bool] | None = None


ToolFunction = Callable[[JsonObject, ToolContext], Awaitable[JsonValue] | JsonValue]


@dataclass(slots=True)
class Tool:
    definition: ToolDefinition
    handler: ToolFunction

    async def run(self, arguments: JsonObject, context: ToolContext) -> JsonValue:
        maybe_result = self.handler(arguments, context)
        if inspect.isawaitable(maybe_result):
            return safe_json(await maybe_result)
        return safe_json(maybe_result)


def tool(
    name: str,
    description: str,
    input_schema: JsonObject | None = None,
    permission: PermissionLevel = PermissionLevel.READ,
    requires_approval: bool = False,
    timeout_seconds: float = 30.0,
) -> Callable[[ToolFunction], Tool]:
    def decorator(func: ToolFunction) -> Tool:
        return Tool(
            ToolDefinition(
                name=name,
                description=description,
                input_schema=input_schema or {},
                permission=permission,
                requires_approval=requires_approval,
                timeout_seconds=timeout_seconds,
            ),
            func,
        )

    return decorator


class MCPToolClient(Protocol):
    async def call_tool(self, name: str, arguments: JsonObject) -> JsonValue:
        raise NotImplementedError


class MCPToolProxy(Tool):
    def __init__(
        self,
        name: str,
        description: str,
        client: MCPToolClient,
        input_schema: JsonObject | None = None,
        permission: PermissionLevel = PermissionLevel.READ,
        requires_approval: bool = False,
    ) -> None:
        async def handler(arguments: JsonObject, context: ToolContext) -> JsonValue:
            return await client.call_tool(name, arguments)

        super().__init__(
            ToolDefinition(name, description, input_schema or {}, permission, requires_approval),
            handler,
        )


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for item in tools or []:
            self.register(item)

    def register(self, item: Tool) -> None:
        self._tools[item.definition.name] = item

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise AgentMeshError(f"Unknown tool: {name}", ErrorKind.TOOL, {"tool": name}, retryable=False)
        return self._tools[name]

    def list(self) -> list[JsonObject]:
        return [item.definition.to_json() for item in self._tools.values()]

    async def execute(self, name: str, arguments: JsonObject, context: ToolContext) -> JsonValue:
        item = self.get(name)
        definition = item.definition
        if definition.permission not in context.permissions:
            raise PermissionDenied(
                f"Tool '{name}' requires permission '{definition.permission.value}'",
                {"tool": name, "permission": definition.permission.value},
            )
        if definition.requires_approval:
            approval_id = None
            if hasattr(context.store, "create_approval"):
                approval_id = context.store.create_approval(context.trace_id, context.agent_name, name, arguments)
                context.recorder.event(
                    context.trace_id,
                    "approval.requested",
                    context.agent_name,
                    {"approval_id": approval_id, "tool": definition.to_json(), "arguments": arguments},
                    parent_span_id=context.parent_span_id,
                )
            if context.approval_callback is None:
                raise PermissionDenied(
                    f"Tool '{name}' requires approval but no approval callback is configured",
                    {"approval_id": approval_id or ""},
                )
            decision = context.approval_callback(definition, arguments, context)
            approved = await decision if inspect.isawaitable(decision) else decision
            if approval_id is not None and hasattr(context.store, "resolve_approval"):
                context.store.resolve_approval(approval_id, approved)
                context.recorder.event(
                    context.trace_id,
                    "approval.resolved",
                    context.agent_name,
                    {"approval_id": approval_id, "approved": approved, "tool": name},
                    parent_span_id=context.parent_span_id,
                )
            if not approved:
                raise PermissionDenied(f"Tool '{name}' was rejected by human approval", {"approval_id": approval_id or ""})
        recorder = context.recorder
        span_id = recorder.event(
            context.trace_id,
            "tool.started",
            context.agent_name,
            {"tool": definition.to_json(), "arguments": arguments},
            parent_span_id=context.parent_span_id,
        )
        try:
            result = await asyncio.wait_for(item.run(arguments, context), timeout=definition.timeout_seconds)
        except Exception as exc:
            classified = classify_error(exc)
            recorder.event(
                context.trace_id,
                "tool.failed",
                context.agent_name,
                {"tool": name, "error": classified.to_json()},
                parent_span_id=span_id,
            )
            raise classified
        recorder.event(
            context.trace_id,
            "tool.finished",
            context.agent_name,
            {"tool": name, "result": safe_json(result)},
            parent_span_id=span_id,
        )
        context.store.audit(context.trace_id, context.agent_name, "tool.execute", name, {"arguments": arguments})
        return result
