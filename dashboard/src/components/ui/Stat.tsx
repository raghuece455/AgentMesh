import type { ReactNode } from 'react'
import { useId } from 'react'
import { cn } from '../../lib/utils'

export function Sparkline({ values, color = 'var(--chart-1)', height = 32, className, fill = true }: { values: number[]; color?: string; height?: number; className?: string; fill?: boolean }) {
  const id = useId().replaceAll(':', '')
  const width = 120
  if (values.length < 2 || values.every(value => value === 0))
    return <svg className={className} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" height={height}><line x1="0" x2={width} y1={height - 2} y2={height - 2} stroke="var(--border-strong)" strokeDasharray="3 3" /></svg>
  const max = Math.max(...values)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const step = width / (values.length - 1)
  const points = values.map((value, index) => [index * step, height - 2 - ((value - min) / span) * (height - 4)] as const)
  const line = points.map(([x, y], index) => `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  return (
    <svg className={className} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" height={height} aria-hidden>
      <defs>
        <linearGradient id={`spark-${id}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.28} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      {fill && <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#spark-${id})`} />}
      <path d={line} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

export function StatCard({
  label,
  value,
  sub,
  icon,
  spark,
  sparkColor,
  tone = 'neutral',
  onClick,
  className,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: ReactNode
  spark?: number[]
  sparkColor?: string
  tone?: 'neutral' | 'success' | 'danger' | 'warning'
  onClick?: () => void
  className?: string
}) {
  const valueColor = { neutral: 'text-fg', success: 'text-fg', danger: 'text-danger-text', warning: 'text-warning-text' }[tone]
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      className={cn('group flex min-w-0 flex-col justify-between gap-2 rounded-xl border border-line bg-surface p-4 text-left shadow-card transition-colors', onClick && 'hover:border-line-strong hover:bg-surface-2/40', className)}
      onClick={onClick}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[12.5px] font-medium text-fg-muted">{label}</span>
        {icon && <span className="text-fg-subtle [&_svg]:size-3.5">{icon}</span>}
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className={cn('tabular truncate text-2xl font-semibold tracking-tight', valueColor)}>{value}</div>
          {/* Always reserve the subtitle line so values line up across a row of cards. */}
          <div className="mt-0.5 truncate text-xs text-fg-subtle">{sub ?? ' '}</div>
        </div>
        {spark && <Sparkline values={spark} color={sparkColor} className="hidden h-8 w-24 shrink-0 sm:block" />}
      </div>
    </Tag>
  )
}

/** Inline row of small labelled numbers, for page and trace headers. */
export function StatStrip({ items, className }: { items: Array<{ label: string; value: ReactNode; tone?: 'danger' | 'success' | 'warning' }>; className?: string }) {
  return (
    <div className={cn('grid grid-cols-2 divide-line overflow-hidden rounded-xl border border-line bg-surface shadow-card sm:grid-cols-3 lg:flex lg:divide-x', className)}>
      {items.map(item => (
        <div key={item.label} className="min-w-0 flex-1 border-b border-line px-4 py-3 lg:border-b-0">
          <div className="truncate text-xs text-fg-subtle">{item.label}</div>
          <div className={cn('tabular mt-0.5 truncate text-[15px] font-semibold', item.tone === 'danger' ? 'text-danger-text' : item.tone === 'success' ? 'text-success-text' : item.tone === 'warning' ? 'text-warning-text' : 'text-fg')}>{item.value}</div>
        </div>
      ))}
    </div>
  )
}
