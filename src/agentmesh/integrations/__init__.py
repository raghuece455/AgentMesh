"""Auto-instrumentation for popular LLM client libraries.

Frameworks that already emit OpenTelemetry (OpenAI Agents SDK via
OpenInference, Pydantic AI / Logfire, LangGraph, CrewAI, Vercel AI SDK, ...)
don't need these: point their OTLP exporter at ``http://<agentmesh>/v1/traces``.
"""

from agentmesh.integrations.anthropic_sdk import instrument_anthropic, uninstrument_anthropic
from agentmesh.integrations.openai_sdk import instrument_openai, uninstrument_openai

__all__ = ["instrument_anthropic", "instrument_openai", "uninstrument_anthropic", "uninstrument_openai"]
