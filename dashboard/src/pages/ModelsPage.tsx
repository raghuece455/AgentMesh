import { Cpu } from 'lucide-react'
import { useState } from 'react'
import { Badge, CostStatusBadge, StatusBadge, StatusDot } from '../components/ui/Badge'
import { Card, EmptyState, Meter, PageHeader } from '../components/ui/Card'
import { DataTable } from '../components/ui/DataTable'
import { cn } from '../lib/utils'
import type { ModelCallRecord, ModelUsage, ProviderHealth } from '../types'
import { formatCompact, formatMoney, formatMs, formatNumber, formatPercent, formatRelative, numeric } from '../utils/format'

export function ModelsPage({ providers, models, modelCalls, onTrace }: { providers: ProviderHealth[]; models: ModelUsage[]; modelCalls: ModelCallRecord[]; onTrace: (traceId: string) => void }) {
  const [showIdle, setShowIdle] = useState(false)
  const active = providers.filter(provider => provider.status !== 'not_configured' && provider.status !== 'planned')
  const idle = providers.filter(provider => !active.includes(provider))
  const maxTokens = Math.max(...models.map(model => numeric(model.total_tokens)), 0)

  return (
    <>
      <PageHeader title="Models" description="Provider health, latency, and usage for every model your agents call." />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-4">
        {active.map(provider => (
          <div key={provider.provider} className={cn('flex flex-col gap-3 rounded-xl border bg-surface p-4 shadow-card', provider.status === 'degraded' ? 'border-danger/40' : 'border-line')}>
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2.5">
                <StatusDot status={provider.status} pulse={provider.status === 'degraded'} />
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] font-semibold text-fg">{provider.display_name}</div>
                  <div className="font-mono text-[11px] text-fg-subtle">{provider.provider}</div>
                </div>
              </div>
              <StatusBadge status={provider.status} />
            </div>
            <dl className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Calls" value={formatNumber(provider.calls)} />
              <Metric label="p95" value={formatMs(provider.p95_latency_ms)} />
              <Metric label="Errors" value={formatPercent(provider.error_rate)} danger={provider.error_rate > 0} />
              <Metric label="Tokens" value={formatCompact(provider.tokens)} />
              <Metric label="Cost" value={formatMoney(provider.cost_usd)} />
              <Metric label="Rate limits" value={formatNumber(provider.rate_limit_events)} danger={provider.rate_limit_events > 0} />
            </dl>
            {provider.last_error && <div className="truncate rounded-md bg-danger-soft px-2 py-1 text-xs text-danger-text" title={provider.last_error}>{provider.last_error}</div>}
            <div className="text-[11px] text-fg-subtle">Last call {provider.updated_at ? formatRelative(provider.updated_at) : 'never'}</div>
          </div>
        ))}
        {active.length === 0 && <Card className="md:col-span-2 2xl:col-span-4"><EmptyState icon={<Cpu />} title="No provider traffic yet" /></Card>}
      </div>
      {idle.length > 0 && (
        <div className="-mt-2 flex flex-wrap items-center gap-1.5 text-xs text-fg-subtle">
          <button className="hover:text-fg" onClick={() => setShowIdle(value => !value)}>{idle.length} providers not configured{showIdle ? ':' : ''}</button>
          {showIdle && idle.map(provider => <Badge key={provider.provider} outline>{provider.display_name}</Badge>)}
        </div>
      )}

      <Card flush title="Model usage">
        <DataTable
          rows={models}
          minWidth={900}
          initialSort={{ column: 2 }}
          empty={<EmptyState title="No model calls yet" />}
          columns={[
            { label: 'Model', sortValue: row => row.model, render: row => <span className="flex flex-col"><span className="font-medium text-fg">{row.model}</span><span className="text-xs text-fg-subtle">{row.provider}{row.endpoint_alias ? ` · ${row.endpoint_alias}` : ''}</span></span> },
            { label: 'Calls', align: 'right', sortValue: row => row.calls, render: row => formatNumber(row.calls) },
            {
              label: 'Tokens',
              width: '200px',
              sortValue: row => numeric(row.total_tokens),
              render: row => (
                <span className="flex items-center gap-2">
                  <Meter value={numeric(row.total_tokens)} max={maxTokens} tone="info" />
                  <span className="tabular w-12 shrink-0 text-right">{formatCompact(row.total_tokens)}</span>
                </span>
              ),
            },
            { label: 'Cost', align: 'right', sortValue: row => numeric(row.estimated_cost), render: row => numeric(row.estimated_cost) ? formatMoney(row.estimated_cost) : <span className="text-fg-subtle">{row.provider === 'ollama' || row.provider === 'mock' ? 'free' : '-'}</span> },
            { label: 'Avg', align: 'right', sortValue: row => row.avg_latency_ms, render: row => formatMs(row.avg_latency_ms) },
            { label: 'p95', align: 'right', sortValue: row => row.p95_latency_ms, render: row => formatMs(row.p95_latency_ms) },
            { label: 'Success', align: 'right', sortValue: row => row.success_rate, render: row => <span className={row.success_rate < 1 ? 'text-warning-text' : 'text-fg'}>{formatPercent(row.success_rate)}</span> },
            { label: 'Context', align: 'right', sortValue: row => numeric(row.context_window), render: row => row.context_window ? formatCompact(row.context_window) : <span className="text-fg-subtle">-</span> },
          ]}
        />
      </Card>

      <Card flush title="Recent model calls" description="Click a call to open its trace">
        <DataTable
          rows={modelCalls.slice(0, 100)}
          rowKey={row => row.model_call_id}
          minWidth={900}
          onRow={row => onTrace(row.trace_id)}
          empty={<EmptyState title="No model calls yet" />}
          columns={[
            { label: 'Model', sortValue: row => row.model ?? '', render: row => <span className="flex items-center gap-2"><StatusDot status={row.status} /><span className="font-medium text-fg">{row.model ?? '-'}</span></span> },
            { label: 'Agent', sortValue: row => row.agent_name ?? '', render: row => <span className="text-fg-muted">{row.agent_name ?? '-'}</span> },
            { label: 'Input', align: 'right', sortValue: row => row.prompt_tokens, render: row => formatCompact(row.prompt_tokens) },
            { label: 'Output', align: 'right', sortValue: row => row.completion_tokens, render: row => formatCompact(row.completion_tokens) },
            { label: 'Cost', align: 'right', sortValue: row => row.estimated_cost, render: row => <span className="inline-flex items-center gap-1.5">{numeric(row.estimated_cost) ? formatMoney(row.estimated_cost) : '-'}{row.cost_status !== 'estimated' && <CostStatusBadge status={row.cost_status} />}</span> },
            { label: 'Latency', align: 'right', sortValue: row => numeric(row.duration_ms), render: row => formatMs(row.duration_ms) },
            { label: 'When', align: 'right', sortValue: row => Date.parse(row.started_at), render: row => <span className="text-fg-muted">{formatRelative(row.started_at)}</span> },
          ]}
        />
      </Card>
    </>
  )
}

function Metric({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-fg-subtle">{label}</dt>
      <dd className={cn('tabular truncate text-[13px] font-medium', danger ? 'text-danger-text' : 'text-fg')}>{value}</dd>
    </div>
  )
}
