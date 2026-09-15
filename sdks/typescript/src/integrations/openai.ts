import { captureContent, Span } from "../span.js";
import { type Accumulator, given, type Handler, unwrapMethod, wrapMethod } from "./common.js";

/**
 * Trace Chat Completions, Responses, and Embeddings calls (streaming included) on an `openai` client.
 * Works with OpenAI and OpenAI-compatible endpoints (Azure OpenAI, Groq, OpenRouter, vLLM, Ollama, ...).
 *
 *     import OpenAI from "openai";
 *     const client = instrumentOpenAI(new OpenAI());
 */
export function instrumentOpenAI<T extends object>(client: T): T {
  const target = client as any;
  const provider = providerFor(target);
  wrapMethod(target.chat?.completions, "create", chatHandler(provider));
  wrapMethod(target.responses, "create", responsesHandler(provider));
  wrapMethod(target.embeddings, "create", embeddingsHandler(provider));
  return client;
}

export function uninstrumentOpenAI(client: object): void {
  const target = client as any;
  unwrapMethod(target.chat?.completions, "create");
  unwrapMethod(target.responses, "create");
  unwrapMethod(target.embeddings, "create");
}

function providerFor(client: any): string {
  const baseURL = String(client?.baseURL ?? "").toLowerCase();
  if (baseURL.includes("azure")) return "azure.ai.openai";
  if (!baseURL || baseURL.includes("api.openai.com")) return "openai";
  for (const [marker, name] of [
    ["groq.com", "groq"],
    ["deepseek", "deepseek"],
    ["mistral.ai", "mistral_ai"],
    ["x.ai", "x_ai"],
    ["perplexity", "perplexity"],
    ["openrouter", "openrouter"],
  ] as const) {
    if (baseURL.includes(marker)) return name;
  }
  if (baseURL.includes("localhost") || baseURL.includes("127.0.0.1")) return "openai-compatible";
  return "openai";
}

function requestAttributes(provider: string, body: Record<string, any>): Record<string, unknown> {
  return {
    "gen_ai.provider.name": provider,
    "gen_ai.request.model": given(body, "model"),
    "gen_ai.request.temperature": given(body, "temperature"),
    "gen_ai.request.top_p": given(body, "top_p"),
    "gen_ai.request.max_tokens": given(body, "max_completion_tokens") ?? given(body, "max_tokens") ?? given(body, "max_output_tokens"),
    "gen_ai.request.seed": given(body, "seed"),
    "gen_ai.request.stream": body.stream === true,
    "gen_ai.request.reasoning.level": given(body, "reasoning_effort") ?? given(body, "reasoning")?.effort,
  };
}

function chatHandler(provider: string): Handler {
  return {
    start(body) {
      const span = new Span(`chat ${given(body, "model") ?? "unknown"}`, { kind: "llm", attributes: requestAttributes(provider, body) });
      if (captureContent()) {
        span.setAttribute("gen_ai.input.messages", given(body, "messages"));
        span.setAttribute("gen_ai.tool.definitions", given(body, "tools"));
      }
      return span;
    },
    onResponse(span, response) {
      const choices: any[] = response?.choices ?? [];
      finishChat(span, {
        model: response?.model,
        id: response?.id,
        usage: response?.usage,
        messages: choices.map((choice) => choice.message),
        finishReasons: choices.map((choice) => choice.finish_reason).filter(Boolean),
      });
    },
    accumulator(): Accumulator {
      let model: string | undefined;
      let id: string | undefined;
      let usage: any;
      const text = new Map<number, string>();
      const toolCalls = new Map<number, Map<number, any>>();
      const finishReasons = new Map<number, string>();
      return {
        add(chunk: any) {
          model = chunk?.model ?? model;
          id = chunk?.id ?? id;
          if (chunk?.usage) usage = chunk.usage;
          for (const choice of chunk?.choices ?? []) {
            const index = Number(choice.index ?? 0);
            const delta = choice.delta ?? {};
            if (delta.content) text.set(index, (text.get(index) ?? "") + String(delta.content));
            for (const call of delta.tool_calls ?? []) {
              const calls = toolCalls.get(index) ?? new Map<number, any>();
              toolCalls.set(index, calls);
              const entry = calls.get(Number(call.index ?? 0)) ?? { id: undefined, type: "function", function: { name: "", arguments: "" } };
              entry.id = call.id ?? entry.id;
              entry.function.name += call.function?.name ?? "";
              entry.function.arguments += call.function?.arguments ?? "";
              calls.set(Number(call.index ?? 0), entry);
            }
            if (choice.finish_reason) finishReasons.set(index, choice.finish_reason);
          }
        },
        finish(span) {
          const indexes = [...new Set([...text.keys(), ...toolCalls.keys(), ...finishReasons.keys()])].sort((a, b) => a - b);
          const messages = indexes.map((index) => {
            const message: Record<string, unknown> = { role: "assistant", content: text.get(index) ?? "" };
            const calls = toolCalls.get(index);
            if (calls) message.tool_calls = [...calls.entries()].sort(([a], [b]) => a - b).map(([, call]) => call);
            return message;
          });
          finishChat(span, {
            model,
            id,
            usage,
            messages,
            finishReasons: indexes.map((index) => finishReasons.get(index)).filter(Boolean) as string[],
          });
        },
      };
    },
  };
}

