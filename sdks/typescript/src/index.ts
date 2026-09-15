export { AgentMeshClient, AgentMeshHttpError, flush, getClient, HttpExporter, InMemoryExporter, init, shutdown } from "./client.js";
export type { ClientConfig, InitOptions } from "./client.js";
export {
  contains,
  CRITERIA,
  DEFAULT_JUDGE_TEMPLATE,
  exactMatch,
  inlineItemId,
  llmJudge,
  runEvaluator,
  runExperiment,
} from "./experiments.js";
export type {
  DatasetItem,
  EvaluationResult,
  Evaluator,
  EvaluatorArgs,
  ExperimentResult,
  ExperimentSummary,
  ItemResult,
  LLMJudgeOptions,
  RunExperimentOptions,
} from "./experiments.js";
export { instrumentAnthropic, uninstrumentAnthropic } from "./integrations/anthropic.js";
export { instrumentOpenAI, uninstrumentOpenAI } from "./integrations/openai.js";
export { getCurrentSpan, Span, withActiveSpan } from "./span.js";
export type { ModelOptions, SpanOptions, Usage } from "./span.js";
export { getCurrentTraceId, observe, score, span, startSpan, trace, updateCurrentTrace } from "./tracing.js";
export type { ObserveOptions, ScoreOptions, TraceOptions } from "./tracing.js";
export type { AttributeValue, Attributes, Exporter, ScorePayload, SpanData, SpanEvent, SpanKind, SpanStatus } from "./types.js";
export { VERSION } from "./version.js";
