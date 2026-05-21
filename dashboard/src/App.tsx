import { useEffect, useRef, useState } from 'react'
import {
  approveRequest,
  compareTraces,
  createReplay,
  createReplayFromSpan,
  exportTrace,
  getCostBreakdown,
  getCostCenterSummary,
  getEvaluationSummary,
  getHealth,
  getOverview,
  getOverviewTimeseries,
  getTrace,
  getWorkflowGraph,
  listAgents,
  listApprovals,
  listAuditLogs,
  listCheckpoints,
  listEvaluations,
  listMemory,
  listMemoryOperations,
  listModelCalls,
  listModels,
  listPrompts,
  listProviders,
  listRagRetrievals,
  listToolCalls,
  listTraces,
  listWorkflows,
  rejectRequest,
  runEvaluation,
} from './api'
import type { JsonRecord, SpanRecord, TraceSummary } from './types'
import type { ConnectionState, Section } from './appTypes'
import { emptyData, type DashboardData, type LiveEventRecord } from './appTypes'
import { ConnectionDiagnostics, GlobalFilters } from './components/layout/GlobalFilters'
import { MobileNav, Sidebar } from './components/layout/Navigation'
import { TopBar } from './components/layout/TopBar'
import { OverviewPage } from './pages/OverviewPage'
import { TraceExplorerPage } from './pages/TraceExplorerPage'
import { WorkflowsPage } from './pages/WorkflowsPage'
import {
  AgentsPage,
  ApprovalsPage,
  CostsPage,
  EvaluationsPage,
  MemoryRagPage,
  ModelsPage,
  PromptsPage,
  ReplayPage,
  SettingsPage,
  ToolsPage,
} from './pages/SecondaryPages'
import { parseFailedEndpoint, stringValue } from './utils/format'

