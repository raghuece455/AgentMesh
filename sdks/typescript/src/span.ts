import { AsyncLocalStorage } from "node:async_hooks";

import { getClient } from "./client.js";
import type { Attributes, SpanEvent, SpanKind, SpanStatus } from "./types.js";
import { nowUnixNano, randomHex, serialize, toAttributeValue } from "./util.js";

const KIND_OPERATION: Partial<Record<SpanKind, string>> = {
  agent: "invoke_agent",
  tool: "execute_tool",
  llm: "chat",
  embedding: "embeddings",
  retrieval: "retrieval",
  workflow: "invoke_workflow",
};

const OPENINFERENCE_KIND: Partial<Record<SpanKind, string>> = {
  agent: "AGENT",
  tool: "TOOL",
  llm: "LLM",
  embedding: "EMBEDDING",
  retrieval: "RETRIEVER",
  guardrail: "GUARDRAIL",
  evaluator: "EVALUATOR",
};

interface Frame {
  span?: Span;
  /** Trace-level attributes (session, user, tags) shared by every span started inside a trace. */
  trace: Attributes;
}

const storage = new AsyncLocalStorage<Frame>();

export interface SpanOptions {
  kind?: SpanKind;
  input?: unknown;
  attributes?: Record<string, unknown>;
  /** Parent span. Defaults to the active span; pass null to start a new trace. */
  parent?: Span | null;
}

export interface ModelOptions {
  provider?: string;
  responseModel?: string;
  temperature?: number;
  topP?: number;
  maxTokens?: number;
}

export interface Usage {
  /** Total input tokens, including cached tokens (OpenTelemetry GenAI convention). */
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  reasoningTokens?: number;
  costUsd?: number;
}

/** A unit of work. Create with `span()`, `trace()`, `observe()`, or `startSpan()`. */
export class Span {
  readonly traceId: string;
  readonly spanId: string;
  readonly parentSpanId?: string;
  readonly kind: SpanKind;
  readonly startTimeUnixNano: string;
  name: string;
  attributes: Attributes = {};
  events: SpanEvent[] = [];
  status: SpanStatus = "unset";
  statusMessage?: string;
  endTimeUnixNano?: string;
  /** @internal trace attributes this span shares with its descendants */
  readonly traceAttributes: Attributes;

  constructor(name: string, options: SpanOptions & { traceAttributes?: Record<string, unknown> } = {}) {
    const frame = storage.getStore();
    const parent = options.parent === undefined ? frame?.span : options.parent ?? undefined;
    this.name = name;
    this.kind = options.kind ?? "chain";
    this.traceId = parent?.traceId ?? randomHex(16);
    this.spanId = randomHex(8);
    this.parentSpanId = parent?.spanId;
    this.startTimeUnixNano = nowUnixNano();
    const inherited = options.parent === null ? {} : (parent?.traceAttributes ?? frame?.trace ?? {});
    this.traceAttributes = options.traceAttributes ? { ...inherited } : inherited;
    for (const [key, value] of Object.entries(options.traceAttributes ?? {})) {
      const converted = toAttributeValue(value);
      if (converted !== undefined) this.traceAttributes[key] = converted;
    }

    const operation = KIND_OPERATION[this.kind];
    if (operation) this.attributes["gen_ai.operation.name"] = operation;
    const openInference = OPENINFERENCE_KIND[this.kind];
    if (openInference) this.attributes["openinference.span.kind"] = openInference;
    if (this.kind === "agent") this.attributes["gen_ai.agent.name"] = name;
    if (this.kind === "tool") this.attributes["gen_ai.tool.name"] = name;
    if (this.kind === "workflow") this.attributes["gen_ai.workflow.name"] = name;
    this.setAttributes(this.traceAttributes);
    this.setAttributes(options.attributes ?? {});
    if (options.input !== undefined) this.setInput(options.input);
  }

  setAttribute(key: string, value: unknown): this {
    const converted = toAttributeValue(value);
    if (converted !== undefined) this.attributes[key] = converted;
    return this;
  }

