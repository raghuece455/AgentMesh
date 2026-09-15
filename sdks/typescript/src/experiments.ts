import { createHash } from "node:crypto";

import { flush, getClient, HttpExporter } from "./client.js";
import { trace } from "./tracing.js";
import { randomHex } from "./util.js";

const DATASET_PAGE_SIZE = 5000;

export interface DatasetItem {
  input: unknown;
  expected?: unknown;
  metadata?: Record<string, unknown>;
  item_id?: string;
}

export interface EvaluationResult {
  name: string;
  score?: number | null;
  passed?: boolean | null;
  label?: string | null;
  comment?: string | null;
  metadata?: Record<string, unknown>;
}

export interface EvaluatorArgs {
  input: unknown;
  output: unknown;
  expected: unknown;
  metadata: Record<string, unknown>;
}

type EvaluatorReturn = EvaluationResult | number | boolean | Omit<EvaluationResult, "name"> | null | undefined;

export type EvaluatorFunction = ((args: EvaluatorArgs) => EvaluatorReturn | Promise<EvaluatorReturn>) & { evaluatorName?: string };
export interface EvaluatorObject {
  name: string;
  evaluate(args: EvaluatorArgs): EvaluatorReturn | Promise<EvaluatorReturn>;
}
export type Evaluator = EvaluatorFunction | EvaluatorObject;

export interface ItemResult {
  item_id: string;
  input: unknown;
  expected: unknown;
  output: unknown;
  error: string | null;
  status: "completed" | "failed";
  trace_id: string;
  duration_ms: number;
  scores: EvaluationResult[];
}

export interface ExperimentResult {
  experimentId: string;
  name: string;
  dataset: string | null;
  results: ItemResult[];
  summary: ExperimentSummary;
  persisted: boolean;
  url?: string;
  /** Mean score for one evaluator, or undefined if it produced no numeric scores. */
  score(name: string): number | undefined;
}

export interface ExperimentSummary {
  items: number;
  errors: number;
  error_rate: number;
  avg_latency_ms: number | null;
  scores: Record<string, { mean: number | null; min: number | null; max: number | null; count: number; pass_rate: number | null }>;
}

export interface RunExperimentOptions<I = any, O = any> {
  /** A dataset name or id on the AgentMesh server, or items inline. */
  dataset: string | DatasetItem[];
  /** Your agent or prompt under test. Receives each item's input. */
  task: (input: I, item: DatasetItem) => O | Promise<O>;
  evaluators?: Evaluator[];
  name?: string;
  description?: string;
  metadata?: Record<string, unknown>;
  maxConcurrency?: number;
}

/**
 * Run `task` over a dataset, score every output, and store the results as an experiment in AgentMesh.
 * Each item runs inside its own trace (tagged `experiment`).
 */
