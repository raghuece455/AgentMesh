import { ListFilter } from 'lucide-react'
import type { ReactNode } from 'react'

export function toneClass(tone: string, target: 'icon' | 'card') {
  if (target === 'icon') {
    if (tone === 'good')
      return 'bg-emerald-400/24 text-emerald-50 ring-1 ring-emerald-200/20'
    if (tone === 'warn')
      return 'bg-amber-400/24 text-amber-50 ring-1 ring-amber-200/20'
    if (tone === 'danger')
      return 'bg-rose-400/24 text-rose-50 ring-1 ring-rose-200/20'
    if (tone === 'money')
      return 'bg-sky-400/24 text-sky-50 ring-1 ring-sky-200/20'
    return 'bg-white/14 text-white/84 ring-1 ring-white/10'
  }
  if (tone === 'good')
    return 'border-emerald-200/24 bg-emerald-400/12'
  if (tone === 'warn')
    return 'border-amber-200/24 bg-amber-400/12'
  if (tone === 'danger')
    return 'border-rose-200/24 bg-rose-400/12'
  return 'border-white/14 bg-black/22'
}

export function MetricCard({ icon, label, value, tone = 'neutral', compact = false }: { icon: ReactNode; label: string; value: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'danger' | 'money'; compact?: boolean }) {
  return (
    <div className={`vision-glass-soft border-white/22 bg-slate-950/22 ${compact ? 'p-3' : 'p-4'}`}>
      <div className="flex items-center justify-between gap-3">
        <div className={`grid ${compact ? 'size-8' : 'size-9'} place-items-center rounded-full ${toneClass(tone, 'icon')}`}>{icon}</div>
        <div className="text-xs/5 font-medium text-white/58">{label}</div>
      </div>
      <div className={`mt-2 font-semibold text-white ${compact ? 'text-base/6' : 'text-2xl/8'}`}>{value}</div>
    </div>
  )
}

export function Panel({ title, icon, children, actions, className = '' }: { title: string; icon: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`vision-glass-soft min-w-0 border-white/20 bg-slate-950/18 p-4 ${className}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="grid size-8 shrink-0 place-items-center rounded-full bg-white/13 text-white/84 ring-1 ring-white/10">{icon}</div>
          <h2 className="truncate text-lg/7 font-semibold text-white">{title}</h2>
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}

export function PanelInset({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/14 bg-slate-950/24 p-3">
      <div className="mb-2 text-sm/6 font-semibold text-white">{title}</div>
      {children}
    </div>
  )
}

export function ChartFrame({ children, dense = false }: { children: ReactNode; dense?: boolean }) {
  return <div className={`${dense ? 'h-56 min-h-56' : 'h-64 min-h-64'} w-full min-w-0 overflow-hidden`}>{children}</div>
}

export function AnswerCard({ label, value, tone = 'neutral' }: { label: string; value: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'danger' }) {
  return (
    <div className={`rounded-2xl border p-3 ${toneClass(tone, 'card')}`}>
      <div className="text-xs/5 font-medium text-white/58">{label}</div>
      <div className="mt-1 break-words text-sm/6 font-semibold text-white">{value}</div>
    </div>
  )
}

export function EmptyState({ icon = <ListFilter className="size-5" />, title, detail }: { icon?: ReactNode; title: string; detail?: string }) {
  return (
    <div className="grid min-h-28 place-items-center rounded-2xl border border-dashed border-white/22 bg-slate-950/20 text-center">
      <div>
        <div className="mx-auto grid size-10 place-items-center rounded-full bg-white/13 text-white/70 ring-1 ring-white/10">{icon}</div>
        <div className="mt-2 text-sm/6 font-semibold text-white/78">{title}</div>
        {detail && <div className="mt-1 max-w-sm text-xs/5 text-white/50">{detail}</div>}
      </div>
    </div>
  )
}

export function LoadingState({ title = 'Loading observability data' }: { title?: string }) {
  return <EmptyState title={title} detail="Waiting for the AgentMesh API to return the latest trace data." />
}

export function ErrorState({ title = 'Request failed', detail }: { title?: string; detail?: string }) {
  return <EmptyState title={title} detail={detail} />
}