  setAttributes(values: Record<string, unknown>): this {
    for (const [key, value] of Object.entries(values)) this.setAttribute(key, value);
    return this;
  }

  setInput(value: unknown): this {
    if (captureContent()) {
      this.attributes["input.value"] = serialize(value);
      if (this.kind === "tool") this.attributes["gen_ai.tool.call.arguments"] = this.attributes["input.value"];
    }
    return this;
  }

  setOutput(value: unknown): this {
    if (captureContent()) {
      this.attributes["output.value"] = serialize(value);
      if (this.kind === "tool") this.attributes["gen_ai.tool.call.result"] = this.attributes["output.value"];
    }
    return this;
  }

  setModel(model: string, options: ModelOptions = {}): this {
    return this.setAttributes({
      "gen_ai.request.model": model,
      "gen_ai.response.model": options.responseModel,
      "gen_ai.provider.name": options.provider,
      "gen_ai.request.temperature": options.temperature,
      "gen_ai.request.top_p": options.topP,
      "gen_ai.request.max_tokens": options.maxTokens,
    });
  }

  setUsage(usage: Usage): this {
    return this.setAttributes({
      "gen_ai.usage.input_tokens": usage.inputTokens,
      "gen_ai.usage.output_tokens": usage.outputTokens,
      "gen_ai.usage.cache_read.input_tokens": usage.cacheReadTokens,
      "gen_ai.usage.cache_write.input_tokens": usage.cacheWriteTokens,
      "gen_ai.usage.reasoning.output_tokens": usage.reasoningTokens,
      "agentmesh.cost_usd": usage.costUsd,
    });
  }

  addEvent(name: string, attributes: Record<string, unknown> = {}): this {
    const converted: Attributes = {};
    for (const [key, value] of Object.entries(attributes)) {
      const item = toAttributeValue(value);
      if (item !== undefined) converted[key] = item;
    }
    this.events.push({ name, timeUnixNano: nowUnixNano(), attributes: converted });
    return this;
  }

  recordException(error: unknown): this {
    const type = error instanceof Error ? error.name || error.constructor.name : typeof error;
    const message = error instanceof Error ? error.message : String(error);
    this.addEvent("exception", {
      "exception.type": type,
      "exception.message": message,
      "exception.stacktrace": error instanceof Error && error.stack ? error.stack.slice(-8000) : undefined,
    });
    this.attributes["error.type"] = type;
    return this.setStatus("error", message || type);
  }

  setStatus(status: SpanStatus, message?: string): this {
    this.status = status;
    this.statusMessage = message;
    return this;
  }

  /** Attach a score to this span. */
  score(name: string, value: number | boolean | string, options: { comment?: string; label?: string } = {}): void {
    getClient().score({
      trace_id: this.traceId,
      span_id: this.spanId,
      name,
      value,
      comment: options.comment ?? null,
      label: options.label ?? null,
      source: "sdk",
    });
  }

  get ended(): boolean {
    return this.endTimeUnixNano !== undefined;
  }

  end(): void {
    if (this.endTimeUnixNano !== undefined) return;
    this.endTimeUnixNano = nowUnixNano();
    getClient().onEnd({
      traceId: this.traceId,
      spanId: this.spanId,
      parentSpanId: this.parentSpanId,
      name: this.name,
      kind: this.kind === "llm" || this.kind === "embedding" ? "CLIENT" : "INTERNAL",
      startTimeUnixNano: this.startTimeUnixNano,
      endTimeUnixNano: this.endTimeUnixNano,
      status: this.status,
      statusMessage: this.statusMessage,
      attributes: { ...this.attributes },
      events: [...this.events],
    });
  }
}

/** Run `fn` with `span` as the active span (without ending it). */
export function withActiveSpan<T>(span: Span, fn: () => T): T {
  return storage.run({ span, trace: span.traceAttributes }, fn);
}

export function getCurrentSpan(): Span | undefined {
  return storage.getStore()?.span;
}

export function currentTraceAttributes(): Attributes | undefined {
  return storage.getStore()?.trace;
}

export function captureContent(): boolean {
  return getClient().config.captureContent;
}
