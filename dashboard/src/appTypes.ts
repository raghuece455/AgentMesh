import type {
  AgentSummary,
  ApprovalRecord,
  Checkpoint,
  CostCenterSummary,
  EvaluationRecord,
  EvaluationSummary,
  JsonRecord,
  MemoryOperation,
  MemoryRecord,
  ModelCallRecord,
  ModelUsage,
  OverviewData,
  PromptSummary,
  ProviderHealth,
  RagRetrieval,
  TimeseriesData,
  ToolCallRecord,
  TraceSummary,
  WorkflowSummary,
} from './types'

export type Section =
  | 'overview'
  | 'traces'
  | 'workflows'
  | 'agents'
  | 'models'
  | 'tools'
  | 'memory'
  | 'prompts'
  | 'costs'
  | 'evaluations'
  | 'approvals'
  | 'replay'
  | 'settings'

export interface DashboardData {
  overview: OverviewData | null
  timeseries: TimeseriesData
  traces: TraceSummary[]
  workflows: WorkflowSummary[]
  agents: AgentSummary[]
  providers: ProviderHealth[]
  models: ModelUsage[]
  modelCalls: ModelCallRecord[]
  costs: CostCenterSummary | null
  costByWorkflow: JsonRecord[]
  costByAgent: JsonRecord[]
  costByModel: JsonRecord[]
  costByProvider: JsonRecord[]
  costByFailedRun: JsonRecord[]
  toolCalls: ToolCallRecord[]
  memoryRecords: MemoryRecord[]
  memoryOperations: MemoryOperation[]
  ragRetrievals: RagRetrieval[]
  prompts: PromptSummary[]
  evaluations: EvaluationRecord[]
  evaluationSummary: EvaluationSummary | null
  approvals: ApprovalRecord[]
  checkpoints: Checkpoint[]
  auditLogs: JsonRecord[]
}

export type LiveStatus = 'connecting' | 'connected' | 'disconnected'

export interface ConnectionState {
  backendStatus: 'checking' | 'ok' | 'failed'
  liveStatus: LiveStatus
  lastSuccessfulRefresh: string | null
  lastFailedEndpoint: string | null
  lastError: string | null
  lastUpdated: string | null
  lastLiveEvent: string | null
  retryCount: number
}

export interface LiveEventRecord {
  type: string
  at: string
  trace_id?: string
}

export const emptyData: DashboardData = {
  overview: null,
  timeseries: { points: [] },
  traces: [],
  workflows: [],
  agents: [],
  providers: [],
  models: [],
  modelCalls: [],
  costs: null,
  costByWorkflow: [],
  costByAgent: [],
  costByModel: [],
  costByProvider: [],
  costByFailedRun: [],
  toolCalls: [],
  memoryRecords: [],
  memoryOperations: [],
  ragRetrievals: [],
  prompts: [],
  evaluations: [],
  evaluationSummary: null,
  approvals: [],
  checkpoints: [],
  auditLogs: [],
}