export async function runExperiment<I = any, O = any>(options: RunExperimentOptions<I, O>): Promise<ExperimentResult> {
  const client = getClient();
  const exporter = client.exporter instanceof HttpExporter ? client.exporter : undefined;
  let datasetName: string | null = null;
  let datasetId: string | null = null;
  let items: DatasetItem[];
  if (typeof options.dataset === "string") {
    if (!exporter) throw new Error("Loading a dataset by name needs the HTTP exporter (an AgentMesh endpoint)");
    const path = `/api/datasets/${encodeURIComponent(options.dataset)}`;
    items = [];
    // The server returns items a page at a time; keep reading until item_count is reached.
    for (;;) {
      const page = (await exporter.request("GET", `${path}?limit=${DATASET_PAGE_SIZE}&offset=${items.length}`)) as {
        dataset_id: string;
        name: string;
        item_count: number;
        items: DatasetItem[];
      };
      datasetName = page.name;
      datasetId = page.dataset_id;
      items.push(...(page.items ?? []));
      if (!page.items?.length || items.length >= Number(page.item_count ?? 0)) break;
    }
  } else {
    items = options.dataset;
  }
  items.forEach((item, index) => {
    if (!item || typeof item !== "object" || !("input" in item)) throw new Error(`dataset item ${index} needs an 'input'`);
  });

  const experimentId = `exp_${randomHex(8)}`;
  const name = options.name ?? `${datasetName ?? "experiment"}-${new Date().toISOString().replace(/[-:]/g, "").slice(0, 15)}`;
  const evaluators = options.evaluators ?? [];
  const header = {
    experiment_id: experimentId,
    name,
    description: options.description ?? null,
    dataset: datasetId,
    dataset_name: datasetName,
    status: "running",
    started_at: new Date().toISOString(),
    evaluators: evaluators.map(evaluatorName),
    metadata: { ...(options.metadata ?? {}), task: options.task.name || "task", sdk: "typescript" },
  };
  if (exporter) await exporter.request("POST", "/api/experiments", JSON.stringify({ ...header, results: [] }));

  const results: ItemResult[] = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const index = next;
      next += 1;
      results[index] = await runItem(items[index]!, options.task, evaluators, experimentId, name, datasetName);
    }
  };
  await Promise.all(Array.from({ length: Math.max(1, Math.min(options.maxConcurrency ?? 4, items.length || 1)) }, worker));
  await flush();

  for (const result of results) {
    for (const score of result.scores) {
      if ((score.score === null || score.score === undefined) && (score.passed === null || score.passed === undefined)) continue;
      client.score({
        trace_id: result.trace_id,
        name: score.name,
        value: score.score ?? score.passed ?? null,
        passed: score.passed ?? null,
        label: score.label ?? null,
        comment: score.comment ?? null,
        source: "experiment",
        metadata: { experiment_id: experimentId, item_id: result.item_id, ...(score.metadata ?? {}) },
      });
    }
  }
  await flush();

  let summary = summarize(results);
  if (exporter) {
    const final = { ...header, status: "completed", ended_at: new Date().toISOString() };
    for (let start = 0; start < Math.max(results.length, 1); start += 200) {
      const saved = (await exporter.request(
        "POST",
        "/api/experiments",
        JSON.stringify({ ...final, results: results.slice(start, start + 200) }),
      )) as { summary?: ExperimentSummary };
      if (saved?.summary) summary = saved.summary;
    }
  }
  return {
    experimentId,
    name,
    dataset: datasetName,
    results,
    summary,
    persisted: Boolean(exporter),
    url: exporter ? `${exporter.endpoint}/?page=datasets&experiment=${experimentId}` : undefined,
    score(evaluator: string) {
      return summary.scores[evaluator]?.mean ?? undefined;
    },
  };
}

async function runItem(
  item: DatasetItem,
  task: (input: any, item: DatasetItem) => unknown,
  evaluators: Evaluator[],
  experimentId: string,
  experimentName: string,
  datasetName: string | null,
): Promise<ItemResult> {
  const itemId = item.item_id ?? inlineItemId(item.input);
  const started = performance.now();
  const outcome = await trace(
    `experiment:${experimentName}`,
    { tags: ["experiment"], metadata: { experiment_id: experimentId, item_id: itemId, dataset: datasetName }, input: item.input },
    async (root) => {
      try {
        const output = await task(item.input, item);
        root.setOutput(output);
        return { traceId: root.traceId, output, error: null as string | null };
      } catch (error) {
        root.recordException(error);
        const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
        return { traceId: root.traceId, output: undefined as unknown, error: message };
      }
    },
  );
  const result: ItemResult = {
    item_id: itemId,
    input: item.input,
    expected: item.expected ?? null,
    output: outcome.output ?? null,
    error: outcome.error,
    status: outcome.error ? "failed" : "completed",
    trace_id: outcome.traceId,
    duration_ms: Math.round((performance.now() - started) * 1000) / 1000,
    scores: [],
  };
  if (!outcome.error) {
    for (const evaluator of evaluators) {
      result.scores.push(await runEvaluator(evaluator, { input: item.input, output: outcome.output, expected: item.expected ?? null, metadata: item.metadata ?? {} }));
    }
  }
  return result;
}

export async function runEvaluator(evaluator: Evaluator, args: EvaluatorArgs): Promise<EvaluationResult> {
  const name = evaluatorName(evaluator);
  try {
    const value = typeof evaluator === "function" ? await evaluator(args) : await evaluator.evaluate(args);
    return coerceResult(name, value);
  } catch (error) {
    return { name, label: "error", comment: error instanceof Error ? `${error.name}: ${error.message}` : String(error) };
  }
}

function evaluatorName(evaluator: Evaluator): string {
  return typeof evaluator === "function" ? evaluator.evaluatorName ?? (evaluator.name || "evaluator") : evaluator.name;
}

