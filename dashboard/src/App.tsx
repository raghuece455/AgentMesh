import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  approveRequest,
  createReplay,
  createReplayFromSpan,
  exportTrace,
  getCostBreakdown,
  getCostCenterSummary,
  getEvaluationSummary,
  getHealth,
  getIntegrations,
  getOverview,
  getTrace,
  getWorkflowGraph,
  listAgents,
  listAlertRules,
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
  listSessions,
  listToolCalls,
  listTraces,
  listWorkflows,
  rejectRequest,
  runEvaluation,
  setApiKey,
  subscribeLiveEvents,
} from './api'
import type { ConnectionState, Section } from './appTypes'
import { emptyData, type DashboardData, type LiveEventRecord } from './appTypes'
import { CommandPalette } from './components/layout/CommandPalette'
import { ConnectionBanner } from './components/layout/ConnectionBanner'
import { ShortcutsDialog } from './components/layout/ShortcutsDialog'
import { useShortcuts } from './lib/shortcuts'
import { ALL_NAV_ITEMS } from './components/layout/nav'
import { Sidebar } from './components/layout/Sidebar'
import { Topbar, type DataScope, type ThemeSetting } from './components/layout/Topbar'
import { Skeleton } from './components/ui/Card'
import { Toast } from './components/ui/Overlay'
import { AgentsPage } from './pages/AgentsPage'
import { AlertsPage } from './pages/AlertsPage'
import { ApprovalsPage, PENDING_APPROVAL } from './pages/ApprovalsPage'
import { ConnectPage } from './pages/ConnectPage'
import { CostsPage } from './pages/CostsPage'
import { DatasetsPage } from './pages/DatasetsPage'
import { EvaluationsPage } from './pages/EvaluationsPage'
import { MemoryRagPage } from './pages/MemoryRagPage'
import { ModelsPage } from './pages/ModelsPage'
import { OverviewPage } from './pages/OverviewPage'
import { PromptsPage } from './pages/PromptsPage'
import { ReplayPage } from './pages/ReplayPage'
import { SessionsPage } from './pages/SessionsPage'
import { SettingsPage } from './pages/SettingsPage'
import { ToolsPage } from './pages/ToolsPage'
import { TracesPage, type TraceFilters } from './pages/TracesPage'
import { TraceView } from './pages/TraceView'
import { WorkflowsPage } from './pages/WorkflowsPage'
import type { AlertRule, JsonRecord, ReplayRun, SpanRecord, TraceDetail, TraceSummary, WorkflowGraph } from './types'
import { errorText, parseFailedEndpoint, stringValue } from './utils/format'
import { defaultSpan, rangeStart, TIME_RANGES, type TimeRange } from './utils/traces'

const SECTIONS = ALL_NAV_ITEMS.map(item => item.id)
const THEME_KEY = 'agentmesh.theme'
const SIDEBAR_KEY = 'agentmesh.sidebarCollapsed'
/** The server returns at most 500 traces per request. */
const TRACE_PAGE_SIZE = 500
const TRACE_FILTER_KEYS = ['q', 'status', 'workflow', 'model', 'provider', 'agent', 'tool', 'error_type', 'session_id'] as const
/** Second key of the "g" shortcuts. */
const GO_TO: Record<string, Section> = { o: 'overview', t: 'traces', s: 'sessions', d: 'datasets', e: 'evaluations', a: 'alerts', c: 'costs', m: 'models', w: 'workflows' }

/** Deep links: ?trace=<id> (used in alert notifications), ?page=datasets&experiment=<id>, ?page=<section>, &range=7d, and trace filters. */
function initialLink(): { section: Section; traceId: string; experimentId?: string; range: TimeRange; filters: TraceFilters } {
  const params = new URLSearchParams(window.location.search)
  const page = params.get('page') as Section | null
  const traceId = params.get('trace') ?? ''
  const section = traceId ? 'traces' : page && SECTIONS.includes(page) ? page : 'overview'
  const range = params.get('range') as TimeRange | null
  const filters: TraceFilters = {}
  for (const key of TRACE_FILTER_KEYS) {
    const value = params.get(key)
    if (value)
      filters[key] = value
  }
  return { section, traceId, experimentId: params.get('experiment') ?? undefined, range: range && TIME_RANGES.some(item => item.value === range) ? range : '24h', filters }
}

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  }
  catch {
    return null
  }
}

