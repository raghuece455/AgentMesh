from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentmesh.task import Task
from agentmesh.types import JsonValue


@dataclass(slots=True)
class PlannedStep:
    agent_name: str
    task: Task
    depends_on: tuple[str, ...] = ()
    trigger: str | None = None
    step_id: str | None = None


class Planner(Protocol):
    name: str

    async def plan(self, input_value: JsonValue) -> list[PlannedStep]:
        raise NotImplementedError


class StaticPlanner:
    name = "static"

    def __init__(self, steps: list[PlannedStep]) -> None:
        self.steps = steps

    async def plan(self, input_value: JsonValue) -> list[PlannedStep]:
        return list(self.steps)

