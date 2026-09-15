import { getClient } from "./client.js";
import { currentTraceAttributes, getCurrentSpan, Span, type SpanOptions, withActiveSpan } from "./span.js";
import type { SpanKind } from "./types.js";
import { isPromiseLike, toAttributeValue } from "./util.js";

const MAX_CAPTURED_ITEMS = 1000;

export interface TraceOptions {
  sessionId?: string;
  userId?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
  input?: unknown;
  kind?: SpanKind;
}

export interface ObserveOptions {
  name?: string;
  kind?: SpanKind;
  captureInput?: boolean;
  captureOutput?: boolean;
  attributes?: Record<string, unknown>;
}

/** Start a span without activating it. Call `span.end()` yourself; use `withActiveSpan` to parent other spans under it. */
export function startSpan(name: string, options: SpanOptions = {}): Span {
  return new Span(name, options);
}

/**
 * Run `fn` inside a new span. The span ends when `fn` returns or its promise settles, and records any error.
 *
 *     const answer = await span("rerank", { kind: "retrieval", input: query }, async (s) => { ... });
 */
export function span<T>(name: string, options: SpanOptions, fn: (span: Span) => T): T;
export function span<T>(name: string, fn: (span: Span) => T): T;
export function span<T>(name: string, optionsOrFn: SpanOptions | ((span: Span) => T), maybeFn?: (span: Span) => T): T {
  const [options, fn] = typeof optionsOrFn === "function" ? [{}, optionsOrFn] : [optionsOrFn, maybeFn!];
  return runInSpan(new Span(name, options), fn, false);
}

/**
 * Start a trace (a root span) and set session, user, and tags for every span inside it.
 *
 *     await trace("support-ticket", { sessionId: "chat-42", userId: "u-7" }, async (root) => { ... });
 */
export function trace<T>(name: string, options: TraceOptions, fn: (span: Span) => T): T;
export function trace<T>(name: string, fn: (span: Span) => T): T;
export function trace<T>(name: string, optionsOrFn: TraceOptions | ((span: Span) => T), maybeFn?: (span: Span) => T): T {
  const [options, fn] = typeof optionsOrFn === "function" ? [{} as TraceOptions, optionsOrFn] : [optionsOrFn, maybeFn!];
  const traceAttributes: Record<string, unknown> = {};
  if (options.sessionId) traceAttributes["gen_ai.conversation.id"] = options.sessionId;
  if (options.userId) traceAttributes["user.id"] = options.userId;
  if (options.tags?.length) traceAttributes["tag.tags"] = [...options.tags];
  const attributes: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(options.metadata ?? {})) attributes[`agentmesh.metadata.${key}`] = value;
  const root = new Span(name, { kind: options.kind ?? "workflow", attributes, input: options.input, traceAttributes });
  return runInSpan(root, fn, false);
}

/**
 * Wrap a function so every call is traced. Works with sync functions, async functions, and async generators.
 *
 *     const searchDocs = observe(async (query: string) => { ... }, { name: "search_docs", kind: "tool" });
 */
export function observe<F extends (...args: any[]) => any>(fn: F, options: ObserveOptions = {}): F {
  const name = options.name ?? (fn.name || "function");
  const wrapped = function (this: unknown, ...args: unknown[]) {
    const created = new Span(name, { kind: options.kind ?? "chain", attributes: options.attributes });
    if (options.captureInput !== false) created.setInput(args.length === 1 ? args[0] : args);
    return runInSpan(created, () => fn.apply(this, args), options.captureOutput !== false);
  };
  Object.defineProperty(wrapped, "name", { value: name });
  return wrapped as unknown as F;
}

/** Set session, user, or tags on the active trace; spans started afterwards inherit them. */
export function updateCurrentTrace(values: { sessionId?: string; userId?: string; tags?: string[] }): void {
  const updates: Record<string, unknown> = {};
  if (values.sessionId) updates["gen_ai.conversation.id"] = values.sessionId;
  if (values.userId) updates["user.id"] = values.userId;
  if (values.tags?.length) updates["tag.tags"] = [...values.tags];
  const shared = currentTraceAttributes();
  for (const [key, value] of Object.entries(updates)) {
    const converted = toAttributeValue(value);
    if (converted !== undefined && shared) shared[key] = converted;
  }
  getCurrentSpan()?.setAttributes(updates);
}

export function getCurrentTraceId(): string | undefined {
  return getCurrentSpan()?.traceId;
}

export interface ScoreOptions {
  traceId?: string;
  spanId?: string;
  comment?: string;
  label?: string;
  passed?: boolean;
  source?: string;
  metadata?: Record<string, unknown>;
}

/** Attach a score (user feedback, eval metric, judge verdict) to the current trace, or to `options.traceId`. */
export function score(name: string, value: number | boolean | string, options: ScoreOptions = {}): void {
  const traceId = options.traceId ?? getCurrentTraceId();
  if (!traceId) {
    console.warn(`[agentmesh] score("${name}") called outside a trace and without traceId; ignored`);
    return;
  }
  getClient().score({
    trace_id: traceId,
    span_id: options.spanId ?? null,
    name,
    value,
    passed: options.passed ?? null,
    comment: options.comment ?? null,
    label: options.label ?? null,
    source: options.source ?? "sdk",
    ...(options.metadata ? { metadata: options.metadata } : {}),
  });
}

function runInSpan<T>(created: Span, fn: (span: Span) => T, captureOutput: boolean): T {
  let result: T;
  try {
    result = withActiveSpan(created, () => fn(created));
  } catch (error) {
    created.recordException(error);
    created.end();
    throw error;
  }
  if (isPromiseLike(result)) {
    return Promise.resolve(result).then(
      (value) => {
        if (captureOutput) created.setOutput(value);
        created.end();
        return value;
      },
      (error: unknown) => {
        created.recordException(error);
        created.end();
        throw error;
      },
    ) as T;
  }
  if (isAsyncGenerator(result)) {
    return tracedGenerator(created, result, captureOutput) as T;
  }
  if (captureOutput) created.setOutput(result);
  created.end();
  return result;
}

function isAsyncGenerator(value: unknown): value is AsyncGenerator<unknown, unknown, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as AsyncGenerator).next === "function" &&
    typeof (value as AsyncGenerator)[Symbol.asyncIterator] === "function"
  );
}

async function* tracedGenerator(created: Span, generator: AsyncGenerator<unknown, unknown, unknown>, captureOutput: boolean) {
  const items: unknown[] = [];
  try {
    while (true) {
      const step = await withActiveSpan(created, () => generator.next());
      if (step.done) break;
      if (items.length < MAX_CAPTURED_ITEMS) items.push(step.value);
      yield step.value;
    }
  } catch (error) {
    created.recordException(error);
    throw error;
  } finally {
    await generator.return?.(undefined);
    if (captureOutput) created.setOutput(items);
    created.end();
  }
}
