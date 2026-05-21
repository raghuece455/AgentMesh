from __future__ import annotations

from dataclasses import dataclass, field

from agentmesh.dependencies import optional_import
from agentmesh.types import JsonObject, safe_json


@dataclass(slots=True)
class OpenTelemetryBridge:
    service_name: str = "agentmesh"
    tracer_name: str = "agentmesh.runtime"
    _trace: object = field(init=False, repr=False)
    _tracer: object = field(init=False, repr=False)

    def __post_init__(self) -> None:
        trace = optional_import("opentelemetry.trace", "otel")
        self._trace = trace
        self._tracer = trace.get_tracer(self.tracer_name)

    def record_event(
        self,
        trace_id: str,
        span_id: str,
        event_type: str,
        actor: str,
        payload: JsonObject,
        parent_span_id: str | None = None,
    ) -> None:
        attributes: dict[str, str | int | float | bool] = {
            "agentmesh.trace_id": trace_id,
            "agentmesh.span_id": span_id,
            "agentmesh.event_type": event_type,
            "agentmesh.actor": actor,
        }
        if parent_span_id is not None:
            attributes["agentmesh.parent_span_id"] = parent_span_id
        with self._tracer.start_as_current_span(event_type, attributes=attributes) as span:
            for key, value in safe_json(payload).items():
                if isinstance(value, str | int | float | bool):
                    span.set_attribute(f"agentmesh.payload.{key}", value)
                else:
                    span.set_attribute(f"agentmesh.payload.{key}", str(value))


def configure_opentelemetry(
    service_name: str = "agentmesh",
    otlp_endpoint: str | None = None,
    console: bool = False,
) -> OpenTelemetryBridge:
    trace = optional_import("opentelemetry.trace", "otel")
    sdk_trace = optional_import("opentelemetry.sdk.trace", "otel")
    resources = optional_import("opentelemetry.sdk.resources", "otel")
    export = optional_import("opentelemetry.sdk.trace.export", "otel")

    resource = resources.Resource.create({"service.name": service_name})
    provider = sdk_trace.TracerProvider(resource=resource)
    if otlp_endpoint:
        otlp_exporter_module = optional_import("opentelemetry.exporter.otlp.proto.http.trace_exporter", "otel")
        exporter = otlp_exporter_module.OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(export.BatchSpanProcessor(exporter))
    if console:
        provider.add_span_processor(export.SimpleSpanProcessor(export.ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return OpenTelemetryBridge(service_name=service_name)
