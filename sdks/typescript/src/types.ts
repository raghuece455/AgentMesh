export type SpanKind =
  | "chain"
  | "agent"
  | "tool"
  | "llm"
  | "embedding"
  | "retrieval"
  | "workflow"
  | "guardrail"
  | "evaluator";

export type AttributeValue = string | number | boolean | string[] | number[] | boolean[];
export type Attributes = Record<string, AttributeValue>;

export type SpanStatus = "unset" | "ok" | "error";

export interface SpanEvent {
  name: string;
  timeUnixNano: string;
  attributes: Attributes;
}

/** A finished span, as handed to exporters. */
export interface SpanData {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  name: string;
  kind: "INTERNAL" | "CLIENT";
  startTimeUnixNano: string;
  endTimeUnixNano: string;
  status: SpanStatus;
  statusMessage?: string;
  attributes: Attributes;
  events: SpanEvent[];
}

export interface ScorePayload {
  trace_id: string;
  span_id?: string | null;
  name: string;
  value: number | boolean | string | null;
  passed?: boolean | null;
  label?: string | null;
  comment?: string | null;
  source?: string;
  metadata?: Record<string, unknown>;
}

export interface Exporter {
  export(spans: SpanData[], resource: Attributes): Promise<void>;
  sendScore(score: ScorePayload): Promise<void>;
  shutdown?(): Promise<void>;
}
