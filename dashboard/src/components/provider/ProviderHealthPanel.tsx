import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { ProviderHealth } from '../../types'
import { formatMoney, formatMs, formatPercent, formatTime } from '../../utils/format'
import { Badge, StatusBadge } from '../common/Badges'
import { EmptyState } from '../common/Cards'

export function ProviderHealthPanel({ providers }: { providers: ProviderHealth[] }) {
  const [plannedOpen, setPlannedOpen] = useState(false)
  const configured = providers.filter(provider => provider.status !== 'planned')
  const planned = providers.filter(provider => provider.status === 'planned')
  return (
    <div className="flex flex-col gap-3">
      {configured.length === 0 && <EmptyState title="No configured providers" detail="Mock, Ollama, or OpenAI-compatible calls will appear here once workflows run." />}
      {configured.map(provider => (
        <div key={provider.provider} className={`rounded-2xl border p-3 ${provider.status === 'degraded' ? 'border-rose-200/28 bg-rose-950/22' : provider.status === 'healthy' ? 'border-emerald-200/22 bg-emerald-950/14' : 'border-white/12 bg-slate-950/26'}`}>
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-sm/6 font-semibold text-white">{provider.display_name}</div>
              <div className="text-xs/5 text-white/56">{provider.provider}</div>
            </div>
            <StatusBadge status={provider.status} />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs/5 text-white/72">
            <span>Calls {provider.calls}</span>
            <span>Cost {formatMoney(provider.cost_usd)}</span>
            <span>Latency {formatMs(provider.avg_latency_ms)}</span>
            <span>P95 {formatMs(provider.p95_latency_ms)}</span>
            <span>Error {formatPercent(provider.error_rate)}</span>
            <span>Rate limits {provider.rate_limit_events}</span>
            <span className="col-span-2">Last seen {provider.updated_at ? formatTime(provider.updated_at) : 'not observed'}</span>
          </div>
          {provider.last_error && <div className="mt-2 rounded-xl bg-rose-400/14 px-2 py-1 text-xs/5 text-rose-100">{provider.last_error}</div>}
        </div>
      ))}
      {planned.length > 0 && (
        <div className="rounded-2xl border border-white/12 bg-slate-950/18">
          <button className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm/6 font-semibold text-white" onClick={() => setPlannedOpen(value => !value)}>
            <span>Planned integrations</span>
            <span className="inline-flex items-center gap-2 text-xs text-white/54">{planned.length}<ChevronRight className={`size-4 transition ${plannedOpen ? 'rotate-90' : ''}`} /></span>
          </button>
          {plannedOpen && (
            <div className="flex flex-wrap gap-2 border-t border-white/10 p-3">
              {planned.map(provider => <Badge key={provider.provider} tone="unknown" outline>{provider.display_name}</Badge>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
