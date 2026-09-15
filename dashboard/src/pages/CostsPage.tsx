import { ArrowUpRight, CalendarDays, Coins, PiggyBank, TrendingUp, Wallet, XCircle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CostStatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, Meter, PageHeader } from '../components/ui/Card'
import { axisProps, CHART_COLORS, ChartLegend, ChartTooltip, gridProps } from '../components/ui/Chart'
import { DataTable } from '../components/ui/DataTable'
import { StatCard } from '../components/ui/Stat'
import { Tabs } from '../components/ui/Tabs'
import type { CostCenterSummary, JsonRecord, TraceSummary } from '../types'
import { formatCompact, formatMoney, formatMs, formatNumber, formatPercent, numeric, stringValue } from '../utils/format'
import { buildSeries, TIME_RANGES, type TimeRange } from '../utils/traces'

type Breakdown = 'workflow' | 'model' | 'agent' | 'provider'

export function CostsPage({
  summary,
  traces,
  range,
  byWorkflow,
  byAgent,
  byModel,
  byProvider,
  byFailedRun,
  onTrace,
}: {
  summary: CostCenterSummary | null
  traces: TraceSummary[]
  range: TimeRange
  byWorkflow: JsonRecord[]
  byAgent: JsonRecord[]
  byModel: JsonRecord[]
  byProvider: JsonRecord[]
  byFailedRun: JsonRecord[]
  onTrace: (traceId: string) => void
}) {
  const [breakdown, setBreakdown] = useState<Breakdown>('model')
  const series = useMemo(() => buildSeries(traces, range), [traces, range])
  const rangeCost = traces.reduce((sum, trace) => sum + numeric(trace.estimated_cost), 0)
  const rangeTitle = TIME_RANGES.find(item => item.value === range)?.title ?? ''
  const tokenData = Object.entries(summary?.token_split ?? {}).map(([name, value]) => ({ name: name.replaceAll('_', ' '), value: numeric(value) })).filter(item => item.value > 0)
  const tokenTotal = tokenData.reduce((sum, item) => sum + item.value, 0)
  const rows = { workflow: byWorkflow, model: byModel, agent: byAgent, provider: byProvider }[breakdown]
  const maxCost = Math.max(...rows.map(row => numeric(row.estimated_cost)), 0)
  const totalCost = rows.reduce((sum, row) => sum + numeric(row.estimated_cost), 0)
  const budgetUsed = numeric(summary?.budget_used)

  return (
    <>
      <PageHeader title="Costs" description="Estimated spend from token usage and model pricing, including what failed runs wasted." />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
        <StatCard label="Today" icon={<Coins />} value={formatMoney(summary?.total_spend_today)} spark={series.map(point => point.cost)} sparkColor="var(--chart-3)" />
        <StatCard label="This week" icon={<CalendarDays />} value={formatMoney(summary?.total_spend_week)} />
        <StatCard label="This month" icon={<Wallet />} value={formatMoney(summary?.total_spend_month)} sub={`${formatPercent(budgetUsed)} of budget`} />
        <StatCard label="Projected month" icon={<TrendingUp />} value={formatMoney(summary?.projected_monthly_spend)} tone={budgetUsed > 0.9 ? 'danger' : budgetUsed > 0.7 ? 'warning' : 'neutral'} sub={`${formatMoney(summary?.budget_remaining)} budget left`} />
        <StatCard label="Failed-run waste" icon={<XCircle />} value={formatMoney(summary?.cost_wasted_on_failed_runs)} tone={numeric(summary?.cost_wasted_on_failed_runs) > 0 ? 'danger' : 'neutral'} sub={`${formatMoney(summary?.cost_per_successful_run)} per successful run`} />
        <StatCard label="Cache savings" icon={<PiggyBank />} value={formatMoney(summary?.cache_savings)} sub="From cached input tokens" />
      </div>

      <Card title="Monthly budget" description={`${formatMoney(summary?.total_spend_month)} spent of ${formatMoney(numeric(summary?.total_spend_month) + numeric(summary?.budget_remaining))}`} actions={<span className="tabular text-[13px] font-semibold text-fg">{formatPercent(budgetUsed)}</span>}>
        <Meter value={budgetUsed} max={1} tone={budgetUsed > 0.9 ? 'danger' : budgetUsed > 0.7 ? 'warning' : 'accent'} className="h-2" />
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Spend over time" description={`${formatMoney(rangeCost)} in the ${rangeTitle.toLowerCase()}`}>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={series} barCategoryGap={2} margin={{ top: 4, right: 4, bottom: 0, left: -6 }}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={40} />
                <YAxis {...axisProps} width={56} tickFormatter={value => formatMoney(value)} />
                <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<ChartTooltip formatter={value => formatMoney(value)} />} />
                <Bar dataKey="cost" name="Cost" fill="var(--chart-3)" radius={[3, 3, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Token mix" description={`${formatCompact(tokenTotal)} tokens`}>
          {tokenData.length === 0
            ? <EmptyState title="No token usage yet" />
            : (
                <div className="flex flex-col items-center gap-3">
                  <div className="h-44 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={tokenData} dataKey="value" nameKey="name" innerRadius={52} outerRadius={78} paddingAngle={2} stroke="var(--surface)" strokeWidth={2}>
                          {tokenData.map((_, index) => <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}
                        </Pie>
                        <Tooltip content={<ChartTooltip formatter={value => formatNumber(value)} />} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <ChartLegend className="justify-center" items={tokenData.map((item, index) => ({ label: item.name, color: CHART_COLORS[index % CHART_COLORS.length], value: tokenTotal ? `${Math.round((item.value / tokenTotal) * 100)}%` : undefined }))} />
                </div>
              )}
        </Card>
      </div>

      <Card flush>
        <div className="flex items-center justify-between gap-3 px-2">
          <Tabs
            className="border-b-0"
            value={breakdown}
            onChange={setBreakdown}
            items={[
              { value: 'model', label: 'By model', count: byModel.length },
              { value: 'workflow', label: 'By workflow', count: byWorkflow.length },
              { value: 'agent', label: 'By agent', count: byAgent.length },
              { value: 'provider', label: 'By provider', count: byProvider.length },
            ]}
          />
          <div className="hidden flex-wrap items-center gap-1.5 pr-2 md:flex">
            {Object.entries(summary?.cost_status_counts ?? {}).map(([status, count]) => (
              <span key={status} className="inline-flex items-center gap-1"><CostStatusBadge status={status} /><span className="tabular text-xs text-fg-muted">{count}</span></span>
            ))}
          </div>
        </div>
        <div className="border-t border-line">
          <DataTable
            rows={rows}
            minWidth={680}
            initialSort={{ column: 3 }}
            empty={<EmptyState title="No spend recorded" />}
            columns={[
              { label: 'Name', sortValue: row => rowName(row), render: row => <span className="font-medium text-fg">{rowName(row)}</span> },
              { label: 'Calls', align: 'right', sortValue: row => numeric(row.calls ?? row.runs), render: row => formatNumber(row.calls ?? row.runs) },
              { label: 'Tokens', align: 'right', sortValue: row => numeric(row.total_tokens), render: row => formatCompact(row.total_tokens) },
              { label: 'Cost', align: 'right', sortValue: row => numeric(row.estimated_cost), render: row => <span className="font-medium">{formatMoney(row.estimated_cost)}</span> },
              {
                label: 'Share',
                width: '200px',
                sortValue: row => numeric(row.estimated_cost),
                render: row => (
                  <span className="flex items-center gap-2">
                    <Meter value={numeric(row.estimated_cost)} max={maxCost} />
                    <span className="tabular w-10 shrink-0 text-right text-xs text-fg-muted">{totalCost ? `${Math.round((numeric(row.estimated_cost) / totalCost) * 100)}%` : '-'}</span>
                  </span>
                ),
              },
              { label: 'Avg latency', align: 'right', sortValue: row => numeric(row.avg_latency_ms), render: row => row.avg_latency_ms === undefined ? <span className="text-fg-subtle">-</span> : formatMs(row.avg_latency_ms) },
            ]}
          />
        </div>
      </Card>

      <Card flush title="Spend on failed runs" description="Tokens paid for by runs that did not succeed">
        <DataTable
          rows={byFailedRun}
          minWidth={620}
          onRow={row => row.trace_id && onTrace(String(row.trace_id))}
          initialSort={{ column: 2 }}
          empty={<EmptyState title="No failed-run spend" detail="Failed runs have not consumed any priced tokens." />}
          columns={[
            { label: 'Trace', sortValue: row => rowName(row), render: row => <span className="flex flex-col"><span className="font-medium text-fg">{rowName(row)}</span>{row.error_type ? <span className="font-mono text-xs text-danger-text">{stringValue(row.error_type)}</span> : null}</span> },
            { label: 'Tokens', align: 'right', sortValue: row => numeric(row.total_tokens), render: row => formatCompact(row.total_tokens) },
            { label: 'Wasted', align: 'right', sortValue: row => numeric(row.estimated_cost), render: row => <span className="font-medium text-danger-text">{formatMoney(row.estimated_cost)}</span> },
            { label: '', align: 'right', render: row => row.trace_id ? <Button size="xs" variant="ghost">Open<ArrowUpRight /></Button> : null },
          ]}
        />
      </Card>
    </>
  )
}

function rowName(row: JsonRecord): string {
  return stringValue(row.name ?? row.workflow_name ?? row.model ?? row.agent_name ?? row.provider ?? row.trace_id) || '-'
}