function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  }
  catch {
    // Storage can be blocked; the preference then lasts for this page only.
  }
}

function initialTheme(): ThemeSetting {
  const param = new URLSearchParams(window.location.search).get('theme')
  const stored = param ?? readStorage(THEME_KEY)
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

export function App() {
  const [link] = useState(initialLink)
  const [section, setSection] = useState<Section>(link.section)
  const [theme, setThemeState] = useState<ThemeSetting>(initialTheme)
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  const [collapsed, setCollapsed] = useState(() => readStorage(SIDEBAR_KEY) === '1')
  const [mobileNav, setMobileNav] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const [range, setRange] = useState<TimeRange>(link.range)
  const [scope, setScope] = useState<DataScope>('all')
  const [traceFilters, setTraceFilters] = useState<TraceFilters>(link.filters)
  const [data, setData] = useState<DashboardData>(emptyData)
  const [alertRules, setAlertRules] = useState<AlertRule[]>([])
  const [selectedTraceId, setSelectedTraceId] = useState(link.traceId)
  const [traceDetail, setTraceDetail] = useState<TraceDetail | null>(null)
  const [traceLoading, setTraceLoading] = useState(false)
  const [selectedSpan, setSelectedSpan] = useState<SpanRecord | null>(null)
  const [workflowGraph, setWorkflowGraph] = useState<WorkflowGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
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
  const [replayResult, setReplayResult] = useState<ReplayRun | null>(null)
  const [olderTraces, setOlderTraces] = useState<{ rows: TraceSummary[]; lastPageFull: boolean; loading: boolean }>({ rows: [], lastPageFull: false, loading: false })
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [apiKeyVersion, setApiKeyVersion] = useState(0)
  const [focusedSession, setFocusedSession] = useState('')
  const [toast, setToast] = useState<{ message: string; tone?: 'neutral' | 'danger' | 'success' }>({ message: '' })
  const [version, setVersion] = useState<string | undefined>()
  const liveRefreshTimer = useRef<number | null>(null)

  const dark = theme === 'dark' || (theme === 'system' && systemDark)
  const notify = useCallback((message: string, tone: 'neutral' | 'danger' | 'success' = 'neutral') => setToast({ message, tone }), [])
  const clearToast = useCallback(() => setToast({ message: '' }), [])

  const traceQuery = useMemo<JsonRecord>(() => {
    const query: JsonRecord = { limit: TRACE_PAGE_SIZE, ...traceFilters }
    const after = rangeStart(range)
    if (after)
      query.started_after = after
    if (scope === 'demo')
      query.is_demo = 'true'
    if (scope === 'real')
      query.is_demo = 'false'
    return query
  }, [traceFilters, range, scope])
  const queryRef = useRef(traceQuery)
  queryRef.current = traceQuery
  const selectedRef = useRef({ traceId: selectedTraceId, spanId: selectedSpan?.span_id })
  selectedRef.current = { traceId: selectedTraceId, spanId: selectedSpan?.span_id }

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media)
      return
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const setTheme = useCallback((next: ThemeSetting) => {
    setThemeState(next)
    writeStorage(THEME_KEY, next)
  }, [])

  const loadTrace = useCallback(async (traceId: string, keepSpanId?: string) => {
    if (!traceId)
      return
    setTraceLoading(true)
    try {
      const detail = await getTrace(traceId)
      if (selectedRef.current.traceId !== traceId)
        return
      setTraceDetail(detail)
      const rootCause = detail.insights?.findings.find(finding => finding.kind === 'root_cause')?.span_id
      setSelectedSpan(detail.spans.find(span => span.span_id === keepSpanId) ?? defaultSpan(detail.spans, rootCause))
    }
    catch (caught) {
      notify(`Could not load trace: ${errorText(caught)}`, 'danger')
    }
    finally {
      setTraceLoading(false)
    }
  }, [notify])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [
        health,
        overview,
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
        sessions,
        integrations,
        rules,
      ] = await Promise.all([
        getHealth(),
        getOverview(),
        listTraces(queryRef.current),
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
        listSessions(),
        getIntegrations(),
        listAlertRules().catch(() => [] as AlertRule[]),
      ])
      setVersion(integrations.version || stringValue(health.version) || undefined)
      setData({ overview, traces, workflows, agents, providers, models, modelCalls, costs, costByWorkflow, costByAgent, costByModel, costByProvider, costByFailedRun, toolCalls, memoryRecords, memoryOperations, ragRetrievals, prompts, evaluations, evaluationSummary, approvals, checkpoints, auditLogs, sessions, integrations })
      setAlertRules(rules)
      const now = new Date().toISOString()
      setConnection(current => ({ ...current, backendStatus: 'ok', lastSuccessfulRefresh: now, lastUpdated: now, lastFailedEndpoint: null, lastError: null }))
      if (selectedRef.current.traceId)
        await loadTrace(selectedRef.current.traceId, selectedRef.current.spanId)
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
      setLoaded(true)
    }
  }, [loadTrace])

  useEffect(() => {
    void refresh()
  }, [traceQuery, apiKeyVersion, refresh])

  // Open the first workflow graph once workflows are known.
  useEffect(() => {
    const first = data.workflows[0]?.workflow_id
    if (first && !workflowGraph)
      void getWorkflowGraph(first).then(setWorkflowGraph).catch(() => undefined)
  }, [data.workflows, workflowGraph])

  useEffect(() => {
    const onLiveEvent = (type: string, payloadText: string) => {
      if (type !== 'trace_event')
        return
      const now = new Date().toISOString()
      let traceId: string | undefined
      let liveType = type
      try {
        const payload = JSON.parse(payloadText) as JsonRecord
        traceId = stringValue(payload.trace_id) || undefined
        liveType = stringValue(payload.live_event || type)
      }
      catch {
        traceId = undefined
      }
      setLiveEvents(current => [{ type: liveType, at: now, trace_id: traceId }, ...current].slice(0, 40))
      setConnection(current => ({ ...current, liveStatus: 'connected', lastLiveEvent: now }))
      if (liveRefreshTimer.current === null) {
        liveRefreshTimer.current = window.setTimeout(() => {
          liveRefreshTimer.current = null
          void refresh()
        }, 1800)
      }
    }
    const close = subscribeLiveEvents({
      onOpen: () => setConnection(current => ({ ...current, liveStatus: 'connected' })),
      onEvent: onLiveEvent,
      onError: () => setConnection(current => ({ ...current, liveStatus: 'disconnected' })),
    })
    return () => {
      if (liveRefreshTimer.current !== null)
        window.clearTimeout(liveRefreshTimer.current)
      close()
    }
  }, [refresh, apiKeyVersion])

  // Keep the address bar shareable: ?page=..., ?trace=..., the time range, and trace filters.
  useEffect(() => {
    const params = new URLSearchParams()
    if (section === 'traces' && selectedTraceId)
      params.set('trace', selectedTraceId)
    else if (section !== 'overview')
      params.set('page', section)
    if (range !== '24h')
      params.set('range', range)
    if (section === 'traces' && !selectedTraceId) {
      for (const key of TRACE_FILTER_KEYS) {
        if (traceFilters[key])
          params.set(key, traceFilters[key]!)
      }
    }
    const next = `${window.location.pathname}${params.toString() ? `?${params}` : ''}`
    if (next !== `${window.location.pathname}${window.location.search}`)
      window.history.replaceState(null, '', next)
  }, [section, selectedTraceId, range, traceFilters])

  useEffect(() => {
    setOlderTraces({ rows: [], lastPageFull: false, loading: false })
  }, [traceQuery])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(value => !value)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // "g" then a letter jumps to a page, as in GitHub and Linear; "?" lists every shortcut.
  const pendingGo = useRef<number | null>(null)
  useShortcuts({
    '?': () => setShortcutsOpen(true),
    '/': () => setCommandOpen(true),
    g: () => {
      if (pendingGo.current !== null)
        window.clearTimeout(pendingGo.current)
      pendingGo.current = window.setTimeout(() => { pendingGo.current = null }, 1200)
    },
    ...Object.fromEntries(Object.entries(GO_TO).map(([key, target]) => [key, () => {
      if (pendingGo.current === null)
        return
      window.clearTimeout(pendingGo.current)
      pendingGo.current = null
      navigate(target)
    }])),
  })

  // Opening a page from the sidebar or palette always shows its top level, so Traces returns to the list.
  const navigate = useCallback((next: Section) => {
    setSection(next)
    setSelectedTraceId('')
    setFocusedSession('')
    window.scrollTo({ top: 0 })
  }, [])

  const openTrace = useCallback((traceId: string) => {
    setSection('traces')
    setSelectedTraceId(traceId)
    selectedRef.current = { traceId, spanId: undefined }
    setTraceDetail(current => current?.trace?.trace_id === traceId ? current : null)
    window.scrollTo({ top: 0 })
    void loadTrace(traceId)
  }, [loadTrace])

  const openSession = useCallback((sessionId: string) => {
    navigate('sessions')
    setFocusedSession(sessionId)
  }, [navigate])

  const closeTrace = useCallback(() => {
    setSelectedTraceId('')
    setTraceDetail(null)
    setSelectedSpan(null)
  }, [])

  async function handleExport(traceId: string, format: 'json' | 'otel-json' = 'json') {
    try {
      const payload = await exportTrace(traceId, format)
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = format === 'otel-json' ? `${traceId}.otel.json` : `${traceId}.json`
      anchor.click()
      URL.revokeObjectURL(url)
    }
    catch (caught) {
      notify(`Export failed: ${errorText(caught)}`, 'danger')
    }
  }

  async function handleReplay(traceId: string, spanId?: string) {
    try {
      const replay = spanId
        ? await createReplayFromSpan(traceId, spanId, { mode: 'deterministic-from-span', side_effects_disabled: true })
        : await createReplay(traceId, { mode: 'deterministic', side_effects_disabled: true })
      setReplayResult(replay)
      navigate('replay')
    }
    catch (caught) {
      notify(`Replay failed: ${errorText(caught)}`, 'danger')
    }
  }

  // The first page of traces comes with every refresh; older pages load on request and reset when the query changes.
  const allTraces = useMemo(() => [...data.traces, ...olderTraces.rows], [data.traces, olderTraces.rows])
  const hasMoreTraces = olderTraces.rows.length ? olderTraces.lastPageFull : data.traces.length >= TRACE_PAGE_SIZE

  async function loadMoreTraces() {
    setOlderTraces(current => ({ ...current, loading: true }))
    try {
      const page = await listTraces({ ...traceQuery, offset: allTraces.length })
      setOlderTraces(current => {
        const known = new Set([...data.traces, ...current.rows].map(trace => trace.trace_id))
        return { rows: [...current.rows, ...page.filter(trace => !known.has(trace.trace_id))], lastPageFull: page.length >= TRACE_PAGE_SIZE, loading: false }
      })
    }
    catch (caught) {
      setOlderTraces(current => ({ ...current, loading: false }))
      notify(`Could not load more traces: ${errorText(caught)}`, 'danger')
    }
  }

  const pendingApprovals = data.approvals.filter(approval => PENDING_APPROVAL.has(approval.status)).length
  const firingAlerts = alertRules.filter(rule => rule.enabled && rule.state === 'firing').length
  const traceIndex = allTraces.findIndex(trace => trace.trace_id === selectedTraceId)
  const traceOpen = section === 'traces' && Boolean(selectedTraceId)

  const page = (() => {
    switch (section) {
      case 'overview':
        return <OverviewPage loaded={loaded} traces={data.traces} range={range} overview={data.overview} providers={data.providers} models={data.models} costs={data.costs} liveEvents={liveEvents} pendingApprovals={pendingApprovals} firingAlerts={firingAlerts} onTrace={openTrace} onSection={navigate} onFilterTraces={filters => { setTraceFilters(filters); navigate('traces') }} />
      case 'traces':
        return traceOpen
          ? (
              <TraceView
                detail={traceDetail?.trace?.trace_id === selectedTraceId ? traceDetail : null}
                loading={traceLoading}
                selectedSpan={selectedSpan}
                candidates={allTraces}
                position={traceIndex >= 0 ? { index: traceIndex, total: allTraces.length } : null}
                onSelectSpan={setSelectedSpan}
                onClose={closeTrace}
                onPrev={traceIndex > 0 ? () => openTrace(allTraces[traceIndex - 1].trace_id) : undefined}
                onNext={traceIndex >= 0 && traceIndex < allTraces.length - 1 ? () => openTrace(allTraces[traceIndex + 1].trace_id) : undefined}
                onExport={handleExport}
                onReplay={handleReplay}
                onOpenTrace={openTrace}
                onValidate={traceId => {
                  void navigator.clipboard?.writeText(`agentmesh validate traces --trace ${traceId}`)
                  notify('Copied the validation command to the clipboard.', 'success')
                }}
                onOpenSession={openSession}
                onNotify={notify}
              />
            )
          : <TracesPage loading={loading && !loaded} traces={allTraces} hasMore={hasMoreTraces} loadingMore={olderTraces.loading} onLoadMore={() => void loadMoreTraces()} filters={traceFilters} onFilters={setTraceFilters} workflows={data.workflows} providers={data.providers} models={data.models} range={range} onOpen={openTrace} />
      case 'sessions':
        return <SessionsPage key={focusedSession} sessions={data.sessions} initialSessionId={focusedSession} onTraceSelect={openTrace} />
      case 'datasets':
        return <DatasetsPage refreshKey={connection.lastSuccessfulRefresh} initialExperimentId={link.experimentId} onTraceSelect={openTrace} />
      case 'alerts':
        return <AlertsPage refreshKey={connection.lastSuccessfulRefresh} onChanged={() => void listAlertRules().then(setAlertRules).catch(() => undefined)} />
      case 'connect':
        return <ConnectPage integrations={data.integrations} hasTraces={data.traces.length > 0} />
      case 'workflows':
        return <WorkflowsPage workflows={data.workflows} traces={data.traces} approvals={data.approvals} checkpoints={data.checkpoints} activeGraph={workflowGraph} onGraph={workflowId => void getWorkflowGraph(workflowId).then(setWorkflowGraph)} onNodeReplay={handleReplay} onTrace={openTrace} />
      case 'agents':
        return <AgentsPage agents={data.agents} traces={data.traces} modelCalls={data.modelCalls} toolCalls={data.toolCalls} onTrace={openTrace} />
      case 'models':
        return <ModelsPage providers={data.providers} models={data.models} modelCalls={data.modelCalls} onTrace={openTrace} />
      case 'tools':
        return <ToolsPage toolCalls={data.toolCalls} onTrace={openTrace} />
      case 'memory':
        return <MemoryRagPage memoryRecords={data.memoryRecords} operations={data.memoryOperations} retrievals={data.ragRetrievals} onTrace={openTrace} />
      case 'prompts':
        return <PromptsPage prompts={data.prompts} />
      case 'costs':
        return <CostsPage summary={data.costs} traces={data.traces} range={range} byWorkflow={data.costByWorkflow} byAgent={data.costByAgent} byModel={data.costByModel} byProvider={data.costByProvider} byFailedRun={data.costByFailedRun} onTrace={openTrace} />
      case 'evaluations':
        return <EvaluationsPage summary={data.evaluationSummary} evaluations={data.evaluations} onTrace={openTrace} onSection={navigate} onRun={() => void runEvaluation({ evaluator: 'mock-evaluator', evaluator_type: 'deterministic_mock', score: 0.9, passed: true }).then(() => refresh())} />
      case 'approvals':
        return <ApprovalsPage approvals={data.approvals} onTrace={openTrace} onApprove={id => void approveRequest(id).then(() => { notify('Approved.', 'success'); return refresh() })} onReject={id => void rejectRequest(id).then(() => { notify('Rejected.'); return refresh() })} />
      case 'replay':
        return <ReplayPage checkpoints={data.checkpoints} replay={replayResult} traces={data.traces} trace={traceDetail?.trace ?? null} selectedSpan={selectedSpan} onReplay={handleReplay} onTrace={openTrace} />
      default:
        return <SettingsPage auditLogs={data.auditLogs} providers={data.providers} costs={data.costs} integrations={data.integrations} theme={theme} onTheme={setTheme} onApiKey={key => { setApiKey(key); setApiKeyVersion(value => value + 1) }} />
    }
  })()

  return (
    <div className="flex min-h-dvh bg-canvas text-fg">
      <Sidebar
        section={section}
        onSection={navigate}
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed(value => {
          writeStorage(SIDEBAR_KEY, value ? '0' : '1')
          return !value
        })}
        badges={{
          approvals: pendingApprovals ? { value: pendingApprovals, tone: 'warning' } : undefined,
          alerts: firingAlerts ? { value: firingAlerts, tone: 'danger' } : undefined,
        }}
        version={version}
        mobileOpen={mobileNav}
        onMobileClose={() => setMobileNav(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          section={section}
          crumb={traceOpen ? traceDetail?.trace?.workflow_name ?? traceDetail?.trace?.name ?? 'Trace' : undefined}
          onCrumbRoot={closeTrace}
          onOpenCommand={() => setCommandOpen(true)}
          range={range}
          onRange={setRange}
          scope={scope}
          onScope={setScope}
          liveStatus={connection.liveStatus}
          lastUpdated={connection.lastUpdated}
          loading={loading}
          onRefresh={() => void refresh()}
          theme={theme}
          onTheme={setTheme}
          onMobileMenu={() => setMobileNav(true)}
        />
        <main className="mx-auto flex w-full max-w-[1600px] min-w-0 flex-1 flex-col gap-5 px-4 py-5 lg:px-6 lg:py-6">
          <ConnectionBanner
            connection={connection}
            error={error}
            onRetry={() => void refresh()}
            onApiKey={key => {
              setApiKey(key)
              setApiKeyVersion(value => value + 1)
            }}
          />
          {/* Until the first successful load, show placeholders rather than empty pages full of zeros. */}
          {connection.lastSuccessfulRefresh || section === 'settings'
            ? (
                <div key={traceOpen ? `trace-${selectedTraceId}` : section} className="animate-fade-in flex min-w-0 flex-col gap-5">
                  {page}
                </div>
              )
            : !error && (
                <div className="flex flex-col gap-5" aria-busy="true">
                  <Skeleton className="h-10 w-72" />
                  <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-[106px] rounded-xl" />)}</div>
                  <div className="grid grid-cols-1 gap-4 xl:grid-cols-3"><Skeleton className="h-72 rounded-xl xl:col-span-2" /><Skeleton className="h-72 rounded-xl" /></div>
                </div>
              )}
        </main>
      </div>
      <CommandPalette
        open={commandOpen}
        onClose={() => setCommandOpen(false)}
        traces={data.traces}
        sessions={data.sessions}
        onSection={navigate}
        onTrace={openTrace}
        onSession={openSession}
        onRefresh={() => void refresh()}
        onToggleTheme={() => setTheme(dark ? 'light' : 'dark')}
        onShowShortcuts={() => setShortcutsOpen(true)}
        dark={dark}
      />
      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <Toast message={toast.message} tone={toast.tone} onDone={clearToast} />
    </div>
  )
}
