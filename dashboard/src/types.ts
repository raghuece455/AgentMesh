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
  session_id?: string | null
  user_id?: string | null
  tags?: string[]
  source?: string | null
  service_name?: string | null
  input?: unknown
  output?: unknown
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
  name?: string | null
  span_kind?: string | null
}

export interface ScoreRecord {
  score_id: string
  trace_id: string
  span_id?: string | null
  name: string
  value?: number | null
  label?: string | null
  comment?: string | null
  passed?: boolean | null
  source?: string | null
  created_at: string
}

export interface InsightFinding {
  kind: string
  severity: 'high' | 'warning' | 'info' | string
  message: string
  span_id?: string | null
  path?: string[]
}

export interface TraceInsights {
  trace_id: string
  found: boolean
  summary?: string
  findings: InsightFinding[]
  stats?: Record<string, unknown>
  slowest_spans?: Array<{ span_id: string; label: string; duration_ms: number; self_time_ms: number; share_of_trace: number | null }>
  costliest_calls?: Array<{ span_id: string; model: string | null; agent: string | null; estimated_cost: number }>
}

export interface SessionSummary {
  session_id: string
  trace_count: number
  started_at: string
  last_activity_at: string
  failed_traces: number
  running_traces?: number
  user_id?: string | null
  estimated_cost: number
  total_tokens: number
  total_duration_ms?: number
}

export interface SessionDetail extends SessionSummary {
  traces: TraceSummary[]
  scores: ScoreRecord[]
}

export interface IntegrationInfo {
  version: string
  otlp_traces_endpoint: string
  otlp_base_endpoint: string
  protobuf_supported: boolean
  auth_mode: string
  capture_content: string
}

