import { AlertTriangle, BarChart3, CheckCircle2, CircleDollarSign, Gauge, ListTree, Route, ShieldCheck, UserCheck, WalletCards, Wifi, Wrench, Zap } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CostCenterSummary, ModelCallRecord, ModelUsage, OverviewData, ProviderHealth, TimeseriesData, ToolCallRecord, TraceSummary } from '../types'
import type { LiveEventRecord } from '../appTypes'
import { formatMoney, formatMs, formatNumber, formatPercent, formatTime } from '../utils/format'
import { Badge, CostStatusBadge, StatusDot } from '../components/common/Badges'
import { ChartFrame, EmptyState, MetricCard, Panel } from '../components/common/Cards'
import { TracesTable } from '../components/trace/TracesTable'
import { FailureInbox } from '../components/trace/FailureInbox'
import { ProviderHealthPanel } from '../components/provider/ProviderHealthPanel'

const chartColors = ['#38bdf8', '#2f8cff', '#5eead4', '#a3e635', '#fbbf24', '#fb7185', '#c084fc']

export function OverviewPage({
  overview,
  timeseries,
  traces,
  providers,
  models,
  modelCalls,
  toolCalls,
  costs,
  liveEvents,
  onTraceSelect,
  onExport,
  onReplay,
  onCompare,
}: {
  overview: OverviewData | null
  timeseries: TimeseriesData
  traces: TraceSummary[]
  providers: ProviderHealth[]
  models: ModelUsage[]
  modelCalls: ModelCallRecord[]
  toolCalls: ToolCallRecord[]
  costs: CostCenterSummary | null
  liveEvents: LiveEventRecord[]
  onTraceSelect: (traceId: string) => void
  onExport: (traceId: string) => void
  onReplay: (traceId: string) => void
  onCompare: (traceId: string) => void
}) {
  const points = timeseries.points
  const healthyProviders = providers.filter(provider => provider.status === 'healthy').length
  const failureCount = traces.filter(trace => trace.status === 'failed').length
  const recentTraces = overview?.recent_traces?.length ? overview.recent_traces : traces
  const failures = overview?.recent_failures?.length ? overview.recent_failures : traces.filter(trace => trace.status === 'failed').slice(0, 8)
  return (
    <div className="flex flex-col gap-4">
      <Panel title="Trace Launchpad" icon={<Route className="size-4" />}>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4 xl:grid-cols-8">
          <MetricCard compact icon={<Route className="size-4" />} label="Runs" value={overview?.runs_today ?? traces.length} />
          <MetricCard compact icon={<CheckCircle2 className="size-4" />} label="Success rate" value={formatPercent(overview?.success_rate)} tone="good" />
          <MetricCard compact icon={<AlertTriangle className="size-4" />} label="Failures" value={failureCount} tone={failureCount ? 'danger' : 'good'} />
          <MetricCard compact icon={<BarChart3 className="size-4" />} label="Avg latency" value={formatMs(overview?.average_latency_ms)} />
          <MetricCard compact icon={<CircleDollarSign className="size-4" />} label="Total cost" value={formatMoney(overview?.total_cost)} tone="money" />
          <MetricCard compact icon={<UserCheck className="size-4" />} label="Approvals" value={overview?.pending_approvals ?? 0} tone="warn" />
          <MetricCard compact icon={<ShieldCheck className="size-4" />} label="Provider health" value={`${healthyProviders} healthy / ${providers.length || 0} configured`} tone={healthyProviders === providers.length ? 'good' : 'warn'} />
          <MetricCard compact icon={<WalletCards className="size-4" />} label="Budget used" value={formatPercent(overview?.budget_used)} tone="money" />
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1.55fr)_minmax(380px,0.75fr)]">
        <Panel title="Recent Traces" icon={<ListTree className="size-4" />} actions={<Badge tone="info" outline>trace-first</Badge>}>
          <TracesTable traces={recentTraces} modelCalls={modelCalls} toolCalls={toolCalls} onOpen={onTraceSelect} onReplay={onReplay} onExport={onExport} onCompare={onCompare} />
        </Panel>
        <div className="flex flex-col gap-4">
          <Panel title="Failure Inbox" icon={<AlertTriangle className="size-4" />}>
            <FailureInbox traces={failures} modelCalls={modelCalls} toolCalls={toolCalls} onOpen={onTraceSelect} onReplay={onReplay} onExport={onExport} />
          </Panel>
          <Panel title="Provider Health" icon={<ShieldCheck className="size-4" />}>
            <ProviderHealthPanel providers={providers} />
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Panel title="Cost and Token Trend" icon={<BarChart3 className="size-4" />} className="xl:col-span-8">
          <ChartFrame dense>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points}>
                <CartesianGrid stroke="rgb(255 255 255 / 12%)" />
                <XAxis dataKey="bucket" tick={{ fill: 'rgb(255 255 255 / 64%)', fontSize: 11 }} />
                <YAxis tick={{ fill: 'rgb(255 255 255 / 64%)', fontSize: 11 }} />
                <Tooltip contentStyle={{ background: '#111827', border: '1px solid rgb(255 255 255 / 18%)', color: '#fff' }} />
                <Area type="monotone" dataKey="cost" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.18} />
                <Area type="monotone" dataKey="tokens" stroke="#5eead4" fill="#5eead4" fillOpacity={0.1} />
                <Area type="monotone" dataKey="failures" stroke="#fb7185" fill="#fb7185" fillOpacity={0.12} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartFrame>
        </Panel>
        <Panel title="Live Event Stream" icon={<Wifi className="size-4" />} className="xl:col-span-4">
          <LiveEventStream events={liveEvents} />
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel title="Model Usage Split" icon={<Zap className="size-4" />}>
          <ChartFrame dense>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={models} dataKey="total_tokens" nameKey="model" innerRadius={48} outerRadius={78} paddingAngle={3}>
                  {models.map((_, index) => <Cell key={index} fill={chartColors[index % chartColors.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: '#111827', border: '1px solid rgb(255 255 255 / 18%)', color: '#fff' }} />
              </PieChart>
            </ResponsiveContainer>
          </ChartFrame>
        </Panel>
        <Panel title="Cost Status Legend" icon={<Gauge className="size-4" />}>
          <div className="flex flex-col gap-2">
            {Object.entries(costs?.cost_status_counts ?? {}).map(([status, count]) => (
              <div key={status} className="flex items-center justify-between rounded-2xl border border-white/10 bg-slate-950/20 px-3 py-2">
                <CostStatusBadge status={status} />
                <span className="text-sm/6 font-semibold text-white">{count}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Tool Activity" icon={<Wrench className="size-4" />}>
          <div className="flex flex-col gap-2">
            {toolCalls.slice(0, 7).map(call => (
              <div key={call.tool_call_id} className="rounded-2xl border border-white/10 bg-slate-950/20 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="truncate text-sm/6 font-semibold text-white">{call.tool_name}</div>
                  <Badge>{formatMs(call.duration_ms)}</Badge>
                </div>
                <div className="truncate text-xs/5 text-white/52">{call.agent_name ?? 'unknown'} / {call.status} / {call.tool_type}</div>
              </div>
            ))}
            {toolCalls.length === 0 && <EmptyState title="No tool calls" />}
          </div>
        </Panel>
      </div>
    </div>
  )
}

function LiveEventStream({ events }: { events: LiveEventRecord[] }) {
  if (events.length === 0)
    return <EmptyState icon={<Wifi className="size-5" />} title="Waiting for live workflow events" />
  return (
    <div className="vision-scroll max-h-64 overflow-auto pr-1">
      {events.map((event, index) => (
        <div key={`${event.at}-${index}`} className="mb-2 grid grid-cols-[auto_1fr] gap-2 rounded-2xl border border-white/10 bg-slate-950/22 p-2.5">
          <StatusDot status={event.type.includes('failed') || event.type.includes('error') ? 'failed' : event.type.includes('completed') ? 'succeeded' : 'running'} />
          <div className="min-w-0">
            <div className="truncate text-sm/5 font-semibold text-white">{event.type}</div>
            <div className="truncate text-xs/5 text-white/50">{formatTime(event.at)} {event.trace_id ? `/ ${event.trace_id}` : ''}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
