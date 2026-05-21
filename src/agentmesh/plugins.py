from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agentmesh.agents import Agent
from agentmesh.evaluation import Evaluator
from agentmesh.planning import Planner
from agentmesh.providers import ModelProvider
from agentmesh.tools import Tool, ToolRegistry


class AgentMeshPlugin(Protocol):
    name: str

    def register(self, manager: "PluginManager") -> None:
        raise NotImplementedError


@dataclass(slots=True)
class PluginManager:
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    providers: dict[str, ModelProvider] = field(default_factory=dict)
    agents: dict[str, Agent] = field(default_factory=dict)
    planners: dict[str, Planner] = field(default_factory=dict)
    evaluators: dict[str, Evaluator] = field(default_factory=dict)
    loaded_plugins: list[str] = field(default_factory=list)

    def load(self, plugin: AgentMeshPlugin) -> None:
        plugin.register(self)
        self.loaded_plugins.append(plugin.name)

    def register_tool(self, item: Tool) -> None:
        self.tools.register(item)

    def register_provider(self, name: str, provider: ModelProvider) -> None:
        self.providers[name] = provider

    def register_agent(self, agent: Agent) -> None:
        self.agents[agent.name] = agent

    def register_planner(self, planner: Planner) -> None:
        self.planners[planner.name] = planner

    def register_evaluator(self, evaluator: Evaluator) -> None:
        self.evaluators[evaluator.name] = evaluator