function finishChat(
  span: Span,
  result: { model?: string; id?: string; usage?: any; messages: unknown[]; finishReasons: string[] },
): void {
  span.setAttribute("gen_ai.response.model", result.model);
  span.setAttribute("gen_ai.response.id", result.id);
  if (result.finishReasons.length) span.setAttribute("gen_ai.response.finish_reasons", result.finishReasons.map(String));
  if (result.usage) {
    span.setUsage({
      inputTokens: result.usage.prompt_tokens,
      outputTokens: result.usage.completion_tokens,
      cacheReadTokens: result.usage.prompt_tokens_details?.cached_tokens,
      reasoningTokens: result.usage.completion_tokens_details?.reasoning_tokens,
    });
  }
  if (captureContent() && result.messages.length) span.setAttribute("gen_ai.output.messages", result.messages);
}

function responsesHandler(provider: string): Handler {
  const onResponse = (span: Span, response: any) => {
    const usage = response?.usage;
    span.setAttribute("gen_ai.response.model", response?.model);
    span.setAttribute("gen_ai.response.id", response?.id);
    span.setAttribute("gen_ai.response.status", response?.status);
    if (usage) {
      span.setUsage({
        inputTokens: usage.input_tokens,
        outputTokens: usage.output_tokens,
        cacheReadTokens: usage.input_tokens_details?.cached_tokens,
        reasoningTokens: usage.output_tokens_details?.reasoning_tokens,
      });
    }
    if (response?.status === "failed" && response?.error) {
      span.setStatus("error", String(response.error.message ?? response.error));
    }
    if (captureContent()) span.setAttribute("gen_ai.output.messages", response?.output);
  };
  return {
    start(body) {
      const span = new Span(`chat ${given(body, "model") ?? "unknown"}`, { kind: "llm", attributes: requestAttributes(provider, body) });
      span.setAttribute("gen_ai.request.previous_response.id", given(body, "previous_response_id"));
      if (typeof body.conversation === "string") span.setAttribute("gen_ai.conversation.id", body.conversation);
      if (captureContent()) {
        span.setAttribute("gen_ai.system_instructions", given(body, "instructions"));
        span.setAttribute("gen_ai.input.messages", given(body, "input"));
        span.setAttribute("gen_ai.tool.definitions", given(body, "tools"));
      }
      return span;
    },
    onResponse,
    accumulator() {
      let final: any;
      return {
        add(event: any) {
          if (["response.completed", "response.failed", "response.incomplete"].includes(event?.type)) final = event.response;
        },
        finish(span) {
          if (final) onResponse(span, final);
        },
      };
    },
  };
}

function embeddingsHandler(provider: string): Handler {
  return {
    start(body) {
      const span = new Span(`embeddings ${given(body, "model") ?? "unknown"}`, {
        kind: "embedding",
        attributes: requestAttributes(provider, body),
      });
      if (body.encoding_format) span.setAttribute("gen_ai.request.encoding_formats", [String(body.encoding_format)]);
      return span;
    },
    onResponse(span, response) {
      span.setAttribute("gen_ai.response.model", response?.model);
      span.setUsage({ inputTokens: response?.usage?.prompt_tokens, outputTokens: 0 });
      const first = response?.data?.[0]?.embedding;
      if (Array.isArray(first)) span.setAttribute("gen_ai.embeddings.dimension.count", first.length);
    },
  };
}
