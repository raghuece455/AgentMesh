import { encodeSpans } from "./otlp.js";
import type { Attributes, Exporter, ScorePayload, SpanData } from "./types.js";
import { debug, env, envFlag } from "./util.js";
import { VERSION } from "./version.js";

export interface InitOptions {
  /** AgentMesh server (or any OTLP/HTTP JSON receiver). Default: AGENTMESH_ENDPOINT or http://127.0.0.1:8787 */
  endpoint?: string;
  /** Sent as a Bearer token. Default: AGENTMESH_API_KEY */
  apiKey?: string;
  /** Default: AGENTMESH_SERVICE_NAME, OTEL_SERVICE_NAME, or "agentmesh-app" */
  serviceName?: string;
  /** Default: AGENTMESH_ENVIRONMENT */
  environment?: string;
  /** Set false (or AGENTMESH_TRACING_ENABLED=false) to turn tracing into a no-op. */
  enabled?: boolean;
  /** Record inputs, outputs, and prompts. Default: AGENTMESH_CAPTURE_CONTENT or true */
  captureContent?: boolean;
  flushIntervalMs?: number;
  maxBatchSize?: number;
  /** Spans beyond this many unsent ones are dropped instead of growing memory. */
  maxQueueSize?: number;
  /** Extra HTTP headers for every request. */
  headers?: Record<string, string>;
  /** Replace the HTTP exporter, e.g. with an InMemoryExporter in tests. */
  exporter?: Exporter;
}

export interface ClientConfig {
  endpoint: string;
  apiKey?: string;
  serviceName: string;
  environment?: string;
  enabled: boolean;
  captureContent: boolean;
  flushIntervalMs: number;
  maxBatchSize: number;
  maxQueueSize: number;
  headers: Record<string, string>;
}

const MAX_BODY_BYTES = 16 * 1024 * 1024;

/** Sends OTLP/JSON to an AgentMesh server. */
export class HttpExporter implements Exporter {
  constructor(
    readonly endpoint: string,
    readonly apiKey?: string,
    readonly headers: Record<string, string> = {},
    readonly timeoutMs = 10_000,
  ) {
    this.endpoint = endpoint.replace(/\/+$/, "");
  }

  async export(spans: SpanData[], resource: Attributes): Promise<void> {
    const body = JSON.stringify(encodeSpans(spans, resource, VERSION));
    if (body.length > MAX_BODY_BYTES && spans.length > 1) {
      const middle = Math.floor(spans.length / 2);
      await this.export(spans.slice(0, middle), resource);
      await this.export(spans.slice(middle), resource);
      return;
    }
    await this.request("POST", "/v1/traces", body);
  }

  async sendScore(score: ScorePayload): Promise<void> {
    await this.request("POST", "/api/scores", JSON.stringify(score));
  }

  async request(method: string, path: string, body?: string): Promise<unknown> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      "User-Agent": `agentmesh-typescript-sdk/${VERSION}`,
      ...this.headers,
    };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.apiKey) headers.Authorization = `Bearer ${this.apiKey}`;
    let lastError: unknown;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await fetch(`${this.endpoint}${path}`, {
          method,
          headers,
          body,
          signal: AbortSignal.timeout(this.timeoutMs),
        });
        const text = await response.text();
        // A success is final even when the body is not JSON (a proxy's "OK"); retrying would send the spans twice.
        if (response.ok) return parseBody(text);
        const error = new AgentMeshHttpError(response.status, `${method} ${path} failed with HTTP ${response.status}: ${text.slice(0, 300)}`);
        if (response.status < 500 && response.status !== 429) throw error;
        lastError = error;
      } catch (error) {
        if (error instanceof AgentMeshHttpError && error.status < 500 && error.status !== 429) throw error;
        lastError = error;
      }
      if (attempt === 0) await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw lastError;
  }
}

function parseBody(text: string): unknown {
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

export class AgentMeshHttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "AgentMeshHttpError";
  }
}

/** Keeps spans and scores in memory. Useful in tests. */
export class InMemoryExporter implements Exporter {
  readonly spans: SpanData[] = [];
  readonly scores: ScorePayload[] = [];
  resource: Attributes = {};

  async export(spans: SpanData[], resource: Attributes): Promise<void> {
    this.resource = resource;
    this.spans.push(...spans);
  }

  async sendScore(score: ScorePayload): Promise<void> {
    this.scores.push(score);
  }

  clear(): void {
    this.spans.length = 0;
    this.scores.length = 0;
  }
}

class NoopExporter implements Exporter {
  async export(): Promise<void> {}
  async sendScore(): Promise<void> {}
}

