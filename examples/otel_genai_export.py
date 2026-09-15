"""Send standard OpenTelemetry GenAI spans to AgentMesh. No AgentMesh code in the app.

This is exactly what OpenTelemetry-instrumented frameworks (OpenAI Agents SDK via OpenInference,
Pydantic AI, LangGraph, CrewAI, Vercel AI SDK, ...) do under the hood.

    pip install "agentmesh-ai[otlp]" opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
    agentmesh dashboard --port 8787          # terminal 1
    python examples/otel_genai_export.py     # terminal 2
"""

import json
import os
import time

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

endpoint = os.getenv("AGENTMESH_OTLP_ENDPOINT", "http://127.0.0.1:8787/v1/traces")
provider = TracerProvider(resource=Resource.create({"service.name": "research-bot", "deployment.environment.name": "dev"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
tracer = provider.get_tracer("example")

conversation = {"gen_ai.conversation.id": "otel-demo-session", "user.id": "analyst-1"}

with tracer.start_as_current_span(
    "invoke_agent researcher",
    attributes={"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "researcher", "input.value": "Summarize Q3", **conversation},
) as root:
    with tracer.start_as_current_span(
        "chat gpt-4.1-mini",
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": "gpt-4.1-mini",
            "gen_ai.input.messages": json.dumps([{"role": "user", "parts": [{"type": "text", "content": "Summarize Q3"}]}]),
        },
    ) as llm:
        time.sleep(0.2)
        llm.set_attributes({"gen_ai.usage.input_tokens": 5_200, "gen_ai.usage.output_tokens": 340, "gen_ai.usage.cache_read.input_tokens": 4_000})

    with tracer.start_as_current_span(
        "execute_tool fetch_report",
        attributes={"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "fetch_report", "gen_ai.tool.call.arguments": '{"quarter": "Q3"}'},
    ) as tool:
        time.sleep(0.1)
        tool.set_status(Status(StatusCode.ERROR, "report service returned 503"))

    root.set_attribute("output.value", "Could not fetch the Q3 report.")
    trace_id = format(root.get_span_context().trace_id, "032x")

provider.shutdown()  # flushes the batch
print(f"Sent trace {trace_id} to {endpoint}")
print(f"Insights: {endpoint.rsplit('/v1/traces', 1)[0]}/api/traces/{trace_id}/insights")
