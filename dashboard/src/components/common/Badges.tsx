import { CheckCircle2, Clock, Copy, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import type { TraceSummary } from '../../types'
import { shortId } from '../../utils/format'

export function Badge({ children, tone = 'neutral', outline = false }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'danger' | 'info' | 'purple' | 'unknown'; outline?: boolean }) {
  const palette = {
    neutral: outline ? 'border border-white/20 text-white/78' : 'bg-white/12 text-white/80',
    good: outline ? 'border border-emerald-200/36 text-emerald-100' : 'bg-emerald-400/22 text-emerald-50',
    warn: outline ? 'border border-amber-200/36 text-amber-100' : 'bg-amber-400/22 text-amber-50',
    danger: outline ? 'border border-rose-200/38 text-rose-100' : 'bg-rose-400/22 text-rose-50',
    info: outline ? 'border border-sky-200/38 text-sky-100' : 'bg-sky-400/22 text-sky-50',
    purple: outline ? 'border border-purple-200/38 text-purple-100' : 'bg-purple-400/22 text-purple-50',
    unknown: 'border border-white/22 bg-transparent text-white/62',
  }[tone]
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs/5 font-semibold ${palette}`}>{children}</span>
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status || 'unknown'
  const tone = normalized === 'succeeded' || normalized === 'approved' || normalized === 'healthy'
    ? 'good'
    : normalized === 'failed' || normalized === 'rejected' || normalized === 'degraded'
      ? 'danger'
      : normalized === 'running'
        ? 'info'
        : normalized.includes('replay')
          ? 'purple'
          : normalized === 'planned' || normalized === 'unknown' || normalized === 'unavailable'
            ? 'unknown'
            : 'warn'
  const icon = tone === 'good' ? <CheckCircle2 className="size-3.5" /> : tone === 'danger' ? <XCircle className="size-3.5" /> : <Clock className="size-3.5" />
  return <Badge tone={tone} outline={tone === 'unknown'}>{icon}{normalized}</Badge>
}

export function StatusDot({ status }: { status: string }) {
  const color = status === 'succeeded' || status === 'healthy' || status === 'ok'
    ? 'bg-emerald-300 shadow-[0_0_12px_rgb(110_231_183/0.45)]'
    : status === 'failed'
      ? 'bg-rose-300 shadow-[0_0_12px_rgb(253_164_175/0.45)]'
      : status === 'running' || status === 'checking'
        ? 'bg-sky-300 shadow-[0_0_12px_rgb(125_211_252/0.45)]'
        : 'bg-amber-300 shadow-[0_0_12px_rgb(252_211_77/0.45)]'
  return <span className={`mt-1 inline-block size-2.5 shrink-0 rounded-full ${color}`} />
}

export function EnvironmentBadge({ trace }: { trace: TraceSummary }) {
  return trace.is_demo
    ? <Badge tone="info" outline>demo</Badge>
    : <Badge tone="good">{trace.environment ?? 'real'}</Badge>
}

export function CostStatusBadge({ status }: { status?: string | null }) {
  const normalized = status || 'unknown'
  const tone = normalized === 'exact' || normalized === 'local/free'
    ? 'good'
    : normalized === 'estimated'
      ? 'warn'
      : 'unknown'
  return <Badge tone={tone} outline={tone === 'unknown'}>{normalized}</Badge>
}

export function EventTypeBadge({ type }: { type: string }) {
  const tone = type.includes('failed') || type.includes('error') ? 'danger' : type.includes('replay') ? 'purple' : type.includes('approval') ? 'warn' : 'neutral'
  return <Badge tone={tone}>{type}</Badge>
}

export function ProviderBadge({ provider, model }: { provider?: string | null; model?: string | null }) {
  return (
    <span className="inline-flex max-w-44 flex-col">
      <span className="truncate text-sm/5 font-semibold text-white" title={provider ?? '-'}>{provider ?? '-'}</span>
      {model && <span className="truncate text-xs/5 text-white/52" title={model}>{model}</span>}
    </span>
  )
}

export function CopyableId({ value, label }: { value: string | undefined | null; label?: string }) {
  const text = value ?? ''
  return (
    <button
      className="inline-flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-xs/5 text-white/68 hover:bg-white/10 hover:text-white"
      title={text}
      onClick={event => {
        event.stopPropagation()
        if (text)
          void navigator.clipboard.writeText(text)
      }}
    >
      <span>{label ?? shortId(text)}</span>
      <Copy className="size-3" />
    </button>
  )
}
