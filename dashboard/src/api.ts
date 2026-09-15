import type {
  AgentSummary,
  ApprovalRecord,
  Checkpoint,
  CompareResult,
  CostCenterSummary,
  CostSummary,
  AlertEvent,
  AlertRule,
  DatasetDetail,
  DatasetSummary,
  EvaluationRecord,
  ExperimentComparison,
  ExperimentDetail,
  ExperimentSummary,
  EvaluationSummary,
  GuardrailsSummary,
  HaltRecord,
  IntegrationInfo,
  JsonRecord,
  SessionDetail,
  SessionSummary,
  MemoryOperation,
  MemoryRecord,
  ModelCallRecord,
  ModelUsage,
  OverviewData,
  PolicyDecision,
  PolicyRecord,
  PolicySimulation,
  PolicyValidation,
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

const API_KEY_STORAGE = 'agentmesh.apiKey'

/** API key for servers running with AGENTMESH_AUTH_MODE=api_key, kept in this browser only. */
export function getApiKey(): string {
  try {
    return window.localStorage.getItem(API_KEY_STORAGE) ?? ''
  }
  catch {
    return ''
  }
}

export function setApiKey(key: string): void {
  try {
    if (key)
      window.localStorage.setItem(API_KEY_STORAGE, key)
    else
      window.localStorage.removeItem(API_KEY_STORAGE)
  }
  catch {
    // Storage can be unavailable (private mode, blocked site data); the key then lasts for this page only.
  }
}

function authHeaders(): Record<string, string> {
  const key = getApiKey()
  return key ? { Authorization: `Bearer ${key}` } : {}
}

export function isUnauthorizedError(message: string): boolean {
  return /failed with 401\b/.test(message)
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: authHeaders() })
  if (!response.ok)
    throw new Error(`GET ${path} failed with ${response.status}`)
  return response.json() as Promise<T>
}

async function postJson<T>(path: string, payload?: unknown): Promise<T> {
  return sendJson<T>('POST', path, payload)
}

/** Write request; errors carry the server's validation message so forms can show it. */
async function sendJson<T>(method: 'POST' | 'PATCH' | 'DELETE', path: string, payload?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: method === 'DELETE' ? undefined : JSON.stringify(payload ?? {}),
  })
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json() as { detail?: { message?: string } | string; message?: string }
      detail = typeof body.detail === 'string' ? body.detail : body.detail?.message ?? body.message ?? ''
    }
    catch {
      detail = ''
    }
    throw new Error(`${method} ${path} failed with ${response.status}${detail ? `: ${detail}` : ''}`)
  }
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

