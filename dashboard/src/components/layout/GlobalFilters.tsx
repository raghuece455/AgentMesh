import { Copy, RefreshCw, Wifi, WifiOff } from 'lucide-react'
import type { ConnectionState } from '../../appTypes'
import type { JsonRecord, ModelUsage, ProviderHealth, WorkflowSummary } from '../../types'
import { formatTime, scopeFromFilters, stringValue } from '../../utils/format'
import { StatusDot } from '../common/Badges'
import { FilterSelect } from '../common/Inputs'

export function GlobalFilters({
  filters,
  workflows,
  providers,
  models,
  connection,
  health,
  onFilters,
  onRefresh,
}: {
  filters: JsonRecord
  workflows: WorkflowSummary[]
  providers: ProviderHealth[]
  models: ModelUsage[]
  connection: ConnectionState
  health: JsonRecord | null
  onFilters: (filters: JsonRecord) => void
  onRefresh: () => void
}) {
  const dataScope = scopeFromFilters(filters)
  const apply = (patch: JsonRecord) => onFilters({ ...filters, ...patch })
  const setDataScope = (scope: string) => {
    const next = { ...filters }
    delete next.environment
    delete next.is_demo
    if (scope === 'demo')
      next.is_demo = 'true'
    if (scope === 'real')
      next.is_demo = 'false'
    onFilters(next)
  }
  const setTimeRange = (range: string) => {
    const next: JsonRecord = { ...filters, time_range: range }
    delete next.started_after
    delete next.started_before
    const now = Date.now()
    if (range === '1h')
      next.started_after = new Date(now - 60 * 60 * 1000).toISOString()
    if (range === '24h')
      next.started_after = new Date(now - 24 * 60 * 60 * 1000).toISOString()
    if (range === '7d')
      next.started_after = new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString()
    if (range === '30d')
      next.started_after = new Date(now - 30 * 24 * 60 * 60 * 1000).toISOString()
    onFilters(next)
  }
  const configured = providers.length
  const healthy = providers.filter(provider => provider.status === 'healthy').length
  return (
    <section className="vision-glass-soft border-white/20 bg-slate-950/18 p-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-[1fr_1fr_1.4fr_1.2fr_1fr_auto]">
        <FilterSelect label="Environment" value={dataScope} options={[['all', 'All data'], ['real', 'Real runs'], ['demo', 'Demo only']]} onChange={setDataScope} />
        <FilterSelect label="Time range" value={stringValue(filters.time_range || '24h')} options={[['1h', 'Last hour'], ['24h', 'Last 24h'], ['7d', 'Last 7d'], ['30d', 'Last 30d'], ['all', 'All time']]} onChange={setTimeRange} />
        <FilterSelect
          label="Workflow"
          value={stringValue(filters.workflow_id || filters.workflow)}
          options={[['', 'All workflows'], ...workflows.map(workflow => [workflow.workflow_id, workflow.workflow_name] as [string, string])]}
          onChange={value => apply({ workflow_id: value, workflow: value })}
        />
        <FilterSelect
          label="Provider / model"
          value={stringValue(filters.provider_model)}
          options={[
            ['', 'All providers/models'],
            ...providers.map(provider => [`provider:${provider.provider}`, `Provider: ${provider.display_name}`] as [string, string]),
            ...models.map(model => [`model:${model.model}`, `Model: ${model.model}`] as [string, string]),
          ]}
          onChange={value => {
            const next: JsonRecord = { ...filters, provider_model: value }
            delete next.provider
            delete next.model
            if (value.startsWith('provider:'))
              next.provider = value.replace('provider:', '')
            if (value.startsWith('model:'))
              next.model = value.replace('model:', '')
            onFilters(next)
          }}
        />
        <FilterSelect label="Status" value={stringValue(filters.status)} options={[['', 'All statuses'], ['succeeded', 'Succeeded'], ['failed', 'Failed'], ['running', 'Running'], ['waiting_approval', 'Waiting approval']]} onChange={value => apply({ status: value })} />
        <div className="flex items-end gap-2">
          <button className="trace-action h-9 px-3" onClick={onRefresh}><RefreshCw className="size-4" />Refresh</button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs/5 text-white/62">
        <StatusDot status={connection.backendStatus === 'ok' ? 'ok' : connection.backendStatus === 'failed' ? 'failed' : 'checking'} />
        <span>Backend {String(health?.status ?? connection.backendStatus)}</span>
        <span className="text-white/28">/</span>
        {connection.liveStatus === 'connected' ? <Wifi className="size-3.5 text-emerald-200" /> : <WifiOff className="size-3.5 text-rose-200" />}
        <span>SSE {connection.liveStatus}</span>
        <span className="text-white/28">/</span>
        <span>{healthy} healthy / {configured} configured providers</span>
        <span className="text-white/28">/</span>
        <span>Last updated {formatTime(connection.lastUpdated)}</span>
      </div>
    </section>
  )
}

export function ConnectionDiagnostics({ connection, error, onRetry }: { connection: ConnectionState; error: string; onRetry: () => void }) {
  if (!error && connection.backendStatus === 'ok')
    return null
  const diagnostics = {
    failed_endpoint: connection.lastFailedEndpoint,
    error: connection.lastError || error,
    backend_status: connection.backendStatus,
    live_status: connection.liveStatus,
    last_successful_refresh: connection.lastSuccessfulRefresh,
    last_live_event: connection.lastLiveEvent,
    retry_count: connection.retryCount,
  }
  return (
    <section className="rounded-3xl border border-amber-200/28 bg-amber-500/10 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="text-sm/6 font-semibold text-amber-50">Connection diagnostics</div>
          <div className="mt-1 text-sm/6 text-amber-50/78">The dashboard could not refresh one or more observability APIs.</div>
          <div className="mt-3 grid grid-cols-1 gap-2 text-xs/5 text-white/74 md:grid-cols-2 xl:grid-cols-5">
            <span>Endpoint: {connection.lastFailedEndpoint ?? 'unknown'}</span>
            <span>Backend: {connection.backendStatus}</span>
            <span>SSE: {connection.liveStatus}</span>
            <span>Last success: {formatTime(connection.lastSuccessfulRefresh)}</span>
            <span>Retries: {connection.retryCount}</span>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button className="trace-action" onClick={onRetry}><RefreshCw className="size-4" />Retry</button>
          <button className="trace-action" onClick={() => void navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2))}><Copy className="size-4" />Copy diagnostics</button>
        </div>
      </div>
    </section>
  )
}
