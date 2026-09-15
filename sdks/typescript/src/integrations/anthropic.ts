import { captureContent, Span } from "../span.js";
import { safely } from "../util.js";
import { type Accumulator, given, type Handler, unwrapMethod, wrapMethod } from "./common.js";

const WRAPPED_STREAM = Symbol.for("agentmesh.wrapped.stream");

/**
 * Trace `messages.create` (including `stream: true`) and `messages.stream` on an `@anthropic-ai/sdk` client.
 *
 *     import Anthropic from "@anthropic-ai/sdk";
 *     const client = instrumentAnthropic(new Anthropic());
 */
export function instrumentAnthropic<T extends object>(client: T): T {
  const target = client as any;
  const provider = providerFor(target);
  for (const messages of [target.messages, target.beta?.messages]) {
    if (!messages) continue;
    const handler = messagesHandler(provider);
    wrapMethod(messages, "create", handler);
    wrapStreamHelper(messages, handler);
  }
  return client;
}

export function uninstrumentAnthropic(client: object): void {
  const target = client as any;
  for (const messages of [target.messages, target.beta?.messages]) {
    if (!messages) continue;
    unwrapMethod(messages, "create");
    if (messages.stream?.[WRAPPED_STREAM]) messages.stream = messages.stream[WRAPPED_STREAM];
  }
}

function providerFor(client: any): string {
  const name = String(client?.constructor?.name ?? "");
  if (name.includes("Bedrock")) return "aws.bedrock";
  if (name.includes("Vertex")) return "gcp.vertex_ai";
  return "anthropic";
}

function messagesHandler(provider: string): Handler & { accumulator(): Accumulator } {
  const onResponse = (span: Span, message: any) => {
    const usage = message?.usage;
    span.setAttribute("gen_ai.response.model", message?.model);
    span.setAttribute("gen_ai.response.id", message?.id);
    if (message?.stop_reason) span.setAttribute("gen_ai.response.finish_reasons", [String(message.stop_reason)]);
    if (usage) {
      const cacheRead = Number(usage.cache_read_input_tokens ?? 0);
      const cacheWrite = Number(usage.cache_creation_input_tokens ?? 0);
      // Anthropic's input_tokens excludes cache reads and writes; the GenAI convention wants the total.
      span.setUsage({
        inputTokens: Number(usage.input_tokens ?? 0) + cacheRead + cacheWrite,
        outputTokens: usage.output_tokens,
        cacheReadTokens: cacheRead,
        cacheWriteTokens: cacheWrite,
      });
    }
    if (captureContent() && message?.content !== undefined) {
      span.setAttribute("gen_ai.output.messages", [{ role: "assistant", content: message.content }]);
    }
  };
  return {
    start(body) {
      const thinking = given(body, "thinking");
      const span = new Span(`chat ${given(body, "model") ?? "unknown"}`, {
        kind: "llm",
        attributes: {
          "gen_ai.provider.name": provider,
          "gen_ai.request.model": given(body, "model"),
          "gen_ai.request.max_tokens": given(body, "max_tokens"),
          "gen_ai.request.temperature": given(body, "temperature"),
          "gen_ai.request.top_p": given(body, "top_p"),
          "gen_ai.request.top_k": given(body, "top_k"),
          "gen_ai.request.stream": body.stream === true,
          "gen_ai.request.stop_sequences": given(body, "stop_sequences"),
          "gen_ai.request.reasoning.level": thinking?.type,
        },
      });
      if (captureContent()) {
        span.setAttribute("gen_ai.system_instructions", given(body, "system"));
        span.setAttribute("gen_ai.input.messages", given(body, "messages"));
        span.setAttribute("gen_ai.tool.definitions", given(body, "tools"));
      }
      return span;
    },
    onResponse,
    accumulator() {
      const message: Record<string, any> = {};
      const usage: Record<string, any> = {};
      const blocks = new Map<number, Record<string, any>>();
      return {
        add(event: any) {
          switch (event?.type) {
            case "message_start":
              message.id = event.message?.id;
              message.model = event.message?.model;
              Object.assign(usage, event.message?.usage ?? {});
              break;
            case "content_block_start":
              blocks.set(Number(event.index ?? 0), { ...(event.content_block ?? {}) });
              break;
            case "content_block_delta": {
              const index = Number(event.index ?? 0);
              const block = blocks.get(index) ?? { type: "text" };
              blocks.set(index, block);
              const delta = event.delta ?? {};
              for (const [type, field] of [
                ["text_delta", "text"],
                ["input_json_delta", "partial_json"],
                ["thinking_delta", "thinking"],
              ] as const) {
                if (delta.type === type) block[field] = String(block[field] ?? "") + String(delta[field] ?? "");
              }
              break;
            }
            case "message_delta":
              if (event.delta?.stop_reason) message.stop_reason = event.delta.stop_reason;
              for (const [key, value] of Object.entries(event.usage ?? {})) if (value !== null && value !== undefined) usage[key] = value;
              break;
          }
        },
        finish(span) {
          const content = [...blocks.entries()]
            .sort(([a], [b]) => a - b)
            .map(([, block]) => {
              if (block.type === "tool_use" && "partial_json" in block) {
                try {
                  block.input = JSON.parse(block.partial_json || "{}");
                  delete block.partial_json;
                } catch {
                  // keep the raw partial JSON
                }
              }
              return block;
            });
          onResponse(span, { ...message, content, usage });
        },
      };
    },
  };
}

/** `messages.stream()` returns a MessageStream synchronously; finish the span from its events. */
function wrapStreamHelper(messages: any, handler: ReturnType<typeof messagesHandler>): void {
  const original = messages.stream;
  if (typeof original !== "function" || original[WRAPPED_STREAM]) return;
  const wrapped = function (this: unknown, body: Record<string, any> = {}, ...rest: unknown[]) {
    const span = handler.start({ ...body, stream: true });
    let stream: any;
    try {
      stream = original.call(this ?? messages, body, ...rest);
    } catch (error) {
      span.recordException(error);
      span.end();
      throw error;
    }
    if (typeof stream?.on === "function") {
      stream.on("finalMessage", (message: unknown) => {
        safely(() => handler.onResponse(span, message));
        span.end();
      });
      stream.on("error", (error: unknown) => {
        span.recordException(error);
        span.end();
      });
      stream.on("abort", (error: unknown) => {
        span.recordException(error ?? new Error("stream aborted"));
        span.end();
      });
    } else {
      span.end();
    }
    return stream;
  };
  (wrapped as any)[WRAPPED_STREAM] = original;
  messages.stream = wrapped;
}
