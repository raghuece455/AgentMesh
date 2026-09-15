import { Activity, AlertOctagon, ArrowRight, BellRing, Coins, Gauge, Plug, Radio, Timer, Waypoints } from 'lucide-react'
import { useMemo } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { LiveEventRecord, Section } from '../appTypes'
import { Badge, StatusBadge, StatusDot } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, Meter, PageHeader, Skeleton } from '../components/ui/Card'
import { axisProps, ChartLegend, ChartTooltip, gridProps } from '../components/ui/Chart'
import { DataTable } from '../components/ui/DataTable'
import { StatCard } from '../components/ui/Stat'
import type { CostCenterSummary, ModelUsage, OverviewData, ProviderHealth, TraceSummary } from '../types'
import { formatCompact, formatMoney, formatMs, formatNumber, formatPercent, formatRelative, numeric } from '../utils/format'
import { buildSeries, groupIssues, percentile, TIME_RANGES, traceDuration, type TimeRange } from '../utils/traces'
import type { TraceFilters } from './TracesPage'

export function OverviewPage({
  loaded,
  traces,
  range,
  overview,
  providers,
  models,
  costs,
  liveEvents,
  pendingApprovals,
  firingAlerts,
  onTrace,
  onSection,
  onFilterTraces,
}: {
  loaded: boolean
  traces: TraceSummary[]
  range: TimeRange
  overview: OverviewData | null
  providers: ProviderHealth[]
  models: ModelUsage[]
  costs: CostCenterSummary | null
  liveEvents: LiveEventRecord[]
  pendingApprovals: number
  firingAlerts: number
  onTrace: (traceId: string) => void
  onSection: (section: Section) => void
  onFilterTraces: (filters: TraceFilters) => void
}) {
  const series = useMemo(() => buildSeries(traces, range), [traces, range])
  const issues = useMemo(() => groupIssues(traces), [traces])
  const rangeTitle = TIME_RANGES.find(item => item.value === range)?.title ?? ''

  const total = traces.length
  const errors = traces.filter(trace => trace.status === 'failed').length
  const errorRate = total ? errors / total : 0
  const durations = traces.map(traceDuration).filter(Boolean)
  const p95 = percentile(durations, 95)
  const p50 = percentile(durations, 50)
  const tokens = traces.reduce((sum, trace) => sum + numeric(trace.total_tokens), 0)
  const cost = traces.reduce((sum, trace) => sum + numeric(trace.estimated_cost), 0)
  const attention = firingAlerts + pendingApprovals + issues.length

  if (!loaded) {
    return (
      <>
        <PageHeader title="Overview" description="Loading observability data..." />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-[106px] rounded-xl" />)}</div>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3"><Skeleton className="h-72 rounded-xl xl:col-span-2" /><Skeleton className="h-72 rounded-xl" /></div>
      </>
    )
  }

  const activeProviders = providers.filter(provider => provider.status !== 'not_configured' && provider.status !== 'planned')
  const idleProviders = providers.length - activeProviders.length
  const topModels = [...models].sort((a, b) => numeric(b.estimated_cost) - numeric(a.estimated_cost) || numeric(b.total_tokens) - numeric(a.total_tokens)).slice(0, 6)
  const maxModelCost = Math.max(...topModels.map(model => numeric(model.estimated_cost)), 0)
  const maxModelTokens = Math.max(...topModels.map(model => numeric(model.total_tokens)), 0)

  return (
    <>
      <PageHeader
        title="Overview"
        description={`${rangeTitle} across every agent, workflow, and model.`}
        actions={<Button icon={<Plug />} onClick={() => onSection('connect')}>Connect an agent</Button>}
      />

      {total === 0 && (
        <Card>
          <EmptyState
            icon={<Waypoints />}
            title={`No traces in the ${rangeTitle.toLowerCase()}`}
            detail="Point any OpenTelemetry exporter or the AgentMesh Python and TypeScript SDKs at this server, or widen the time range."
            action={<Button variant="primary" icon={<Plug />} onClick={() => onSection('connect')}>Send your first trace</Button>}
          />
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
        <StatCard label="Traces" icon={<Waypoints />} value={formatNumber(total)} sub={`${formatNumber(total - errors)} ok · ${formatNumber(errors)} failed`} spark={series.map(point => point.runs)} onClick={() => onFilterTraces({})} />
        <StatCard label="Error rate" icon={<AlertOctagon />} value={formatPercent(errorRate)} sub={`${errors} failed traces`} tone={errorRate > 0.1 ? 'danger' : errorRate > 0 ? 'warning' : 'neutral'} spark={series.map(point => point.errors)} sparkColor="var(--danger)" onClick={() => onFilterTraces({ status: 'failed' })} />
        <StatCard label="p95 latency" icon={<Timer />} value={formatMs(p95)} sub={`p50 ${formatMs(p50)}`} spark={series.map(point => point.p95)} sparkColor="var(--chart-5)" />
        <StatCard label="Tokens" icon={<Gauge />} value={formatCompact(tokens)} sub={`${formatNumber(overview?.total_tokens ?? tokens)} all time`} spark={series.map(point => point.tokens)} sparkColor="var(--chart-2)" />
        <StatCard label="Cost" icon={<Coins />} value={formatMoney(cost)} sub={costs ? `${formatPercent(costs.budget_used)} of monthly budget` : undefined} spark={series.map(point => point.cost)} sparkColor="var(--chart-3)" onClick={() => onSection('costs')} />
        <StatCard
          label="Needs attention"
          icon={<BellRing />}
          value={formatNumber(attention)}
          tone={firingAlerts ? 'danger' : attention ? 'warning' : 'neutral'}
          sub={`${firingAlerts} alerts · ${pendingApprovals} approvals · ${issues.length} issues`}
          onClick={() => onSection(firingAlerts ? 'alerts' : pendingApprovals ? 'approvals' : 'traces')}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Trace volume"
          description="Successful and failed traces per interval"
          actions={<ChartLegend items={[{ label: 'Success', color: 'var(--chart-1)', value: formatNumber(total - errors) }, { label: 'Failed', color: 'var(--danger)', value: formatNumber(errors) }]} />}
        >
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={series} barCategoryGap={2} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={40} />
                <YAxis {...axisProps} allowDecimals={false} width={44} />
                <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<ChartTooltip />} />
                <Bar dataKey="ok" name="Success" stackId="runs" fill="var(--chart-1)" radius={[0, 0, 0, 0]} maxBarSize={28} />
                <Bar dataKey="errors" name="Failed" stackId="runs" fill="var(--danger)" radius={[3, 3, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Latency" description="Per-interval trace duration" actions={<ChartLegend items={[{ label: 'p95', color: 'var(--chart-5)' }, { label: 'avg', color: 'var(--chart-2)' }]} />}>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
                <defs>
                  <linearGradient id="latency-fill" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="var(--chart-5)" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="var(--chart-5)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={40} />
                <YAxis {...axisProps} width={52} tickFormatter={value => formatMs(value)} />
                <Tooltip content={<ChartTooltip formatter={value => formatMs(value)} />} />
                <Area type="monotone" dataKey={point => point.runs ? point.p95 : null} name="p95" stroke="var(--chart-5)" strokeWidth={1.75} fill="url(#latency-fill)" dot={{ r: 2.5, fill: 'var(--chart-5)', strokeWidth: 0 }} connectNulls />
                <Area type="monotone" dataKey={point => point.runs ? point.avg : null} name="avg" stroke="var(--chart-2)" strokeWidth={1.5} fill="transparent" dot={{ r: 2, fill: 'var(--chart-2)', strokeWidth: 0 }} connectNulls />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          flush
          title="Issues"
          description="Failed traces grouped by error type and workflow"
          actions={issues.length > 0 && <Button size="sm" variant="ghost" onClick={() => onFilterTraces({ status: 'failed' })}>View failed traces<ArrowRight /></Button>}
        >
          {issues.length === 0
            ? <EmptyState icon={<Activity />} title="No failures" detail={`Every trace in the ${rangeTitle.toLowerCase()} succeeded.`} />
            : (
                <ul className="divide-y divide-line">
                  {issues.slice(0, 6).map(issue => (
                    <li key={issue.key}>
                      <button className="flex w-full items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-surface-2/60" onClick={() => onTrace(issue.traces[0].trace_id)}>
                        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-danger-soft text-danger-text"><AlertOctagon className="size-4" /></span>
                        <span className="min-w-0 flex-1">
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate font-mono text-[13px] font-medium text-fg">{issue.errorType}</span>
                            <span className="truncate text-[13px] text-fg-muted">in {issue.workflow}</span>
                          </span>
                          <span className="block truncate text-xs text-fg-subtle">{issue.message || 'No error message recorded'}</span>
                        </span>
                        <span className="hidden w-24 shrink-0 text-right sm:block">
                          <span className="tabular block text-[13px] text-fg">{issue.cost > 0 ? formatMoney(issue.cost) : '-'}</span>
                          <span className="block text-[11px] text-fg-subtle">wasted</span>
                        </span>
                        <span className="w-20 shrink-0 text-right">
                          <span className="tabular block text-[13px] font-semibold text-fg">{issue.count}</span>
                          <span className="block text-[11px] text-fg-subtle">{issue.count === 1 ? 'event' : 'events'}</span>
                        </span>
                        <span className="hidden w-20 shrink-0 text-right text-xs text-fg-subtle md:block">{formatRelative(issue.lastSeen)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
        </Card>

        <Card title="Spend by model" description="Estimated cost in the loaded data" actions={<Button size="sm" variant="ghost" onClick={() => onSection('models')}>Models<ArrowRight /></Button>}>
          {topModels.length === 0
            ? <EmptyState title="No model calls yet" />
            : (
                <ul className="flex flex-col gap-3.5">
                  {topModels.map(model => (
                    <li key={`${model.provider}-${model.model}`} className="flex flex-col gap-1.5">
                      <div className="flex items-baseline justify-between gap-3 text-[13px]">
                        <span className="min-w-0 truncate"><span className="font-medium text-fg">{model.model}</span> <span className="text-fg-subtle">{model.provider}</span></span>
                        <span className="tabular shrink-0 font-medium text-fg">{maxModelCost > 0 ? formatMoney(model.estimated_cost) : `${formatCompact(model.total_tokens)} tok`}</span>
                      </div>
                      <Meter value={maxModelCost > 0 ? numeric(model.estimated_cost) : numeric(model.total_tokens)} max={maxModelCost > 0 ? maxModelCost : maxModelTokens} />
                      <div className="flex gap-3 text-[11.5px] text-fg-subtle">
                        <span>{formatNumber(model.calls)} calls</span>
                        <span>{formatCompact(model.total_tokens)} tokens</span>
                        <span>p95 {formatMs(model.p95_latency_ms)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" flush title="Recent traces" actions={<Button size="sm" variant="ghost" onClick={() => onFilterTraces({})}>All traces<ArrowRight /></Button>}>
          <DataTable
            rows={traces.slice(0, 8)}
            minWidth={620}
            onRow={row => onTrace(row.trace_id)}
            rowKey={row => row.trace_id}
            empty={<EmptyState title="No traces yet" />}
            columns={[
              {
                label: 'Trace',
                render: row => (
                  <span className="flex min-w-0 items-center gap-2.5">
                    <StatusDot status={row.status} />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-fg">{row.workflow_name ?? row.name}</span>
                      {row.error_message && <span className="block max-w-md truncate text-xs text-danger-text">{row.error_message}</span>}
                    </span>
                  </span>
                ),
              },
              { label: 'Tokens', align: 'right', render: row => numeric(row.total_tokens) ? formatCompact(row.total_tokens) : <span className="text-fg-subtle">-</span> },
              { label: 'Duration', align: 'right', render: row => formatMs(traceDuration(row)) },
              { label: 'Cost', align: 'right', render: row => numeric(row.estimated_cost) ? formatMoney(row.estimated_cost) : <span className="text-fg-subtle">-</span> },
              { label: 'Started', align: 'right', render: row => <span className="text-fg-muted" title={row.started_at}>{formatRelative(row.started_at)}</span> },
            ]}
          />
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          <Card flush title="Providers" description={idleProviders ? `${idleProviders} more not configured` : undefined} actions={<Button size="sm" variant="ghost" onClick={() => onSection('models')}>Details<ArrowRight /></Button>}>
            {activeProviders.length === 0
              ? <EmptyState title="No provider traffic yet" />
              : (
                  <ul className="divide-y divide-line">
                    {activeProviders.map(provider => (
                      <li key={provider.provider} className="flex items-center gap-3 px-4 py-2.5">
                        <StatusDot status={provider.status} pulse={provider.status === 'degraded'} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-fg">{provider.display_name}</span>
                          <span className="block truncate text-xs text-fg-subtle">{formatNumber(provider.calls)} calls · p95 {formatMs(provider.p95_latency_ms)}{provider.error_rate ? ` · ${formatPercent(provider.error_rate)} errors` : ''}</span>
                        </span>
                        <StatusBadge status={provider.status} />
                      </li>
                    ))}
                  </ul>
                )}
          </Card>
          <Card flush title="Live activity" icon={<Radio />} description="Events streamed from the server">
            {liveEvents.length === 0
              ? <div className="px-4 py-6 text-center text-[13px] text-fg-subtle">Waiting for new trace events...</div>
              : (
                  <ul className="max-h-56 divide-y divide-line overflow-y-auto">
                    {liveEvents.slice(0, 12).map((event, index) => (
                      <li key={`${event.at}-${index}`} className="flex items-center gap-2.5 px-4 py-2 text-[13px]">
                        <StatusDot status={event.type.includes('fail') || event.type.includes('error') ? 'failed' : event.type.includes('finish') || event.type.includes('complete') ? 'succeeded' : 'running'} />
                        <button className="min-w-0 flex-1 truncate text-left text-fg hover:text-accent-text" disabled={!event.trace_id} onClick={() => event.trace_id && onTrace(event.trace_id)}>{event.type}</button>
                        <Badge outline>{formatRelative(event.at)}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
          </Card>
        </div>
      </div>
    </>
  )
}
