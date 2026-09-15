import type { AttributeValue, Attributes, SpanData } from "./types.js";

type AnyValue =
  | { stringValue: string }
  | { boolValue: boolean }
  | { intValue: string }
  | { doubleValue: number }
  | { arrayValue: { values: AnyValue[] } };

const SPAN_KIND = { INTERNAL: 1, SERVER: 2, CLIENT: 3 } as const;
const STATUS_CODE = { unset: 0, ok: 1, error: 2 } as const;

/** Encode spans as an OTLP/JSON ExportTraceServiceRequest. */
export function encodeSpans(spans: SpanData[], resource: Attributes, scopeVersion: string): Record<string, unknown> {
  return {
    resourceSpans: [
      {
        resource: { attributes: encodeAttributes(resource) },
        scopeSpans: [
          {
            scope: { name: "agentmesh.sdk.typescript", version: scopeVersion },
            spans: spans.map((span) => ({
              traceId: span.traceId,
              spanId: span.spanId,
              ...(span.parentSpanId ? { parentSpanId: span.parentSpanId } : {}),
              name: span.name,
              kind: SPAN_KIND[span.kind],
              startTimeUnixNano: span.startTimeUnixNano,
              endTimeUnixNano: span.endTimeUnixNano,
              attributes: encodeAttributes(span.attributes),
              events: span.events.map((event) => ({
                name: event.name,
                timeUnixNano: event.timeUnixNano,
                attributes: encodeAttributes(event.attributes),
              })),
              status: {
                code: STATUS_CODE[span.status],
                ...(span.statusMessage ? { message: span.statusMessage } : {}),
              },
            })),
          },
        ],
      },
    ],
  };
}

export function encodeAttributes(attributes: Attributes): Array<{ key: string; value: AnyValue }> {
  return Object.entries(attributes).map(([key, value]) => ({ key, value: encodeValue(value) }));
}

function encodeValue(value: AttributeValue): AnyValue {
  if (Array.isArray(value)) {
    return { arrayValue: { values: (value as Array<string | number | boolean>).map((item) => encodeValue(item)) } };
  }
  if (typeof value === "boolean") return { boolValue: value };
  if (typeof value === "number") {
    return Number.isInteger(value) ? { intValue: String(value) } : { doubleValue: value };
  }
  return { stringValue: String(value) };
}
