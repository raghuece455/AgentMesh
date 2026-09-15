"""OTLP/HTTP trace encoding and decoding.

AgentMesh accepts ``POST /v1/traces`` with either ``application/json`` (always
available) or ``application/x-protobuf`` (requires the ``otlp`` extra:
``pip install "agentmesh-ai[otlp]"``). Any OpenTelemetry SDK or Collector can
therefore export straight into AgentMesh.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import zlib
from typing import Any

from agentmesh.ingest import SpanData, iso_from_unix_nano
from agentmesh.types import JsonObject

_HEX_TRACE = re.compile(r"^[0-9a-fA-F]{32}$")
_HEX_SPAN = re.compile(r"^[0-9a-fA-F]{16}$")
_STATUS = {
    0: "unset",
    1: "ok",
    2: "error",
    "STATUS_CODE_UNSET": "unset",
    "STATUS_CODE_OK": "ok",
    "STATUS_CODE_ERROR": "error",
}
_KINDS = {
    0: "UNSPECIFIED",
    1: "INTERNAL",
    2: "SERVER",
    3: "CLIENT",
    4: "PRODUCER",
    5: "CONSUMER",
}
_KIND_TO_OTLP = {"INTERNAL": 1, "SERVER": 2, "CLIENT": 3, "PRODUCER": 4, "CONSUMER": 5}


DEFAULT_MAX_REQUEST_BYTES = 32 * 1024 * 1024


class OTLPDecodeError(ValueError):
    pass


class OTLPPayloadTooLarge(OTLPDecodeError):
    pass


class ProtobufUnavailable(RuntimeError):
    pass


def max_request_bytes() -> int:
    """Largest accepted request body, before and after decompression (``AGENTMESH_MAX_OTLP_BYTES``)."""
    try:
        return max(int(os.getenv("AGENTMESH_MAX_OTLP_BYTES", str(DEFAULT_MAX_REQUEST_BYTES))), 1024)
    except ValueError:
        return DEFAULT_MAX_REQUEST_BYTES


def decompress(body: bytes, content_encoding: str | None, max_bytes: int | None = None) -> bytes:
    limit = max_bytes or max_request_bytes()
    if len(body) > limit:
        raise OTLPPayloadTooLarge(f"Request body exceeds {limit} bytes (AGENTMESH_MAX_OTLP_BYTES)")
    encoding = (content_encoding or "").strip().lower()
    if encoding == "gzip" or body[:2] == b"\x1f\x8b":
        wbits = 16 + zlib.MAX_WBITS
    elif encoding == "deflate":
        wbits = zlib.MAX_WBITS
    else:
        return body
    decompressor = zlib.decompressobj(wbits)
    try:
        # Bounded output: a small compressed body must not expand without limit in memory.
        output = decompressor.decompress(body, limit + 1)
    except zlib.error as exc:
        raise OTLPDecodeError(f"Could not decompress request body: {exc}") from exc
    if len(output) > limit:
        raise OTLPPayloadTooLarge(f"Decompressed request body exceeds {limit} bytes (AGENTMESH_MAX_OTLP_BYTES)")
    if not decompressor.eof:
        raise OTLPDecodeError("Compressed request body is truncated")
    return output


def decode_request(body: bytes, content_type: str | None, content_encoding: str | None = None) -> list[SpanData]:
    raw = decompress(body, content_encoding)
    media_type = (content_type or "application/json").split(";", 1)[0].strip().lower()
    if media_type in {"application/x-protobuf", "application/protobuf"}:
        return decode_protobuf(raw)
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OTLPDecodeError(f"Request body is not valid JSON: {exc}") from exc
    return decode_json(payload)


def protobuf_available() -> bool:
    try:
        import opentelemetry.proto.collector.trace.v1.trace_service_pb2  # noqa: F401
        from google.protobuf import json_format  # noqa: F401
    except ImportError:
        return False
    return True


def decode_protobuf(body: bytes) -> list[SpanData]:
    try:
        from google.protobuf.json_format import MessageToDict
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    except ImportError as exc:
        raise ProtobufUnavailable(
            'OTLP protobuf payloads need the otlp extra: pip install "agentmesh-ai[otlp]". '
            "Alternatively configure your exporter to send http/json."
        ) from exc
    request = ExportTraceServiceRequest()
    try:
        request.ParseFromString(body)
    except Exception as exc:  # google.protobuf.message.DecodeError
        raise OTLPDecodeError(f"Invalid OTLP protobuf payload: {exc}") from exc
    return decode_json(MessageToDict(request))


def decode_json(payload: Any) -> list[SpanData]:
    try:
        return _decode_json(payload)
    except OTLPDecodeError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        # Structurally invalid payloads (e.g. a number where a ResourceSpans object belongs)
        # are client errors, not server failures.
        raise OTLPDecodeError(f"Malformed OTLP payload: {exc}") from exc


def _decode_json(payload: Any) -> list[SpanData]:
    if not isinstance(payload, dict):
        raise OTLPDecodeError("OTLP payload must be a JSON object with resourceSpans")
    spans: list[SpanData] = []
    for resource_spans in _list(payload.get("resourceSpans") or payload.get("resource_spans")):
        resource = _attributes(_dict(resource_spans.get("resource")).get("attributes"))
        for scope_spans in _list(
            resource_spans.get("scopeSpans")
            or resource_spans.get("scope_spans")
            or resource_spans.get("instrumentationLibrarySpans")
        ):
            scope = _dict(scope_spans.get("scope") or scope_spans.get("instrumentationLibrary"))
            scope_name = scope.get("name")
            for raw in _list(scope_spans.get("spans")):
                span = _span(raw, resource, str(scope_name) if scope_name else None)
                if span is not None:
                    spans.append(span)
    return spans


def encode_json(
    spans: list[SpanData], resource: dict[str, Any] | None = None, scope: str = "agentmesh.sdk"
) -> JsonObject:
    """Encode spans as an OTLP/JSON ExportTraceServiceRequest."""
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _encode_attributes(resource or (spans[0].resource if spans else {}))},
                "scopeSpans": [{"scope": {"name": scope}, "spans": [_encode_span(span) for span in spans]}],
            }
        ]
    }


def _span(raw: Any, resource: dict[str, Any], scope: str | None) -> SpanData | None:
    if not isinstance(raw, dict):
        return None
    trace_id = _id(raw.get("traceId") or raw.get("trace_id"), 32)
    span_id = _id(raw.get("spanId") or raw.get("span_id"), 16)
    if not trace_id or not span_id:
        return None
    start = iso_from_unix_nano(raw.get("startTimeUnixNano") or raw.get("start_time_unix_nano"))
    if start is None:
        return None
    status = _dict(raw.get("status"))
    code = status.get("code", 0)
    kind = raw.get("kind", 1)
    return SpanData(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=_id(raw.get("parentSpanId") or raw.get("parent_span_id"), 16),
        name=str(raw.get("name") or "span"),
        kind=_KINDS.get(kind, str(kind).removeprefix("SPAN_KIND_")) if kind is not None else "INTERNAL",
        start_time=start,
        end_time=iso_from_unix_nano(raw.get("endTimeUnixNano") or raw.get("end_time_unix_nano")),
        status=_STATUS.get(code, _STATUS.get(_int_or_str(code), "unset")),
        status_message=str(status["message"]) if status.get("message") else None,
        attributes=_attributes(raw.get("attributes")),
        events=[
            {
                "name": str(event.get("name") or "event"),
                "time": iso_from_unix_nano(event.get("timeUnixNano") or event.get("time_unix_nano")),
                "attributes": _attributes(event.get("attributes")),
            }
            for event in _list(raw.get("events"))
            if isinstance(event, dict)
        ],
        resource=resource,
        scope=scope,
    )


def _id(value: Any, length: int) -> str | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    pattern = _HEX_TRACE if length == 32 else _HEX_SPAN
    if pattern.match(text):
        hex_id = text.lower()
    else:
        try:
            decoded = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            return None
        if len(decoded) != length // 2:
            return None
        hex_id = decoded.hex()
    return None if set(hex_id) == {"0"} else hex_id


def _attributes(raw: Any) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for item in _list(raw):
        if isinstance(item, dict) and "key" in item:
            attributes[str(item["key"])] = _value(item.get("value"))
    return attributes


def _value(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    if "stringValue" in raw or "string_value" in raw:
        return raw.get("stringValue", raw.get("string_value"))
    if "boolValue" in raw or "bool_value" in raw:
        return bool(raw.get("boolValue", raw.get("bool_value")))
    if "intValue" in raw or "int_value" in raw:
        try:
            return int(raw.get("intValue", raw.get("int_value")))
        except (TypeError, ValueError):
            return None
    if "doubleValue" in raw or "double_value" in raw:
        try:
            return float(raw.get("doubleValue", raw.get("double_value")))
        except (TypeError, ValueError):
            return None
    if "arrayValue" in raw or "array_value" in raw:
        array = _dict(raw.get("arrayValue", raw.get("array_value")))
        return [_value(item) for item in _list(array.get("values"))]
    if "kvlistValue" in raw or "kvlist_value" in raw:
        kvlist = _dict(raw.get("kvlistValue", raw.get("kvlist_value")))
        return _attributes(kvlist.get("values"))
    if "bytesValue" in raw or "bytes_value" in raw:
        return raw.get("bytesValue", raw.get("bytes_value"))
    return None


def _encode_span(span: SpanData) -> JsonObject:
    encoded: JsonObject = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "name": span.name,
        "kind": _KIND_TO_OTLP.get(span.kind.upper(), 1),
        "startTimeUnixNano": str(_unix_nano(span.start_time)),
        "endTimeUnixNano": str(_unix_nano(span.end_time or span.start_time)),
        "attributes": _encode_attributes(span.attributes),
        "events": [
            {
                "name": event.get("name", "event"),
                "timeUnixNano": str(_unix_nano(event.get("time") or span.start_time)),
                "attributes": _encode_attributes(event.get("attributes") or {}),
            }
            for event in span.events
        ],
        "status": {"code": {"ok": 1, "error": 2}.get(span.status, 0)},
    }
    if span.parent_span_id:
        encoded["parentSpanId"] = span.parent_span_id
    if span.status_message:
        encoded["status"]["message"] = span.status_message  # type: ignore[index]
    return encoded


def _encode_attributes(values: dict[str, Any]) -> list[JsonObject]:
    return [{"key": key, "value": _encode_value(value)} for key, value in values.items() if value is not None]


def _encode_value(value: Any) -> JsonObject:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list | tuple) and all(isinstance(item, str | int | float | bool) for item in value):
        return {"arrayValue": {"values": [_encode_value(item) for item in value]}}
    return {"stringValue": json.dumps(value, default=str)}


def _unix_nano(value: str | None) -> int:
    from datetime import UTC, datetime

    if not value:
        return 0
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp()) * 1_000_000_000 + moment.microsecond * 1000


def _int_or_str(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
