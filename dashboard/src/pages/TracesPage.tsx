import { Download, Filter, Waypoints, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts'
import { Badge, StatusDot } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, PageHeader, Skeleton } from '../components/ui/Card'
import { axisProps, ChartTooltip } from '../components/ui/Chart'
import { CopyableId } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Input, SearchInput, Select } from '../components/ui/Field'
import { Segmented } from '../components/ui/Tabs'
import { cn } from '../lib/utils'
import type { ModelUsage, ProviderHealth, TraceSummary, WorkflowSummary } from '../types'
import { formatCompact, formatMoney, formatMs, formatNumber, formatRelative, numeric } from '../utils/format'
import { buildSeries, TIME_RANGES, traceDuration, type TimeRange } from '../utils/traces'

export interface TraceFilters {
  q?: string
  status?: string
  workflow?: string
  provider?: string
  model?: string
  agent?: string
  tool?: string
  error_type?: string
  session_id?: string
}

const STATUS_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'failed', label: 'Errors' },
  { value: 'succeeded', label: 'Success' },
  { value: 'running', label: 'Running' },
]

export function TracesPage({
  loading,
  traces,
  hasMore,
  loadingMore,
  onLoadMore,
  filters,
  onFilters,
  workflows,
  providers,
  models,
  range,
  onOpen,
}: {
  loading: boolean
  traces: TraceSummary[]
  hasMore: boolean
  loadingMore: boolean
  onLoadMore: () => void
  filters: TraceFilters
  onFilters: (filters: TraceFilters) => void
  workflows: WorkflowSummary[]
  providers: ProviderHealth[]
  models: ModelUsage[]
  range: TimeRange
  onOpen: (traceId: string) => void
}) {
  const [search, setSearch] = useState(filters.q ?? '')
  const [moreOpen, setMoreOpen] = useState(Boolean(filters.agent || filters.tool || filters.error_type || filters.session_id))
  const set = (patch: TraceFilters) => {
    const next = { ...filters, ...patch }
    for (const key of Object.keys(next) as Array<keyof TraceFilters>) {
      if (!next[key])
        delete next[key]
    }
    onFilters(next)
  }

  // Search as you type, without refetching on every keystroke.
  useEffect(() => {
    if ((filters.q ?? '') === search)
      return
    const timer = window.setTimeout(() => set({ q: search }), 350)
    return () => window.clearTimeout(timer)
  })

  const series = useMemo(() => buildSeries(traces, range), [traces, range])
  const maxDuration = Math.max(...traces.map(traceDuration), 1)
  const errors = traces.filter(trace => trace.status === 'failed').length
  const active = (['workflow', 'provider', 'model', 'agent', 'tool', 'error_type', 'session_id'] as const).filter(key => filters[key])
  const rangeTitle = TIME_RANGES.find(item => item.value === range)?.title ?? ''
  const modelOptions = [...new Set(models.map(model => model.model))]

  return (
    <>
      <PageHeader
        title="Traces"
        description={`${formatNumber(traces.length)}${hasMore ? '+' : ''} traces · ${formatNumber(errors)} failed · ${rangeTitle.toLowerCase()}`}
        actions={<Button icon={<Download />} disabled={traces.length === 0} onClick={() => downloadCsv(traces)} title="Download the traces shown below as CSV">Export CSV</Button>}
      />

      <Card flush>
        <div className="flex flex-col gap-3 border-b border-line p-3">
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput className="w-full sm:w-72" value={search} onChange={setSearch} onSubmit={() => set({ q: search })} placeholder="Search name, id, input, error" />
            <Segmented value={filters.status ?? ''} onChange={value => set({ status: value })} options={STATUS_OPTIONS} />
            <Select aria-label="Workflow" className="w-44" value={filters.workflow ?? ''} onChange={event => set({ workflow: event.target.value })}>
              <option value="">All workflows</option>
              {workflows.map(workflow => <option key={workflow.workflow_id} value={workflow.workflow_name}>{workflow.workflow_name}</option>)}
            </Select>
            <Select aria-label="Model" className="w-44" value={filters.model ?? ''} onChange={event => set({ model: event.target.value })}>
              <option value="">All models</option>
              {modelOptions.map(model => <option key={model} value={model}>{model}</option>)}
            </Select>
            <Select aria-label="Provider" className="w-40" value={filters.provider ?? ''} onChange={event => set({ provider: event.target.value })}>
              <option value="">All providers</option>
              {providers.filter(provider => provider.calls > 0).map(provider => <option key={provider.provider} value={provider.provider}>{provider.display_name}</option>)}
            </Select>
            <Button variant={moreOpen ? 'subtle' : 'ghost'} icon={<Filter />} onClick={() => setMoreOpen(value => !value)}>
              More filters
            </Button>
            {(active.length > 0 || filters.status || filters.q) && (
              <Button variant="ghost" icon={<X />} onClick={() => { setSearch(''); onFilters({}) }}>Clear</Button>
            )}
          </div>
          {moreOpen && (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
              <FilterInput label="Agent" placeholder="Agent name" value={filters.agent ?? ''} onCommit={value => set({ agent: value })} />
              <FilterInput label="Tool" placeholder="Tool name" value={filters.tool ?? ''} onCommit={value => set({ tool: value })} />
              <FilterInput label="Error type" placeholder="Error type" value={filters.error_type ?? ''} onCommit={value => set({ error_type: value })} />
              <FilterInput label="Session" placeholder="Session id" value={filters.session_id ?? ''} onCommit={value => set({ session_id: value })} />
            </div>
          )}
          {active.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {active.map(key => (
                <button key={key} className="inline-flex h-6 items-center gap-1 rounded-md border border-line bg-surface-2 px-2 text-xs text-fg-muted hover:border-line-strong hover:text-fg" onClick={() => set({ [key]: '' })}>
                  <span className="text-fg-subtle">{key.replace('_', ' ')}:</span>{filters[key]}<X className="size-3" />
                </button>
              ))}
            </div>
          )}
        </div>

        <div className={cn('h-20 border-b border-line px-3 pt-2', traces.length === 0 && 'hidden')}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={series} barCategoryGap={1} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
              <XAxis dataKey="label" {...axisProps} height={16} tickMargin={2} interval="preserveStartEnd" minTickGap={60} />
              <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<ChartTooltip />} />
              <Bar dataKey="ok" name="Success" stackId="a" fill="var(--chart-1)" maxBarSize={20} />
              <Bar dataKey="errors" name="Failed" stackId="a" fill="var(--danger)" radius={[2, 2, 0, 0]} maxBarSize={20} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {loading
          ? <div className="flex flex-col gap-2 p-4">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-9" />)}</div>
          : (
              <DataTable
                rows={traces}
                rowKey={row => row.trace_id}
                onRow={row => onOpen(row.trace_id)}
                minWidth={920}
                empty={active.length > 0 || filters.status || filters.q
                  ? <EmptyState icon={<Waypoints />} title="No traces match" detail="Try a wider time range or clear the filters." />
                  : <EmptyState icon={<Waypoints />} title={`No traces in the ${rangeTitle.toLowerCase()}`} detail="Send traces from the Python or TypeScript SDK or any OpenTelemetry exporter (see Connect), or pick a wider time range." />}
                rowClassName={row => cn(row.status === 'failed' && 'shadow-[inset_2px_0_0_var(--danger)]')}
                columns={[
                  {
                    label: 'Name',
                    sortValue: row => row.workflow_name ?? row.name,
                    render: row => (
                      <span className="flex min-w-0 items-center gap-3">
                        <StatusDot status={row.status} pulse={row.status === 'running'} />
                        <span className="min-w-0">
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate font-medium text-fg">{row.workflow_name ?? row.name}</span>
                            {row.session_id && <Badge tone="info" title={`Session ${row.session_id}`}>session</Badge>}
                            {row.is_demo && <Badge outline>demo</Badge>}
                            {row.source && row.source !== 'runtime' && <Badge outline>{row.source}</Badge>}
                          </span>
                          <span className="flex min-w-0 items-center gap-2 text-xs">
                            <CopyableId value={row.trace_id} />
                            {row.error_message && <span className="max-w-sm truncate text-danger-text">{row.error_type ? `${row.error_type}: ` : ''}{row.error_message}</span>}
                          </span>
                        </span>
                      </span>
                    ),
                  },
                  ...(traces.some(trace => trace.model)
                    ? [{ label: 'Model', sortValue: (row: TraceSummary) => row.model ?? '', render: (row: TraceSummary) => row.model ? <span className="flex flex-col"><span className="text-fg">{row.model}</span><span className="text-xs text-fg-subtle">{row.provider}</span></span> : <span className="text-fg-subtle">-</span> }]
                    : []),
                  { label: 'Spans', align: 'right', sortValue: row => numeric(row.span_count), render: row => formatNumber(row.span_count) },
                  { label: 'Tokens', align: 'right', sortValue: row => numeric(row.total_tokens), render: row => numeric(row.total_tokens) ? formatCompact(row.total_tokens) : <span className="text-fg-subtle">-</span> },
                  { label: 'Cost', align: 'right', sortValue: row => numeric(row.estimated_cost), render: row => numeric(row.estimated_cost) ? formatMoney(row.estimated_cost) : <span className="text-fg-subtle">-</span> },
                  {
                    label: 'Duration',
                    align: 'right',
                    width: '180px',
                    sortValue: row => traceDuration(row),
                    render: row => (
                      <span className="flex items-center justify-end gap-2.5">
                        <span className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-surface-3 md:block">
                          <span className={cn('block h-full rounded-full', row.status === 'failed' ? 'bg-danger' : 'bg-accent')} style={{ width: `${Math.max((traceDuration(row) / maxDuration) * 100, 2)}%` }} />
                        </span>
                        <span className="tabular w-14 text-right">{formatMs(traceDuration(row))}</span>
                      </span>
                    ),
                  },
                  { label: 'Started', align: 'right', sortValue: row => Date.parse(row.started_at), render: row => <span className="whitespace-nowrap text-fg-muted" title={new Date(row.started_at).toLocaleString()}>{formatRelative(row.started_at)}</span> },
                ]}
              />
            )}
        {hasMore && !loading && (
          <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5 text-xs text-fg-subtle">
            <span>Showing the newest {formatNumber(traces.length)} traces.</span>
            <Button size="sm" disabled={loadingMore} onClick={onLoadMore}>{loadingMore ? 'Loading...' : 'Load older traces'}</Button>
          </div>
        )}
      </Card>
    </>
  )
}