export function listSessions(): Promise<SessionSummary[]> {
  return getJson<SessionSummary[]>('/api/sessions')
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return getJson<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`)
}

export function createScore(payload: { trace_id: string; name: string; value: number | boolean | string; comment?: string; span_id?: string; source?: string }): Promise<JsonRecord> {
  return postJson<JsonRecord>('/api/scores', payload)
}

export function listDatasets(): Promise<DatasetSummary[]> {
  return getJson<DatasetSummary[]>('/api/datasets')
}

export function getDataset(dataset: string): Promise<DatasetDetail> {
  return getJson<DatasetDetail>(`/api/datasets/${encodeURIComponent(dataset)}`)
}

export function createDataset(payload: { name: string; description?: string }): Promise<DatasetSummary> {
  return postJson<DatasetSummary>('/api/datasets', payload)
}

export function deleteDataset(dataset: string): Promise<JsonRecord> {
  return sendJson<JsonRecord>('DELETE', `/api/datasets/${encodeURIComponent(dataset)}`)
}

export function addDatasetItems(dataset: string, items: Array<{ input: unknown; expected?: unknown; metadata?: JsonRecord }>): Promise<JsonRecord> {
  return postJson<JsonRecord>(`/api/datasets/${encodeURIComponent(dataset)}/items`, { items })
}

export function addTraceToDataset(dataset: string, payload: { trace_id: string; span_id?: string; use_trace_output: boolean }): Promise<JsonRecord> {
  return postJson<JsonRecord>(`/api/datasets/${encodeURIComponent(dataset)}/items`, payload)
}

export function deleteDatasetItem(dataset: string, itemId: string): Promise<JsonRecord> {
  return sendJson<JsonRecord>('DELETE', `/api/datasets/${encodeURIComponent(dataset)}/items/${encodeURIComponent(itemId)}`)
}

export function listExperiments(dataset?: string): Promise<ExperimentSummary[]> {
  return getJson<ExperimentSummary[]>(`/api/experiments${dataset ? `?dataset=${encodeURIComponent(dataset)}` : ''}`)
}

export function getExperiment(experimentId: string): Promise<ExperimentDetail> {
  return getJson<ExperimentDetail>(`/api/experiments/${encodeURIComponent(experimentId)}`)
}

export function compareExperiments(base: string, candidate: string): Promise<ExperimentComparison> {
  return getJson<ExperimentComparison>(`/api/experiments/compare?base=${encodeURIComponent(base)}&candidate=${encodeURIComponent(candidate)}`)
}

export function deleteExperiment(experimentId: string): Promise<JsonRecord> {
  return sendJson<JsonRecord>('DELETE', `/api/experiments/${encodeURIComponent(experimentId)}`)
}

export function getGuardrailsSummary(hours = 24): Promise<GuardrailsSummary> {
  return getJson<GuardrailsSummary>(`/api/guardrails/summary?hours=${hours}`)
}

export function listPolicies(): Promise<PolicyRecord[]> {
  return getJson<PolicyRecord[]>('/api/policies')
}

export function createPolicy(text: string, enabled = true): Promise<PolicyRecord> {
  return postJson<PolicyRecord>('/api/policies', { text, enabled })
}

export function updatePolicy(policy: string, payload: JsonRecord): Promise<PolicyRecord> {
  return sendJson<PolicyRecord>('PATCH', `/api/policies/${encodeURIComponent(policy)}`, payload)
}

export function deletePolicy(policy: string): Promise<JsonRecord> {
  return sendJson<JsonRecord>('DELETE', `/api/policies/${encodeURIComponent(policy)}`)
}

export function validatePolicy(text: string): Promise<PolicyValidation> {
  return postJson<PolicyValidation>('/api/policies/validate', { text })
}

/** Replay recent traces through a draft (`text`) or saved (`policy`) policy. */
export function simulatePolicy(payload: { text?: string; policy?: string; limit?: number; hours?: number }): Promise<PolicySimulation> {
  return postJson<PolicySimulation>('/api/policies/simulate', payload)
}

export function listPolicyDecisions(filters: { action?: string; trace_id?: string; limit?: number; hours?: number } = {}): Promise<PolicyDecision[]> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '')
      params.set(key, String(value))
  }
  const query = params.toString()
  return getJson<PolicyDecision[]>(`/api/policy-decisions${query ? `?${query}` : ''}`)
}

export function listHalts(active = true): Promise<HaltRecord[]> {
  return getJson<HaltRecord[]>(`/api/halts?active=${active}`)
}

export function createHalt(payload: { scope: HaltRecord['scope']; value?: string; reason?: string }): Promise<HaltRecord> {
  return postJson<HaltRecord>('/api/halts', payload)
}

export function releaseHalt(haltId: string): Promise<HaltRecord> {
  return postJson<HaltRecord>(`/api/halts/${encodeURIComponent(haltId)}/release`)
}

export function listAlertRules(): Promise<AlertRule[]> {
  return getJson<AlertRule[]>('/api/alerts/rules')
}

export function getAlertKinds(): Promise<{ kinds: Record<string, string>; check_interval_seconds: number }> {
  return getJson('/api/alerts/kinds')
}

export function createAlertRule(payload: JsonRecord): Promise<AlertRule> {
  return postJson<AlertRule>('/api/alerts/rules', payload)
}

export function updateAlertRule(rule: string, payload: JsonRecord): Promise<AlertRule> {
  return sendJson<AlertRule>('PATCH', `/api/alerts/rules/${encodeURIComponent(rule)}`, payload)
}

export function deleteAlertRule(rule: string): Promise<JsonRecord> {
  return sendJson<JsonRecord>('DELETE', `/api/alerts/rules/${encodeURIComponent(rule)}`)
}

export function testAlertRule(rule: string): Promise<{ delivered: boolean; error?: string | null }> {
  return postJson(`/api/alerts/rules/${encodeURIComponent(rule)}/test`)
}

export function checkAlerts(): Promise<{ fired: AlertEvent[] }> {
  return postJson('/api/alerts/check')
}

export function listAlertEvents(limit = 50): Promise<AlertEvent[]> {
  return getJson<AlertEvent[]>(`/api/alerts/events?limit=${limit}`)
}

export function getIntegrations(): Promise<IntegrationInfo> {
  return getJson<IntegrationInfo>('/api/integrations')
}

/**
 * Subscribe to the server-sent live event stream. Uses fetch instead of EventSource so the
 * API key header can be sent. Returns a function that closes the stream.
 */
export function subscribeLiveEvents(handlers: { onOpen: () => void; onEvent: (type: string, data: string) => void; onError: () => void }): () => void {
  const controller = new AbortController()
  void (async () => {
    try {
      const response = await fetch('/api/events/live', { headers: { Accept: 'text/event-stream', ...authHeaders() }, signal: controller.signal })
      if (!response.ok || !response.body)
        throw new Error(`GET /api/events/live failed with ${response.status}`)
      handlers.onOpen()
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
      let buffer = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done)
          break
        buffer += value.replace(/\r\n/g, '\n')
        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
          const block = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          let type = 'message'
          const data: string[] = []
          for (const line of block.split('\n')) {
            if (line.startsWith('event:'))
              type = line.slice(6).trim()
            else if (line.startsWith('data:'))
              data.push(line.slice(5).trimStart())
          }
          if (data.length)
            handlers.onEvent(type, data.join('\n'))
          boundary = buffer.indexOf('\n\n')
        }
      }
      if (!controller.signal.aborted)
        handlers.onError()
    }
    catch {
      if (!controller.signal.aborted)
        handlers.onError()
    }
  })()
  return () => controller.abort()
}