export class AgentMeshClient {
  readonly config: ClientConfig;
  readonly resource: Attributes;
  readonly exporter: Exporter;
  private spans: SpanData[] = [];
  private scores: ScorePayload[] = [];
  private timer: ReturnType<typeof setTimeout> | undefined;
  private tail: Promise<void> = Promise.resolve();
  private dropped = 0;

  constructor(options: InitOptions = {}) {
    this.config = {
      endpoint: options.endpoint ?? env("AGENTMESH_ENDPOINT") ?? "http://127.0.0.1:8787",
      apiKey: options.apiKey ?? (env("AGENTMESH_API_KEY") || undefined),
      serviceName: options.serviceName ?? env("AGENTMESH_SERVICE_NAME") ?? env("OTEL_SERVICE_NAME") ?? "agentmesh-app",
      environment: options.environment ?? (env("AGENTMESH_ENVIRONMENT") || undefined),
      enabled: options.enabled ?? envFlag("AGENTMESH_TRACING_ENABLED", true),
      captureContent: options.captureContent ?? envFlag("AGENTMESH_CAPTURE_CONTENT", true),
      flushIntervalMs: options.flushIntervalMs ?? 1000,
      maxBatchSize: options.maxBatchSize ?? 512,
      maxQueueSize: options.maxQueueSize ?? 10_000,
      headers: options.headers ?? {},
    };
    this.resource = {
      "service.name": this.config.serviceName,
      "telemetry.sdk.name": "agentmesh",
      "telemetry.sdk.language": "nodejs",
      "telemetry.sdk.version": VERSION,
    };
    if (this.config.environment) this.resource["deployment.environment.name"] = this.config.environment;
    this.exporter =
      options.exporter ??
      (this.config.enabled
        ? new HttpExporter(this.config.endpoint, this.config.apiKey, this.config.headers)
        : new NoopExporter());
  }

  onEnd(span: SpanData): void {
    if (!this.config.enabled) return;
    if (this.spans.length >= this.config.maxQueueSize) {
      this.dropped += 1;
      return;
    }
    this.spans.push(span);
    if (this.spans.length >= this.config.maxBatchSize) {
      void this.flush();
    } else {
      this.schedule();
    }
  }

  score(payload: ScorePayload): void {
    if (!this.config.enabled) return;
    this.scores.push(payload);
    this.schedule();
  }

  /** Send everything queued. Resolves once the exporter has finished (errors are logged, never thrown). */
  async flush(): Promise<void> {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    while (this.spans.length || this.scores.length) {
      const batch = this.spans.splice(0, this.config.maxBatchSize);
      // Scores go after the spans of the same flush so the server can link them to their trace.
      const scores = this.spans.length ? [] : this.scores.splice(0);
      // Sends run one after another, in the order spans ended.
      this.tail = this.tail.then(() => this.send(batch, scores));
    }
    await this.tail;
    if (this.dropped) {
      debug(`dropped ${this.dropped} spans because the queue was full`);
      this.dropped = 0;
    }
  }

  async shutdown(): Promise<void> {
    await this.flush();
    await this.exporter.shutdown?.();
  }

  private async send(batch: SpanData[], scores: ScorePayload[]): Promise<void> {
    if (batch.length) {
      try {
        await this.exporter.export(batch, this.resource);
      } catch (error) {
        debug(`failed to export ${batch.length} spans`, error);
      }
    }
    for (const score of scores) {
      try {
        await this.exporter.sendScore(score);
      } catch (error) {
        debug(`failed to send score ${score.name}`, error);
      }
    }
  }

  private schedule(): void {
    if (this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.flush();
    }, this.config.flushIntervalMs);
    (this.timer as { unref?: () => void }).unref?.();
  }
}

let current: AgentMeshClient | undefined;
let exitHookInstalled = false;

/** Configure tracing. Every option falls back to an environment variable. */
export function init(options: InitOptions = {}): AgentMeshClient {
  const previous = current;
  current = new AgentMeshClient(options);
  if (previous) void previous.shutdown();
  installExitHook();
  return current;
}

/** The configured client; initializes from environment variables on first use. */
export function getClient(): AgentMeshClient {
  return current ?? init();
}

/** Wait until queued spans and scores are sent. Call before a short-lived process (or serverless handler) returns. */
export async function flush(): Promise<void> {
  await current?.flush();
}

export async function shutdown(): Promise<void> {
  await current?.shutdown();
}

function installExitHook(): void {
  if (exitHookInstalled || typeof process === "undefined" || typeof process.once !== "function") return;
  exitHookInstalled = true;
  process.once("beforeExit", () => {
    void current?.flush();
  });
}