const CSV_COLUMNS: Array<[string, (trace: TraceSummary) => unknown]> = [
  ['trace_id', trace => trace.trace_id],
  ['name', trace => trace.workflow_name ?? trace.name],
  ['status', trace => trace.status],
  ['started_at', trace => trace.started_at],
  ['duration_ms', trace => traceDuration(trace)],
  ['spans', trace => trace.span_count],
  ['total_tokens', trace => trace.total_tokens],
  ['estimated_cost_usd', trace => trace.estimated_cost],
  ['error_type', trace => trace.error_type],
  ['error_message', trace => trace.error_message],
  ['session_id', trace => trace.session_id],
  ['user_id', trace => trace.user_id],
  ['source', trace => trace.source],
  ['environment', trace => trace.environment],
]

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value)
  // Quote every field that could break a row, and neutralize spreadsheet formulas.
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text
  return /[",\n\r]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe
}

function downloadCsv(traces: TraceSummary[]) {
  const lines = [CSV_COLUMNS.map(([name]) => name).join(','), ...traces.map(trace => CSV_COLUMNS.map(([, get]) => csvCell(get(trace))).join(','))]
  const url = URL.createObjectURL(new Blob([`${lines.join('\r\n')}\r\n`], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `agentmesh-traces-${new Date().toISOString().slice(0, 19).replaceAll(':', '-')}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}

/** Text filter that applies after typing pauses, so each keystroke does not refetch. */
function FilterInput({ label, placeholder, value, onCommit }: { label: string; placeholder: string; value: string; onCommit: (value: string) => void }) {
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value])
  useEffect(() => {
    if (text === value)
      return
    const timer = window.setTimeout(() => onCommit(text.trim()), 450)
    return () => window.clearTimeout(timer)
  }, [text, value, onCommit])
  return <Input aria-label={label} placeholder={placeholder} value={text} onChange={event => setText(event.target.value)} />
}
