import type {
  AgentSummary,
  ApprovalRecord,
  Checkpoint,
  CompareResult,
  CostCenterSummary,
  CostSummary,
  EvaluationRecord,
  EvaluationSummary,
  JsonRecord,
  MemoryOperation,
  MemoryRecord,
  ModelCallRecord,
  ModelUsage,
  OverviewData,
  PromptSummary,
  PromptVersion,
  ProviderHealth,
  RagRetrieval,
  ReplayDetail,
  ReplayRun,
  SpanRecord,
  TimeseriesData,
  ToolCallRecord,
  TraceDetail,
  TraceEvent,
  TraceSummary,
  WorkflowGraph,
  WorkflowSummary,
} from './types'

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok)
    throw new Error(`GET ${path} failed with ${response.status}`)
  return response.json() as Promise<T>
}

async function postJson<T>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
  })
  if (!response.ok)
    throw new Error(`POST ${path} failed with ${response.status}`)
  return response.json() as Promise<T>
}

export function getHealth(): Promise<JsonRecord> {
  return getJson<JsonRecord>('/api/health')
}

export function getOverview(): Promise<OverviewData> {
  return getJson<OverviewData>('/api/overview')
}

export function getOverviewTimeseries(): Promise<TimeseriesData> {
  return getJson<TimeseriesData>('/api/overview/timeseries')
}

export function listTraces(filters: JsonRecord = {}): Promise<TraceSummary[]> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && String(value) !== '')
      params.set(key, String(value))
  }
  const query = params.toString()
  return getJson<TraceSummary[]>(`/api/traces${query ? `?${query}` : ''}`)
}

export function getTrace(traceId: string): Promise<TraceDetail> {
  return getJson<TraceDetail>(`/api/traces/${traceId}`)
}

export function listTraceSpans(traceId: string): Promise<SpanRecord[]> {
  return getJson<SpanRecord[]>(`/api/traces/${traceId}/spans`)
}

export function listTraceEvents(traceId: string): Promise<TraceEvent[]> {
  return getJson<TraceEvent[]>(`/api/traces/${traceId}/events`)
}

export function exportTrace(traceId: string, format: 'json' | 'otel-json' = 'json'): Promise<JsonRecord> {
  const query = format === 'otel-json' ? '?format=otel-json' : ''
  return getJson<JsonRecord>(`/api/traces/${traceId}/export${query}`)
}

export function getCosts(traceId?: string): Promise<CostSummary> {
  return getJson<CostSummary>(traceId ? `/api/traces/${traceId}/costs` : '/api/costs')
}

export function getCostCenterSummary(): Promise<CostCenterSummary> {
  return getJson<CostCenterSummary>('/api/costs/summary')
}

export function getCostBreakdown(kind: 'workflow' | 'agent' | 'model' | 'provider' | 'failed-run'): Promise<JsonRecord[]> {
  const path = kind === 'failed-run' ? '/api/costs/by-failed-run' : `/api/costs/by-${kind}`
  return getJson<JsonRecord[]>(path)
}

export function getReplay(traceId: string): Promise<ReplayDetail> {
  return getJson<ReplayDetail>(`/api/traces/${traceId}/replay`)
}

export function createReplay(traceId: string, payload: JsonRecord = {}): Promise<ReplayRun> {
  return postJson<ReplayRun>(`/api/replay/${traceId}`, payload)
}

export function createReplayFromSpan(traceId: string, spanId: string, payload: JsonRecord = {}): Promise<ReplayRun> {
  return postJson<ReplayRun>(`/api/replay/${traceId}/from-span/${spanId}`, payload)
}

export function getReplayRun(replayId: string): Promise<ReplayRun> {
  return getJson<ReplayRun>(`/api/replay/${replayId}`)
}

export function listCheckpoints(traceId?: string): Promise<Checkpoint[]> {
  return getJson<Checkpoint[]>(traceId ? `/api/traces/${traceId}/checkpoints` : '/api/replay/checkpoints')
}

export function listPromptVersions(traceId: string): Promise<PromptVersion[]> {
  return getJson<PromptVersion[]>(`/api/traces/${traceId}/prompts`)
}

export function listPrompts(): Promise<PromptSummary[]> {
  return getJson<PromptSummary[]>('/api/prompts')
}

export function listPromptHistory(promptId: string): Promise<PromptVersion[]> {
  return getJson<PromptVersion[]>(`/api/prompts/${promptId}/versions`)
}

export function listMemory(): Promise<MemoryRecord[]> {
  return getJson<MemoryRecord[]>('/api/memory/records')
}

export function listMemoryOperations(): Promise<MemoryOperation[]> {
  return getJson<MemoryOperation[]>('/api/memory/operations')
}

export function listRagRetrievals(): Promise<RagRetrieval[]> {
  return getJson<RagRetrieval[]>('/api/rag/retrievals')
}

export function listApprovals(): Promise<ApprovalRecord[]> {
  return getJson<ApprovalRecord[]>('/api/approvals')
}

export function approveRequest(approvalId: string): Promise<JsonRecord> {
  return postJson<JsonRecord>(`/api/approvals/${approvalId}/approve`, {})
}

export function rejectRequest(approvalId: string): Promise<JsonRecord> {
  return postJson<JsonRecord>(`/api/approvals/${approvalId}/reject`, {})
}

export function compareTraces(left: string, right: string): Promise<CompareResult> {
  return getJson<CompareResult>(`/api/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`)
}

export function diagnoseTrace(traceId: string) {
  return getJson(`/api/traces/${traceId}/diagnose`)
}

export function listWorkflows(): Promise<WorkflowSummary[]> {
  return getJson<WorkflowSummary[]>('/api/workflows')
}

export function getWorkflowGraph(workflowId: string): Promise<WorkflowGraph> {
  return getJson<WorkflowGraph>(`/api/workflows/${workflowId}/graph`)
}

export function listAgents(): Promise<AgentSummary[]> {
  return getJson<AgentSummary[]>('/api/agents')
}

export function listProviders(): Promise<ProviderHealth[]> {
  return getJson<ProviderHealth[]>('/api/providers/health')
}

export function listModels(): Promise<ModelUsage[]> {
  return getJson<ModelUsage[]>('/api/models')
}

export function listModelCalls(): Promise<ModelCallRecord[]> {
  return getJson<ModelCallRecord[]>('/api/model-calls')
}

export function listToolCalls(): Promise<ToolCallRecord[]> {
  return getJson<ToolCallRecord[]>('/api/tool-calls')
}

export function listEvaluations(): Promise<EvaluationRecord[]> {
  return getJson<EvaluationRecord[]>('/api/evaluations')
}

export function getEvaluationSummary(): Promise<EvaluationSummary> {
  return getJson<EvaluationSummary>('/api/evaluations/summary')
}

export function runEvaluation(payload: JsonRecord): Promise<JsonRecord> {
  return postJson<JsonRecord>('/api/evaluations/run', payload)
}

export function listAuditLogs(): Promise<JsonRecord[]> {
  return getJson<JsonRecord[]>('/api/audit-logs')
}
