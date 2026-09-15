import { randomBytes } from "node:crypto";

import type { AttributeValue } from "./types.js";

export function randomHex(bytes: number): string {
  return randomBytes(bytes).toString("hex");
}

/** Wall-clock time in nanoseconds since the epoch, with sub-millisecond precision from the monotonic clock. */
export function nowUnixNano(): string {
  const ms = performance.timeOrigin + performance.now();
  const whole = Math.floor(ms);
  const fraction = Math.round((ms - whole) * 1_000_000);
  return (BigInt(whole) * 1_000_000n + BigInt(fraction)).toString();
}

/** Strings pass through; everything else becomes JSON (circular references and bigints are handled). */
export function serialize(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined) return "null";
  const seen = new WeakSet<object>();
  try {
    return JSON.stringify(value, (_key, item) => {
      if (typeof item === "bigint") return item.toString();
      if (item instanceof Error) return { name: item.name, message: item.message };
      if (item instanceof Map) return Object.fromEntries(item);
      if (item instanceof Set) return [...item];
      if (typeof item === "object" && item !== null) {
        if (seen.has(item)) return "[Circular]";
        seen.add(item);
      }
      return item;
    }) ?? String(value);
  } catch {
    return String(value);
  }
}

export function toAttributeValue(value: unknown): AttributeValue | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : String(value);
  if (typeof value === "bigint") return value.toString();
  if (Array.isArray(value) && value.length > 0) {
    const first = typeof value[0];
    if ((first === "string" || first === "number" || first === "boolean") && value.every((item) => typeof item === first)) {
      return value as AttributeValue;
    }
  }
  return serialize(value);
}

export function envFlag(name: string, fallback: boolean): boolean {
  const raw = env(name);
  if (raw === undefined || raw === "") return fallback;
  return !["0", "false", "no", "off"].includes(raw.trim().toLowerCase());
}

export function env(name: string): string | undefined {
  return typeof process !== "undefined" ? process.env?.[name] : undefined;
}

export function isPromiseLike(value: unknown): value is PromiseLike<unknown> {
  return typeof value === "object" && value !== null && typeof (value as { then?: unknown }).then === "function";
}

export function isAsyncIterable(value: unknown): value is AsyncIterable<unknown> {
  return typeof value === "object" && value !== null && typeof (value as Record<symbol, unknown>)[Symbol.asyncIterator] === "function";
}

/** Run a callback and swallow errors: instrumentation must never break the application. */
export function safely(callback: () => void): void {
  try {
    callback();
  } catch (error) {
    debug("instrumentation callback failed", error);
  }
}

export function debug(message: string, error?: unknown): void {
  if (envFlag("AGENTMESH_DEBUG", false)) {
    console.warn(`[agentmesh] ${message}`, error ?? "");
  }
}
