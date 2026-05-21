from __future__ import annotations

from dataclasses import dataclass

from agentmesh.providers import ModelProvider, ModelRequest, ModelResponse


@dataclass(slots=True)
class RouteRule:
    key: str
    provider: ModelProvider
    description: str = ""


class ModelRouter:
    name = "model-router"

    def __init__(self, default_provider: ModelProvider, routes: list[RouteRule] | None = None) -> None:
        self.default_provider = default_provider
        self.routes = {route.key: route for route in routes or []}

    def add_route(self, key: str, provider: ModelProvider, description: str = "") -> None:
        self.routes[key] = RouteRule(key, provider, description)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        route_key = str(request.metadata.get("model_class") or request.metadata.get("task_type") or "default")
        route = self.routes.get(route_key)
        provider = route.provider if route else self.default_provider
        response = await provider.generate(request)
        response.raw["routed_provider"] = provider.name
        response.raw["route_key"] = route_key
        return response