export function App() {
  const [section, setSection] = useState<Section>('overview')
  const [data, setData] = useState<DashboardData>(emptyData)
  const [selectedTraceId, setSelectedTraceId] = useState('')
  const [traceDetail, setTraceDetail] = useState<Awaited<ReturnType<typeof getTrace>> | null>(null)
  const [selectedSpan, setSelectedSpan] = useState<SpanRecord | null>(null)
  const [workflowGraph, setWorkflowGraph] = useState<Awaited<ReturnType<typeof getWorkflowGraph>> | null>(null)
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<JsonRecord>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [health, setHealth] = useState<JsonRecord | null>(null)
  const [connection, setConnection] = useState<ConnectionState>({
    backendStatus: 'checking',
    liveStatus: 'connecting',
    lastSuccessfulRefresh: null,
    lastFailedEndpoint: null,
    lastError: null,
    lastUpdated: null,
    lastLiveEvent: null,
    retryCount: 0,
  })
  const [liveEvents, setLiveEvents] = useState<LiveEventRecord[]>([])
  const [dark, setDark] = useState(false)
  const [replayResult, setReplayResult] = useState<Awaited<ReturnType<typeof createReplay>> | null>(null)
  const [compareResult, setCompareResult] = useState<Awaited<ReturnType<typeof compareTraces>> | null>(null)
  const liveRefreshTimer = useRef<number | null>(null)

  async function loadTrace(traceId: string) {
    if (!traceId)
      return
    const detail = await getTrace(traceId)
    setTraceDetail(detail)
    setSelectedTraceId(traceId)
    setSelectedSpan(detail.spans[0] ?? null)
  }

  async function refresh(nextFilters: JsonRecord = filters) {
    setLoading(true)
    setError('')
    try {
      const [
        healthStatus,
        overview,
        timeseries,
        traces,
        workflows,
        agents,
        providers,
        models,
        modelCalls,
        costs,
        costByWorkflow,
        costByAgent,
        costByModel,
        costByProvider,
        costByFailedRun,
        toolCalls,
        memoryRecords,
        memoryOperations,
        ragRetrievals,
        prompts,
        evaluations,
        evaluationSummary,
        approvals,
        checkpoints,
        auditLogs,
      ] = await Promise.all([
        getHealth(),
        getOverview(),
        getOverviewTimeseries(),
        listTraces({ ...nextFilters, q: query }),
        listWorkflows(),
        listAgents(),
        listProviders(),
        listModels(),
        listModelCalls(),
        getCostCenterSummary(),
        getCostBreakdown('workflow'),
        getCostBreakdown('agent'),
        getCostBreakdown('model'),
        getCostBreakdown('provider'),
        getCostBreakdown('failed-run'),
        listToolCalls(),
        listMemory(),
        listMemoryOperations(),
        listRagRetrievals(),
        listPrompts(),
        listEvaluations(),
        getEvaluationSummary(),
        listApprovals(),
        listCheckpoints(),
        listAuditLogs(),
      ])
      setHealth(healthStatus)
      setData({ overview, timeseries, traces, workflows, agents, providers, models, modelCalls, costs, costByWorkflow, costByAgent, costByModel, costByProvider, costByFailedRun, toolCalls, memoryRecords, memoryOperations, ragRetrievals, prompts, evaluations, evaluationSummary, approvals, checkpoints, auditLogs })
      const now = new Date().toISOString()
      setConnection(current => ({ ...current, backendStatus: 'ok', lastSuccessfulRefresh: now, lastUpdated: now, lastFailedEndpoint: null, lastError: null }))
      const nextTraceId = selectedTraceId || traces[0]?.trace_id || ''
      if (nextTraceId)
        await loadTrace(nextTraceId)
      const workflowId = workflows[0]?.workflow_id
      if (workflowId)
        setWorkflowGraph(await getWorkflowGraph(workflowId))
    }
    catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Dashboard request failed'
      setError(message)
      setConnection(current => ({
        ...current,
        backendStatus: 'failed',
        retryCount: current.retryCount + 1,
        lastFailedEndpoint: parseFailedEndpoint(message),
        lastError: message,
      }))
    }
    finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh({})
  }, [])

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])

  useEffect(() => {
    const source = new EventSource('/api/events/live')
    source.onopen = () => setConnection(current => ({ ...current, liveStatus: 'connected' }))
    const onLiveEvent = (event: MessageEvent) => {
      const now = new Date().toISOString()
      let traceId: string | undefined
      let liveType = event.type || 'trace_event'
      try {
        const payload = JSON.parse(event.data) as JsonRecord
        traceId = stringValue(payload.trace_id) || undefined
        liveType = stringValue(payload.live_event || event.type || 'trace_event')
      }
      catch {
        traceId = undefined
      }
      setLiveEvents(current => [{ type: liveType, at: now, trace_id: traceId }, ...current].slice(0, 40))
      setConnection(current => ({ ...current, liveStatus: 'connected', lastLiveEvent: now }))
      if (liveRefreshTimer.current === null) {
        liveRefreshTimer.current = window.setTimeout(() => {
          liveRefreshTimer.current = null
          void refresh(filters)
        }, 1800)
      }
    }
    source.addEventListener('trace_event', onLiveEvent)
    source.onerror = () => {
      setConnection(current => ({ ...current, liveStatus: 'disconnected' }))
      source.close()
    }
    return () => {
      if (liveRefreshTimer.current !== null)
        window.clearTimeout(liveRefreshTimer.current)
      source.removeEventListener('trace_event', onLiveEvent)
      source.close()
    }
  }, [filters, query, selectedTraceId])

  const activeTrace = traceDetail?.trace ?? data.traces.find(trace => trace.trace_id === selectedTraceId) ?? null

  async function handleTraceSelect(traceId: string) {
    setSection('traces')
    await loadTrace(traceId)
  }

  async function handleExportTrace(traceId: string, format: 'json' | 'otel-json' = 'json') {
    const payload = await exportTrace(traceId, format)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = format === 'otel-json' ? `${traceId}.otel.json` : `${traceId}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  async function handleReplay(traceId: string, spanId?: string) {
    const replay = spanId
      ? await createReplayFromSpan(traceId, spanId, { mode: 'deterministic-from-span', side_effects_disabled: true })
      : await createReplay(traceId, { mode: 'deterministic', side_effects_disabled: true })
    setReplayResult(replay)
    setSection('replay')
  }

  async function handleCompare(traceId: string) {
    const other = data.traces.find(trace => trace.trace_id !== traceId)
    if (other)
      setCompareResult(await compareTraces(traceId, other.trace_id))
  }

  async function handleWorkflowGraph(workflowId: string) {
    setWorkflowGraph(await getWorkflowGraph(workflowId))
  }

  const page = renderPage({
    section,
    data,
    liveEvents,
    traceDetail,
    selectedTraceId,
    selectedSpan,
    filters,
    compareResult,
    workflowGraph,
    replayResult,
    onRefresh: () => void refresh(filters),
    onFilters: next => {
      setFilters(next)
      void refresh(next)
    },
    onTraceSelect: handleTraceSelect,
    onSelectSpan: setSelectedSpan,
    onExport: handleExportTrace,
    onReplay: handleReplay,
    onCompare: handleCompare,
    onValidate: traceId => void navigator.clipboard.writeText(`Trace ${traceId} validation should be run with: agentmesh validate traces`),
    onWorkflowGraph: handleWorkflowGraph,
    onApprove: id => void approveRequest(id).then(() => refresh(filters)),
    onReject: id => void rejectRequest(id).then(() => refresh(filters)),
  })

  return (
    <main className="vision-page p-2 sm:p-5">
      <div className="vision-shell mx-auto grid max-w-screen-2xl grid-cols-1 gap-4 p-4 sm:p-5 lg:grid-cols-[220px_1fr]">
        <Sidebar section={section} onSection={setSection} onTheme={() => setDark(value => !value)} />
        <section className="min-w-0">
          <div className="flex flex-col gap-4">
            <TopBar activeTrace={activeTrace as TraceSummary | null} query={query} loading={loading} dark={dark} onQuery={setQuery} onRefresh={() => void refresh(filters)} onTheme={() => setDark(value => !value)} />
            <MobileNav section={section} onSection={setSection} />
            <GlobalFilters filters={filters} workflows={data.workflows} providers={data.providers} models={data.models} connection={connection} health={health} onFilters={next => { setFilters(next); void refresh(next) }} onRefresh={() => void refresh(filters)} />
            <ConnectionDiagnostics connection={connection} error={error} onRetry={() => void refresh(filters)} />
            {page}
          </div>
        </section>
      </div>
    </main>
  )
}

function renderPage(args: {
  section: Section
  data: DashboardData
  liveEvents: LiveEventRecord[]
  traceDetail: Awaited<ReturnType<typeof getTrace>> | null
  selectedTraceId: string
  selectedSpan: SpanRecord | null
  filters: JsonRecord
  compareResult: Awaited<ReturnType<typeof compareTraces>> | null
  workflowGraph: Awaited<ReturnType<typeof getWorkflowGraph>> | null
  replayResult: Awaited<ReturnType<typeof createReplay>> | null
  onRefresh: () => void
  onFilters: (filters: JsonRecord) => void
  onTraceSelect: (traceId: string) => void
  onSelectSpan: (span: SpanRecord) => void
  onExport: (traceId: string, format?: 'json' | 'otel-json') => void
  onReplay: (traceId: string, spanId?: string) => void
  onCompare: (traceId: string) => void
  onValidate: (traceId: string) => void
  onWorkflowGraph: (workflowId: string) => void
  onApprove: (id: string) => void
  onReject: (id: string) => void
}) {
  const { section, data } = args
  if (section === 'overview')
    return <OverviewPage overview={data.overview} timeseries={data.timeseries} traces={data.traces} providers={data.providers} models={data.models} modelCalls={data.modelCalls} toolCalls={data.toolCalls} costs={data.costs} liveEvents={args.liveEvents} onTraceSelect={args.onTraceSelect} onExport={args.onExport} onReplay={args.onReplay} onCompare={args.onCompare} />
  if (section === 'traces')
    return <TraceExplorerPage traces={data.traces} detail={args.traceDetail} selectedTraceId={args.selectedTraceId} selectedSpan={args.selectedSpan} filters={args.filters} modelCalls={data.modelCalls} toolCalls={data.toolCalls} compareResult={args.compareResult} onFilters={args.onFilters} onSelectTrace={args.onTraceSelect} onSelectSpan={args.onSelectSpan} onExport={args.onExport} onReplay={args.onReplay} onCompare={args.onCompare} onValidate={args.onValidate} />
  if (section === 'workflows')
    return <WorkflowsPage workflows={data.workflows} traces={data.traces} approvals={data.approvals} checkpoints={data.checkpoints} activeGraph={args.workflowGraph} onGraph={args.onWorkflowGraph} onNodeReplay={args.onReplay} />
  if (section === 'agents')
    return <AgentsPage agents={data.agents} traces={data.traces} modelCalls={data.modelCalls} toolCalls={data.toolCalls} memoryOperations={data.memoryOperations} />
  if (section === 'models')
    return <ModelsPage providers={data.providers} models={data.models} modelCalls={data.modelCalls} />
  if (section === 'tools')
    return <ToolsPage toolCalls={data.toolCalls} />
  if (section === 'memory')
    return <MemoryRagPage memoryRecords={data.memoryRecords} operations={data.memoryOperations} retrievals={data.ragRetrievals} />
  if (section === 'prompts')
    return <PromptsPage prompts={data.prompts} detail={args.traceDetail} />
  if (section === 'costs')
    return <CostsPage summary={data.costs} byWorkflow={data.costByWorkflow} byAgent={data.costByAgent} byModel={data.costByModel} byProvider={data.costByProvider} byFailedRun={data.costByFailedRun} />
  if (section === 'evaluations')
    return <EvaluationsPage summary={data.evaluationSummary} evaluations={data.evaluations} onRun={() => void runEvaluation({ evaluator: 'mock-evaluator', evaluator_type: 'deterministic_mock', score: 0.9, passed: true }).then(args.onRefresh)} />
  if (section === 'approvals')
    return <ApprovalsPage approvals={data.approvals} onApprove={args.onApprove} onReject={args.onReject} />
  if (section === 'replay')
    return <ReplayPage checkpoints={data.checkpoints} replay={args.replayResult} trace={args.traceDetail?.trace ?? data.traces[0] ?? null} selectedSpan={args.selectedSpan} onReplay={args.onReplay} />
  return <SettingsPage auditLogs={data.auditLogs} providers={data.providers} costs={data.costs} />
}
