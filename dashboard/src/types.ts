export type JsonRecord = Record<string, unknown>

export interface TraceSummary {
  trace_id: string
  run_id?: string
  workflow_id?: string
  workflow_name?: string
  name: string
  status: string
  started_at: string
  ended_at: string | null
  duration_ms?: number | null
  error?: unknown
  error_type?: string | null
  error_message?: string | null
  environment?: string
  is_demo?: boolean
  total_tokens?: number
  estimated_cost?: number
  cost_status?: string | null
  provider?: string | null
  model?: string | null
  model_call_count?: number
  tool_call_count?: number
  max_latency_ms?: number
  span_count?: number
}

export interface TraceEvent {
  event_id: string
  trace_id: string
  span_id: string
  parent_span_id: string | null
  timestamp: string
  event_type: string
  actor: string
  payload: unknown
}

export interface SpanRecord {
  span_id: string
  trace_id: string
  run_id?: string
  workflow_id?: string
  workflow_name?: string
  parent_span_id: string | null
  agent_id?: string | null
  agent_name?: string | null
  task_id?: string | null
  task_name?: string | null
  event_type: string
  status: string
  started_at: string
  ended_at?: string | null
  duration_ms?: number | null
  input?: unknown
  output?: unknown
  error_type?: string | null
  error_message?: string | null
  retry_count?: number
  provider?: string | null
  model?: string | null
  prompt_tokens?: number
  completion_tokens?: number
  cached_tokens?: number
  reasoning_tokens?: number
  total_tokens?: number
  estimated_cost?: number
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  prompt_version?: string | null
  tool_name?: string | null
  memory_operation?: string | null
  rag_document_ids?: string[]
  metadata?: unknown
}

export interface TraceDetail {
  trace: TraceSummary | null
  spans: SpanRecord[]
  events: TraceEvent[]
  task_graph: Array<{ event: string; actor: string; span_id: string; parent_span_id: string | null }>
  model_calls: ModelCallRecord[]
  tool_calls: ToolCallRecord[]
  memory_operations: MemoryOperation[]
  rag_retrievals: RagRetrieval[]
  prompt_versions: PromptVersion[]
  checkpoints: Checkpoint[]
  costs: CostSummary
  diagnosis: Diagnosis
}

export interface CostSummary {
  trace_id?: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  model_calls: number
  by_agent: Record<string, unknown>
  by_model: Record<string, unknown>
}

export interface CostCenterSummary {
  total_spend_today: number
  total_spend_week: number
  total_spend_month: number
  projected_monthly_spend: number
  budget_used: number
  budget_remaining: number
  cost_per_successful_run: number
  cost_wasted_on_failed_runs: number
  cache_savings: number
  token_split: Record<string, number>
  total_tokens: number
  total_cost: number
  budget_settings: JsonRecord
  budget_alert_history: unknown[]
  cost_status_counts?: Record<string, number>
}

export interface Checkpoint {
  checkpoint_id: string
  trace_id: string
  step_id: string | null
  checkpoint_type: string
  state: unknown
  created_at: string
}

export interface ReplayDetail {
  trace_id: string
  found: boolean
  mode?: string
  prompts?: TraceEvent[]
  outputs?: TraceEvent[]
  tool_calls?: TraceEvent[]
  agent_interactions?: TraceEvent[]
  checkpoints?: Checkpoint[]
  events?: TraceEvent[]
}

export interface PromptVersion {
  prompt_id: string
  trace_id: string | null
  agent: string
  task_id: string | null
  prompt_hash: string
  system_prompt: string | null
  user_prompt: string
  metadata: unknown
  created_at: string
}

export interface PromptSummary {
  prompt_name: string
  prompt_hash: string
  latest_version: string
  owner: string
  usage_count: number
  avg_cost: number
  avg_quality_score: number | null
  last_updated: string
}

export interface MemoryRecord {
  agent: string
  namespace: string
  key: string
  value: unknown
  version: number
  trace_id: string | null
  created_at: string
  updated_at: string
}

export interface MemoryOperation {
  operation_id: string
  trace_id: string
  span_id: string
  agent_name?: string | null
  memory_type: string
  operation: string
  key?: string | null
  value_preview?: string | null
  value?: unknown
  version?: number | null
  redacted: boolean
  timestamp: string
  metadata?: unknown
}

export interface RagRetrieval {
  retrieval_id: string
  trace_id: string
  span_id: string
  agent_name?: string | null
  query?: string | null
  embedding_model?: string | null
  vector_store?: string | null
  retrieved_documents: unknown[]
  chunk_ids: string[]
  chunk_preview?: string | null
  scores: unknown[]
  source_metadata: unknown
  used_in_answer: boolean
  citation_mapping: unknown
  timestamp: string
  metadata?: unknown
}

export interface ApprovalRecord {
  approval_id: string
  trace_id: string | null
  workflow?: string | null
  agent: string
  tool: string
  risky_action?: string
  arguments: unknown
  input_args?: unknown
  status: string
  risk_level?: string
  reason: string | null
  created_at: string
  resolved_at: string | null
}

