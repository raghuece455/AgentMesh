import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export const CHART_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)']

export const axisProps = {
  tickLine: false,
  axisLine: false,
  tickMargin: 8,
  fontSize: 11,
  stroke: 'var(--fg-subtle)',
} as const

export const gridProps = {
  stroke: 'var(--chart-grid)',
  strokeDasharray: '0',
  vertical: false,
} as const

interface TooltipEntry {
  name?: string | number
  value?: number | string | Array<number | string>
  color?: string
  dataKey?: string | number
  payload?: Record<string, unknown>
}

/** Recharts tooltip content that follows the dashboard theme. */
export function ChartTooltip({ active, payload, label, formatter, labelFormatter }: {
  active?: boolean
  payload?: TooltipEntry[]
  label?: string | number
  formatter?: (value: number, name: string) => string
  labelFormatter?: (label: string) => string
}) {
  if (!active || !payload?.length)
    return null
  return (
    <div className="min-w-36 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-pop">
      {label !== undefined && <div className="mb-1.5 font-medium text-fg">{labelFormatter ? labelFormatter(String(label)) : label}</div>}
      <div className="flex flex-col gap-1">
        {payload.map(entry => (
          <div key={String(entry.dataKey ?? entry.name)} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-fg-muted">
              <span className="size-2 rounded-sm" style={{ background: entry.color }} />
              {entry.name}
            </span>
            <span className="tabular font-medium text-fg">{formatter ? formatter(Number(entry.value), String(entry.name)) : String(entry.value)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function ChartLegend({ items, className }: { items: Array<{ label: string; color: string; value?: ReactNode }>; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted', className)}>
      {items.map(item => (
        <span key={item.label} className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-sm" style={{ background: item.color }} />
          {item.label}
          {item.value !== undefined && <span className="tabular font-medium text-fg">{item.value}</span>}
        </span>
      ))}
    </div>
  )
}
