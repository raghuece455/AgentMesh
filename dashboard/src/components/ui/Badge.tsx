import { CheckCircle2, CircleDashed, Clock, Loader2, PauseCircle, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export type Tone = 'neutral' | 'success' | 'danger' | 'warning' | 'info' | 'accent' | 'violet'

const soft: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-fg-muted border-line',
  success: 'bg-success-soft text-success-text border-transparent',
  danger: 'bg-danger-soft text-danger-text border-transparent',
  warning: 'bg-warning-soft text-warning-text border-transparent',
  info: 'bg-info-soft text-info-text border-transparent',
  accent: 'bg-accent-soft text-accent-text border-transparent',
  violet: 'bg-violet-soft text-violet-text border-transparent',
}

const dots: Record<Tone, string> = {
  neutral: 'bg-fg-subtle',
  success: 'bg-success',
  danger: 'bg-danger',
  warning: 'bg-warning',
  info: 'bg-info',
  accent: 'bg-accent',
  violet: 'bg-violet',
}

export function Badge({ children, tone = 'neutral', outline = false, dot = false, className, title }: { children: ReactNode; tone?: Tone; outline?: boolean; dot?: boolean; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex h-5 max-w-full items-center gap-1 rounded-md border px-1.5 text-[11.5px] font-medium whitespace-nowrap [&_svg]:size-3 [&_svg]:shrink-0',
        outline ? 'border-line bg-transparent text-fg-muted' : soft[tone],
        className,
      )}
    >
      {dot && <span className={cn('size-1.5 shrink-0 rounded-full', dots[tone])} />}
      {/* Preflight makes svg display:block, which would break the line inside the truncating span. */}
      <span className="flex min-w-0 items-center gap-1 truncate [&_svg]:inline-block">{children}</span>
    </span>
  )
}

export function statusTone(status: string | null | undefined): Tone {
  const value = (status || 'unknown').toLowerCase()
  if (['succeeded', 'success', 'completed', 'approved', 'healthy', 'ok', 'passed', 'resolved', 'delivered', 'exact', 'local/free'].includes(value))
    return 'success'
  if (['failed', 'error', 'rejected', 'degraded', 'firing', 'regressed', 'down'].includes(value))
    return 'danger'
  if (['running', 'in_progress', 'started', 'connecting', 'checking'].includes(value))
    return 'info'
  if (value.includes('replay'))
    return 'violet'
  if (['waiting_approval', 'pending', 'estimated', 'warning', 'retrying'].includes(value))
    return 'warning'
  return 'neutral'
}

const STATUS_LABELS: Record<string, string> = {
  succeeded: 'Success',
  completed: 'Completed',
  failed: 'Error',
  running: 'Running',
  waiting_approval: 'Awaiting approval',
  healthy: 'Healthy',
  degraded: 'Degraded',
  planned: 'Planned',
  unknown: 'Unknown',
}

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  const value = status || 'unknown'
  const tone = statusTone(value)
  const icon = tone === 'success'
    ? <CheckCircle2 />
    : tone === 'danger'
      ? <XCircle />
      : tone === 'info'
        ? <Loader2 className="animate-spin" />
        : tone === 'warning'
          ? <PauseCircle />
          : value === 'planned' ? <CircleDashed /> : <Clock />
  return <Badge tone={tone}>{icon}{label ?? STATUS_LABELS[value] ?? value.replaceAll('_', ' ')}</Badge>
}

export function StatusDot({ status, pulse = false, className }: { status: string | null | undefined; pulse?: boolean; className?: string }) {
  const tone = statusTone(status)
  return (
    <span className={cn('relative inline-flex size-2 shrink-0', className)}>
      {pulse && <span className={cn('absolute inset-0 rounded-full opacity-60 animate-live', dots[tone])} />}
      <span className={cn('relative inline-flex size-2 rounded-full', dots[tone])} />
    </span>
  )
}

export function CostStatusBadge({ status }: { status?: string | null }) {
  const value = status || 'unknown'
  const tone: Tone = value === 'exact' || value === 'local/free' ? 'success' : value === 'estimated' ? 'warning' : 'neutral'
  return <Badge tone={tone} outline={tone === 'neutral'}>{value}</Badge>
}