export interface CompareResult {
  left_trace_id: string
  right_trace_id: string
  left_event_count: number
  right_event_count: number
  event_types_match: boolean
  left_event_types: string[]
  right_event_types: string[]
}

export interface Diagnosis {
  trace_id: string
  found: boolean
  status?: string
  failure_count?: number
  retry_count?: number
  findings?: unknown[]
}

export interface ModelCallRecord {
  model_call_id: string
  trace_id: string
  span_id: string
  parent_span_id?: string | null
  agent_name?: string | null
  task_id?: string | null
  provider?: string | null
  model?: string | null
  endpoint_alias?: string | null
  status: string
  started_at: string
  ended_at?: string | null
  duration_ms?: number | null
  prompt_version?: string | null
  prompt?: unknown
  output?: unknown
  prompt_tokens: number
  completion_tokens: number
  cached_tokens: number
  reasoning_tokens: number
  total_tokens: number
  estimated_cost: number
  cost_status?: string
  cost_source?: string | null
  request_id?: string | null
  retry_count?: number
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  context_window?: number | null
  error_type?: string | null
  error_message?: string | null
}

export interface ProviderHealth {
  provider: string
  display_name: string
  status: string
  calls: number
  tokens: number
  cost_usd: number
  avg_latency_ms: number
  p95_latency_ms: number
  error_count: number
  error_rate: number
  rate_limit_events: number
  fallback_count: number
  last_error?: string | null
  updated_at?: string
  metadata?: JsonRecord
}

export interface ModelUsage {
  provider: string
  model: string
  endpoint_alias?: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cached_tokens: number
  reasoning_tokens?: number
  total_tokens: number
  estimated_cost: number
  avg_latency_ms: number
  p95_latency_ms: number
  success_rate: number
  error_rate: number
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  context_window?: number | null
}

export interface ToolCallRecord {
  tool_call_id: string
  trace_id: string
  span_id: string
  parent_span_id?: string | null
  agent_name?: string | null
  tool_name: string
  tool_type: string
  status: string
  started_at: string
  ended_at?: string | null
  duration_ms?: number | null
  permission_level?: string | null
  approval_status?: string | null
  risk_level?: string | null
  retry_count: number
  side_effect: boolean
  input?: unknown
  output?: unknown
  stdout?: string | null
  stderr?: string | null
  error_type?: string | null
  error_message?: string | null
  sandbox_logs?: unknown
  mcp_metadata?: unknown
  side_effects?: unknown
  metadata?: unknown
}

export interface WorkflowSummary {
  workflow_id: string
  workflow_name: string
  runs: number
  active_runs: number
  failed_runs: number
  avg_latency_ms: number
  total_cost: number
  total_tokens: number
  created_at?: string
  updated_at?: string
}

export interface WorkflowGraph {
  workflow_id: string
  trace_id?: string
  nodes: Array<{
    id: string
    name: string
    type: string
    status: string
    duration_ms?: number | null
    cost?: number | null
    tokens?: number | null
    retry_count?: number | null
    error?: string | null
    raw?: unknown
  }>
  edges: Array<{ source: string; target: string }>
}

export interface AgentSummary {
  agent_id: string
  agent_name: string
  role?: string | null
  provider?: string | null
  model?: string | null
  status: string
  current_task?: string | null
  model_calls: number
  total_tokens: number
  total_cost: number
  avg_latency_ms: number
  success_rate: number
  failure_rate: number
  tools_available: number
  memory_permissions: string[]
}

export interface EvaluationRecord {
  evaluation_id: string
  trace_id?: string | null
  workflow_name?: string | null
  agent_name?: string | null
  evaluator: string
  evaluator_type: string
  status: string
  score?: number | null
  human_rating?: number | null
  passed?: boolean | null
  findings?: unknown
  created_at: string
}

export interface EvaluationSummary {
  count: number
  task_success_score?: number | null
  human_rating?: number | null
  schema_validation_pass_rate?: number | null
  rag_faithfulness_score?: number | null
  hallucination_risk?: number | null
  regression_status?: string
  quality_by_workflow?: Array<{ name: string; score: number }>
  quality_by_agent?: Array<{ name: string; score: number }>
}

export interface OverviewData {
  runs_today: number
  active_workflows: number
  success_rate: number
  failure_rate: number
  average_latency_ms: number
  total_tokens: number
  total_cost: number
  pending_approvals: number
  provider_health: ProviderHealth[]
  budget_used: number
  budget_remaining: number
  recent_traces: TraceSummary[]
  recent_failures: TraceSummary[]
  recent_approvals: ApprovalRecord[]
  expensive_runs: JsonRecord[]
  slowest_runs: TraceSummary[]
}

export interface TimeseriesData {
  points: Array<{ bucket: string; runs: number; cost: number; tokens: number; failures: number; latency: number }>
}

export interface ReplayRun {
  replay_id: string
  source_trace_id: string
  source_span_id?: string | null
  mode: string
  status: string
  created_at: string
  completed_at?: string | null
  result: unknown
  metadata?: unknown
}