export interface TraceDetail {
  scores?: ScoreRecord[]
  insights?: TraceInsights | null
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
  policy_decisions?: PolicyDecision[]
  swarms?: Array<{ swarm_id: string; name: string }>
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

export interface DatasetSummary {
  dataset_id: string
  name: string
  description?: string | null
  created_at: string
  updated_at: string
  metadata: JsonRecord
  item_count: number
  experiment_count: number
  last_experiment_at?: string | null
}

export interface DatasetItem {
  item_id: string
  dataset_id: string
  input: unknown
  expected?: unknown
  metadata: JsonRecord
  source_trace_id?: string | null
  source_span_id?: string | null
  created_at: string
}

export interface DatasetDetail extends DatasetSummary {
  items: DatasetItem[]
}

export interface EvaluatorScore {
  name: string
  score?: number | null
  passed?: boolean | null
  label?: string | null
  comment?: string | null
}

export interface ScoreStats {
  mean: number | null
  min: number | null
  max: number | null
  count: number
  pass_rate: number | null
}

export interface ExperimentSummary {
  experiment_id: string
  dataset_id?: string | null
  dataset_name?: string | null
  name: string
  description?: string | null
  status: string
  started_at: string
  ended_at?: string | null
  evaluators: string[]
  summary: { items: number; errors: number; error_rate: number; avg_latency_ms: number | null; scores: Record<string, ScoreStats> }
  metadata: JsonRecord
  total_cost: number
  total_tokens: number
}

export interface ExperimentResultRow {
  result_id: string
  item_id: string
  trace_id?: string | null
  status: string
  input: unknown
  expected?: unknown
  output?: unknown
  error?: string | null
  duration_ms?: number | null
  scores: EvaluatorScore[]
  estimated_cost?: number
  total_tokens?: number
}

export interface ExperimentDetail extends ExperimentSummary {
  results: ExperimentResultRow[]
}

export type ComparedResult = Pick<ExperimentResultRow, 'status' | 'output' | 'error' | 'trace_id' | 'duration_ms' | 'estimated_cost' | 'scores'>

export interface ExperimentComparison {
  base: ExperimentSummary
  candidate: ExperimentSummary
  score_deltas: Record<string, { base: number | null; candidate: number | null; delta: number | null }>
  cost_delta: number
  latency_delta_ms: number | null
  counts: { improved: number; regressed: number; unchanged: number; added: number; removed: number }
  items: Array<{
    item_id: string
    input: unknown
    expected?: unknown
    change: 'improved' | 'regressed' | 'unchanged' | 'added' | 'removed'
    base: ComparedResult | null
    candidate: ComparedResult | null
  }>
}

export interface AlertRule {
  rule_id: string
  name: string
  kind: string
  description?: string | null
  threshold: number
  window_minutes: number
  cooldown_minutes: number
  filters: JsonRecord
  channel: { type: string; url?: string | null; format: string; secret?: string | null; notify_resolved?: boolean }
  enabled: boolean
  state: string
  last_value?: number | null
  last_evaluated_at?: string | null
  last_triggered_at?: string | null
  created_at: string
  updated_at: string
}

export interface AlertEvent {
  alert_id: string
  rule_id: string
  rule_name: string
  kind: string
  status: string
  value?: number | null
  threshold?: number | null
  message: string
  details: JsonRecord
  delivered: boolean
  delivery_error?: string | null
  created_at: string
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

export type PolicyAction = 'allow' | 'warn' | 'require_approval' | 'deny'

export interface PolicyRecord {
  policy_id: string
  name: string
  description?: string | null
  mode: 'enforce' | 'monitor'
  enabled: boolean
  spec: JsonRecord
  rule_count: number
  limits: Record<string, number>
  source_text?: string | null
  created_at: string
  updated_at: string
}

export interface PolicyDecision {
  decision_id: string
  trace_id: string | null
  span_id: string | null
  policy_id: string | null
  policy_name: string | null
  rule: string
  action: PolicyAction
  enforced: boolean
  kind: string
  target: string
  agent: string | null
  service: string | null
  reason: string
  details: JsonRecord
  created_at: string
}

export interface HaltRecord {
  halt_id: string
  scope: 'all' | 'swarm' | 'trace' | 'agent' | 'service'
  value: string | null
  reason: string | null
  created_by: string | null
  created_at: string
  released_at: string | null
  released_by: string | null
  active: boolean
}

export interface GuardrailsSummary {
  policies: number
  enabled_policies: number
  enforcing_policies: number
  active_halts: number
  decisions: { blocked: number; approvals: number; would_block: number; warnings: number; total: number }
  hours: number
}

export interface PolicyValidation {
  valid: boolean
  errors: string[]
  policy?: JsonRecord
}

export interface PolicySimulation {
  traces_evaluated: number
  actions_evaluated: number
  traces_affected: number
  blocked_calls: number
  approval_calls: number
  rules: Array<{ policy: string; rule: string; action: PolicyAction; calls: number; traces: number }>
  traces: Array<{
    trace_id: string
    name: string | null
    status: string | null
    started_at: string | null
    blocked_calls: number
    approval_calls: number
    first: { span_id: string | null; rule: string; action: PolicyAction; reason: string; target: string; kind: string }
  }>
}

export interface SwarmSummaryRow {
  swarm_id: string
  name: string
  service_name: string | null
  environment: string | null
  is_demo: boolean
  status: string
  traces: number
  agents: number
  failed_agents: number
  running_agents: number
  errors: number
  llm_calls: number
  tool_calls: number
  tokens: number
  cost: number
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  last_seen_at: string
}

export interface SwarmNode {
  key: string
  span_id: string
  trace_id: string
  name: string
  kind: 'agent' | 'trace'
  status: string
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  parent_key: string | null
  depth: number
  children: number
  llm_calls: number
  tool_calls: number
  tokens: number
  cost: number
  errors: number
  error_message: string | null
  tools: string[]
  models: string[]
  folded_trace?: string
}

export type SwarmEdgeKind = 'spawn' | 'message' | 'handoff' | 'link'

export interface SwarmEdge {
  source: string
  target: string
  kind: SwarmEdgeKind
  count: number
  first_at?: string | null
}

export interface SwarmRole {
  name: string
  kind: 'agent' | 'trace'
  instances: number
  running: number
  failed: number
  llm_calls: number
  tool_calls: number
  tokens: number
  cost: number
  min_depth: number
}

export interface SwarmMessage {
  message_id: string
  trace_id: string
  span_id: string
  from_agent: string | null
  to_agent: string | null
  kind: string
  content: unknown
  created_at: string
  source_key: string | null
  target_key: string | null
}

export interface SwarmInsight {
  kind: string
  severity: 'danger' | 'warning' | 'info'
  title: string
  detail: string
  node_key: string | null
}

export interface SwarmDetail {
  swarm_id: string
  name: string
  service_name: string | null
  environment: string | null
  is_demo: boolean
  first_seen_at: string
  last_seen_at: string
  traces: Array<{ trace_id: string; workflow_name: string | null; status: string; started_at: string; ended_at: string | null; duration_ms: number | null; service_name: string | null }>
  summary: {
    status: string
    traces: number
    agents: number
    running_agents: number
    failed_agents: number
    roles: number
    max_depth: number
    max_fan_out: number
    max_fan_out_key: string | null
    llm_calls: number
    tool_calls: number
    tokens: number
    cost: number
    errors: number
    messages: number
    handoffs: number
    spans: number
    started_at: string | null
    ended_at: string | null
    duration_ms: number | null
    truncated: boolean
    nodes_truncated: boolean
  }
  nodes: SwarmNode[]
  edges: SwarmEdge[]
  roles: { nodes: SwarmRole[]; edges: Array<{ source: string; target: string; kind: SwarmEdgeKind; count: number }> }
  messages: SwarmMessage[]
  timeline: Array<{ at: string; active: number; started: number; failed: number }>
  insights: SwarmInsight[]
}
