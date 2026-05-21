from __future__ import annotations

from dataclasses import dataclass, field

from agentmesh.reliability import RetryPolicy
from agentmesh.types import JsonObject, new_id


@dataclass(slots=True)
class ToolCallRequest:
    name: str
    arguments: JsonObject = field(default_factory=dict)

    def to_json(self) -> JsonObject:
        return {"name": self.name, "arguments": self.arguments}


@dataclass(slots=True)
class Task:
    description: str
    input: JsonObject = field(default_factory=dict)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)
    timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    id: str = field(default_factory=lambda: new_id("task"))

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "description": self.description,
            "input": self.input,
            "tool_calls": [call.to_json() for call in self.tool_calls],
            "metadata": self.metadata,
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": self.retry_policy.to_json(),
        }

