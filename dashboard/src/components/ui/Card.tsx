import { Inbox } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export function Card({
  title,
  description,
  icon,
  actions,
  children,
  className,
  bodyClassName,
  flush = false,
}: {
  title?: ReactNode
  description?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  className?: string
  bodyClassName?: string
  /** Remove body padding, for tables and lists that run edge to edge. */
  flush?: boolean
}) {
  return (
    <section className={cn('flex min-w-0 flex-col rounded-xl border border-line bg-surface shadow-card', className)}>
      {(title || actions) && (
        <header className="flex min-h-12 items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-2">
            {icon && <span className="text-fg-subtle [&_svg]:size-4">{icon}</span>}
            <div className="min-w-0">
              <h2 className="truncate text-[13.5px] font-semibold text-fg">{title}</h2>
              {description && <p className="truncate text-xs text-fg-subtle">{description}</p>}
            </div>
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cn('min-w-0 flex-1', !flush && 'p-4', bodyClassName)}>{children}</div>
    </section>
  )
}

export function PageHeader({ title, description, actions, children }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-fg">{title}</h1>
          {description && <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

export function EmptyState({ icon, title, detail, action, className }: { icon?: ReactNode; title: string; detail?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 px-6 py-10 text-center', className)}>
      <div className="grid size-10 place-items-center rounded-lg border border-line bg-surface-2 text-fg-subtle [&_svg]:size-5">
        {icon ?? <Inbox />}
      </div>
      <div className="text-[13.5px] font-medium text-fg">{title}</div>
      {detail && <div className="max-w-md text-[13px] leading-5 text-fg-muted">{detail}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton rounded-md', className)} />
}

export function KeyValue({ rows, className }: { rows: Array<[string, ReactNode]>; className?: string }) {
  const visible = rows.filter(([, value]) => value !== undefined && value !== null && value !== '')
  return (
    <dl className={cn('grid grid-cols-[minmax(96px,auto)_1fr] gap-x-4 gap-y-2 text-[13px]', className)}>
      {visible.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-fg-subtle">{label}</dt>
          <dd className="min-w-0 break-words text-fg">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** A thin horizontal bar showing a share of the largest value. */
export function Meter({ value, max, tone = 'accent', className }: { value: number; max: number; tone?: 'accent' | 'success' | 'danger' | 'warning' | 'info'; className?: string }) {
  const width = max > 0 ? Math.max(Math.min((value / max) * 100, 100), value > 0 ? 2 : 0) : 0
  const color = { accent: 'bg-accent', success: 'bg-success', danger: 'bg-danger', warning: 'bg-warning', info: 'bg-info' }[tone]
  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-surface-3', className)}>
      <div className={cn('h-full rounded-full', color)} style={{ width: `${width}%` }} />
    </div>
  )
}

export function Callout({ tone = 'info', icon, title, children, actions }: { tone?: 'info' | 'danger' | 'warning' | 'success'; icon?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  const palette = {
    info: 'border-info/30 bg-info-soft text-info-text',
    danger: 'border-danger/30 bg-danger-soft text-danger-text',
    warning: 'border-warning/30 bg-warning-soft text-warning-text',
    success: 'border-success/30 bg-success-soft text-success-text',
  }[tone]
  return (
    <div className={cn('flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between', palette)}>
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <span className="mt-0.5 [&_svg]:size-4">{icon}</span>}
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold">{title}</div>
          {children && <div className="mt-0.5 text-[13px] text-fg-muted">{children}</div>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
