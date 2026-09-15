import { Span } from "../span.js";
import { isAsyncIterable, safely } from "../util.js";

const WRAPPED = Symbol.for("agentmesh.wrapped");

export interface Accumulator {
  add(event: unknown): void;
  finish(span: Span): void;
}

export interface Handler {
  start(body: Record<string, any>): Span;
  onResponse(span: Span, response: any): void;
  accumulator?(): Accumulator;
}

/**
 * Replace `resource[method]` with a traced version. The SDK's return value is handed back untouched
 * (an `APIPromise` keeps `.withResponse()` / `.asResponse()`); the span ends when the response or
 * the stream finishes.
 */
export function wrapMethod(resource: any, method: string, handler: Handler): void {
  const original = resource?.[method];
  if (typeof original !== "function" || original[WRAPPED]) return;
  const wrapped = function (this: unknown, body: Record<string, any> = {}, ...rest: unknown[]) {
    const span = handler.start(body ?? {});
    let result: unknown;
    try {
      result = original.call(this ?? resource, body, ...rest);
    } catch (error) {
      span.recordException(error);
      span.end();
      throw error;
    }
    return traceResult(result, span, handler, body?.stream === true);
  };
  (wrapped as any)[WRAPPED] = original;
  resource[method] = wrapped;
}

export function unwrapMethod(resource: any, method: string): void {
  const current = resource?.[method];
  if (current?.[WRAPPED]) resource[method] = current[WRAPPED];
}

function traceResult(result: unknown, span: Span, handler: Handler, streaming: boolean): unknown {
  if (!result || typeof (result as PromiseLike<unknown>).then !== "function") {
    finishWith(span, handler, result, streaming);
    return result;
  }
  const promise = result as Promise<unknown> & Record<string, any>;
  let tracked: Promise<unknown> | undefined;
  const track = (): Promise<unknown> => {
    tracked ??= promise.then(
      (value) => {
        finishWith(span, handler, value, streaming);
        return value;
      },
      (error: unknown) => {
        span.recordException(error);
        span.end();
        throw error;
      },
    );
    return tracked;
  };
  return new Proxy(promise, {
    get(target, property) {
      if (property === "then") return (onFulfilled?: any, onRejected?: any) => track().then(onFulfilled, onRejected);
      if (property === "catch") return (onRejected?: any) => track().catch(onRejected);
      if (property === "finally") return (onFinally?: any) => track().finally(onFinally);
      if (property === "withResponse" && typeof target.withResponse === "function") {
        return () =>
          target.withResponse().then(
            (value: { data: unknown }) => {
              finishWith(span, handler, value.data, streaming);
              return value;
            },
            (error: unknown) => {
              span.recordException(error);
              span.end();
              throw error;
            },
          );
      }
      if (property === "asResponse" && typeof target.asResponse === "function") {
        // The caller reads the raw body, so there is nothing to parse: end with request details only.
        return () =>
          target.asResponse().then(
            (value: unknown) => {
              span.end();
              return value;
            },
            (error: unknown) => {
              span.recordException(error);
              span.end();
              throw error;
            },
          );
      }
      const value = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

function finishWith(span: Span, handler: Handler, value: unknown, streaming: boolean): void {
  if (span.ended) return;
  if (streaming && isAsyncIterable(value) && handler.accumulator) {
    wrapStream(value, span, handler.accumulator());
    return;
  }
  safely(() => handler.onResponse(span, value));
  span.end();
}

const STREAM_WRAPPED = new WeakSet<object>();

/** Observe an SDK stream as the caller iterates it; the span ends when the stream is exhausted, fails, or is abandoned. */
export function wrapStream(stream: AsyncIterable<unknown>, span: Span, accumulator: Accumulator): void {
  if (STREAM_WRAPPED.has(stream)) return;
  STREAM_WRAPPED.add(stream);
  const originalIterator = stream[Symbol.asyncIterator].bind(stream);
  const finish = (error?: unknown) => {
    if (span.ended) return;
    if (error !== undefined) span.recordException(error);
    safely(() => accumulator.finish(span));
    span.end();
  };
  Object.defineProperty(stream, Symbol.asyncIterator, {
    configurable: true,
    writable: true,
    value: () => {
      const iterator = originalIterator();
      return {
        async next(...args: [] | [unknown]) {
          try {
            const step = await iterator.next(...args);
            if (step.done) finish();
            else safely(() => accumulator.add(step.value));
            return step;
          } catch (error) {
            finish(error);
            throw error;
          }
        },
        async return(value?: unknown) {
          finish();
          return iterator.return ? iterator.return(value) : { done: true, value };
        },
        async throw(error?: unknown) {
          finish(error);
          if (iterator.throw) return iterator.throw(error);
          throw error;
        },
        [Symbol.asyncIterator]() {
          return this;
        },
      };
    },
  });
}

export function given(body: Record<string, any>, key: string): any {
  const value = body?.[key];
  return value === undefined || value === null ? undefined : value;
}