function coerceResult(name: string, value: EvaluatorReturn): EvaluationResult {
  if (typeof value === "boolean") return { name, score: value ? 1 : 0, passed: value };
  if (typeof value === "number") return { name, score: value };
  if (value === null || value === undefined) return { name, label: "skipped" };
  const result = value as EvaluationResult;
  return { ...result, name: result.name ?? name };
}

function summarize(results: ItemResult[]): ExperimentSummary {
  const buckets = new Map<string, { values: number[]; passed: boolean[] }>();
  for (const result of results) {
    for (const score of result.scores) {
      const bucket = buckets.get(score.name) ?? { values: [], passed: [] };
      buckets.set(score.name, bucket);
      if (typeof score.score === "number") bucket.values.push(score.score);
      if (typeof score.passed === "boolean") bucket.passed.push(score.passed);
    }
  }
  const scores: ExperimentSummary["scores"] = {};
  for (const [name, { values, passed }] of buckets) {
    scores[name] = {
      mean: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null,
      min: values.length ? Math.min(...values) : null,
      max: values.length ? Math.max(...values) : null,
      count: values.length,
      pass_rate: passed.length ? passed.filter(Boolean).length / passed.length : null,
    };
  }
  const errors = results.filter((result) => result.status === "failed").length;
  const durations = results.map((result) => result.duration_ms);
  return {
    items: results.length,
    errors,
    error_rate: results.length ? errors / results.length : 0,
    avg_latency_ms: durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null,
    scores,
  };
}

/**
 * The id the Python SDK gives an inline item, so experiments from either language compare item by item.
 * Matches for strings, integers, booleans, null, arrays, and objects. Floats can differ (JavaScript cannot
 * tell `1.0` from `1`), so give items an explicit `item_id` when inputs contain them.
 */
export function inlineItemId(input: unknown): string {
  return `item_${createHash("sha1").update(pythonJson(input)).digest("hex").slice(0, 16)}`;
}

/** `json.dumps(value, sort_keys=True)` formatting: ", " and ": " separators, ASCII-only escapes. */
function pythonJson(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(value);
  if (typeof value === "string") {
    // ensure_ascii: escape every UTF-16 code unit from DEL (0x7F) up as backslash-u plus four hex digits.
    const text = JSON.stringify(value);
    let escaped = "";
    for (let index = 0; index < text.length; index += 1) {
      const code = text.charCodeAt(index);
      escaped += code >= 0x7f ? `${String.fromCharCode(92)}u${code.toString(16).padStart(4, "0")}` : text[index];
    }
    return escaped;
  }
  if (Array.isArray(value)) return `[${value.map(pythonJson).join(", ")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `${pythonJson(key)}: ${pythonJson(item)}`).join(", ")}}`;
  }
  return JSON.stringify(String(value));
}

// -- evaluators ------------------------------------------------------------------------------

function normalize(value: unknown, caseSensitive: boolean): string {
  const text = typeof value === "string" ? value : JSON.stringify(value) ?? "";
  const collapsed = text.split(/\s+/).filter(Boolean).join(" ");
  return caseSensitive ? collapsed : collapsed.toLowerCase();
}

/** 1 when the output equals the expected value (strings trimmed; case-insensitive unless `caseSensitive`). */
export function exactMatch(options: { name?: string; caseSensitive?: boolean } = {}): EvaluatorObject {
  return {
    name: options.name ?? "exact_match",
    evaluate({ output, expected }) {
      if (expected === null || expected === undefined) return { label: "no_expected" };
      const passed =
        typeof output !== "string" && typeof expected !== "string"
          ? JSON.stringify(output) === JSON.stringify(expected)
          : normalize(output, Boolean(options.caseSensitive)) === normalize(expected, Boolean(options.caseSensitive));
      return { score: passed ? 1 : 0, passed };
    },
  };
}

/** The output contains `value` (or the expected text, or every string in an expected array). */
export function contains(value?: string | string[], options: { name?: string; caseSensitive?: boolean } = {}): EvaluatorObject {
  return {
    name: options.name ?? "contains",
    evaluate({ output, expected }) {
      const source = value ?? expected;
      if (source === null || source === undefined) return { label: "no_expected" };
      const needles = (Array.isArray(source) ? source : [source]).map((item) => (typeof item === "string" ? item : JSON.stringify(item)));
      const haystack = typeof output === "string" ? output : JSON.stringify(output) ?? "";
      const matches = (needle: string) =>
        options.caseSensitive ? haystack.includes(needle) : haystack.toLowerCase().includes(needle.toLowerCase());
      const missing = needles.filter((needle) => !matches(needle));
      return {
        score: needles.length ? (needles.length - missing.length) / needles.length : 1,
        passed: missing.length === 0,
        comment: missing.length ? `missing: ${missing.join(", ")}` : null,
      };
    },
  };
}

