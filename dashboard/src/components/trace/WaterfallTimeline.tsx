import { Clock } from 'lucide-react'
import type { SpanRecord } from '../../types'
import { formatMs, numeric } from '../../utils/format'
import { EmptyState } from '../common/Cards'

export function WaterfallTimeline({ spans, onSelect }: { spans: SpanRecord[]; onSelect: (span: SpanRecord) => void }) {
  if (spans.length === 0)
    return <EmptyState icon={<Clock className="size-5" />} title="No timeline" detail="No span timing data is available for this trace." />
  const starts = spans.map(span => Date.parse(span.started_at)).filter(Number.isFinite)
  const min = Math.min(...starts)
  const max = Math.max(...spans.map(span => Date.parse(span.ended_at ?? span.started_at)).filter(Number.isFinite), min + 1)
  const total = Math.max(max - min, 1)
  return (
    <div className="vision-scroll flex max-h-[520px] flex-col gap-2 overflow-auto pr-1">
      {spans.map(span => {
        const start = Date.parse(span.started_at)
        const end = Date.parse(span.ended_at ?? span.started_at)
        const left = Number.isFinite(start) ? ((start - min) / total) * 100 : 0
        const width = Number.isFinite(end) ? Math.max(((end - start) / total) * 100, 2) : 3
        const color = span.status === 'failed' ? 'bg-rose-400' : span.status === 'running' ? 'bg-sky-300' : span.event_type.includes('replay') ? 'bg-purple-300' : numeric(span.estimated_cost) > 0 ? 'bg-amber-300' : 'bg-emerald-300'
        return (
          <button key={span.span_id} className="grid grid-cols-[190px_1fr_78px] items-center gap-3 rounded-2xl border border-white/10 bg-slate-950/22 px-3 py-2 text-left transition hover:border-sky-200/28 hover:bg-sky-300/10" onClick={() => onSelect(span)}>
            <div className="min-w-0">
              <div className="truncate text-sm/6 font-semibold text-white">{span.event_type}</div>
              <div className="truncate text-xs/5 text-white/52">{span.agent_name ?? 'workflow'}</div>
            </div>
            <div className="relative h-3 rounded-full bg-white/10">
              <div className={`absolute top-0 h-3 rounded-full ${color}`} style={{ left: `${left}%`, width: `${width}%` }} />
            </div>
            <div className="text-right text-xs/5 font-semibold text-white/70">{formatMs(span.duration_ms)}</div>
          </button>
        )
      })}
    </div>
  )
}