export const CRITERIA: Record<string, string> = {
  correctness:
    "Is the actual output factually correct and does it answer the input? When an expected output is given, treat it as the reference answer: the actual output should agree with it in substance, wording may differ.",
  helpfulness: "Does the actual output directly and completely help the user with what the input asks for?",
  conciseness: "Is the actual output as short as it can be while still fully answering the input?",
  faithfulness:
    "Is every claim in the actual output supported by the input (including any provided context or documents)? Unsupported or invented claims score low.",
  harmlessness: "Is the actual output free of harmful, unsafe, or policy-violating content?",
};

export const DEFAULT_JUDGE_TEMPLATE = `You are grading the output of an AI system.

Criteria:
{criteria}

Input:
{input}

Expected output (reference, may be empty):
{expected}

Actual output:
{output}

Respond with only a JSON object: {"score": <number from 0 to 1>, "reason": "<one short sentence>"}`;

export interface LLMJudgeOptions {
  /** A preset from CRITERIA (correctness, helpfulness, conciseness, faithfulness, harmlessness) or free text. */
  criteria?: string;
  /** Call your model: take the prompt, return its text. */
  judge: (prompt: string) => string | Promise<string>;
  name?: string;
  threshold?: number;
  scale?: [number, number];
  template?: string;
  maxChars?: number;
}

/** Grade outputs with a language model (LLM-as-judge). */
export function llmJudge(options: LLMJudgeOptions): EvaluatorObject & { buildPrompt(args: Omit<EvaluatorArgs, "metadata">): string } {
  const criteriaKey = options.criteria ?? "correctness";
  const criteria = CRITERIA[criteriaKey] ?? criteriaKey;
  const [low, high] = options.scale ?? [0, 1];
  const threshold = options.threshold ?? 0.5;
  const maxChars = options.maxChars ?? 12_000;
  const clip = (value: unknown) => {
    const text = typeof value === "string" ? value : JSON.stringify(value) ?? "";
    return text.length <= maxChars ? text : `${text.slice(0, maxChars)}... [truncated ${text.length - maxChars} chars]`;
  };
  const buildPrompt = ({ input, output, expected }: Omit<EvaluatorArgs, "metadata">) => {
    const values: Record<string, string> = {
      criteria,
      input: clip(input),
      expected: expected === null || expected === undefined ? "(none)" : clip(expected),
      output: clip(output),
    };
    // One pass over the template, so placeholders inside the inserted text are left alone.
    return (options.template ?? DEFAULT_JUDGE_TEMPLATE).replace(/\{(criteria|input|expected|output)\}/g, (_match, key: string) => values[key]!);
  };
  return {
    name: options.name ?? (CRITERIA[criteriaKey] ? criteriaKey : "llm_judge"),
    buildPrompt,
    async evaluate(args) {
      const reply = String(await options.judge(buildPrompt(args)));
      const [raw, reason] = parseJudgement(reply);
      if (raw === undefined) return { label: "unparseable", comment: reply.slice(0, 500) };
      const normalized = Math.min(Math.max(high !== low ? (raw - low) / (high - low) : raw, 0), 1);
      return {
        score: Math.round(normalized * 10_000) / 10_000,
        passed: normalized >= threshold,
        comment: reason ?? null,
        metadata: { raw_score: raw },
      };
    },
  };
}

function parseJudgement(text: string): [number | undefined, string | undefined] {
  const cleaned = text.trim().replace(/^```[a-zA-Z0-9]*\s*/, "").replace(/\s*```$/, "").trim();
  for (const candidate of [cleaned, ...(cleaned.match(/\{[^{}]*\}/g) ?? [])]) {
    try {
      const data = JSON.parse(candidate);
      if (data && typeof data.score === "number") return [data.score, data.reason ?? data.explanation];
    } catch {
      // not JSON; try the next candidate
    }
  }
  const match = cleaned.match(/score\W{0,3}\s*([0-9]+(?:\.[0-9]+)?)/i);
  return match ? [Number(match[1]), undefined] : [undefined, undefined];
}
