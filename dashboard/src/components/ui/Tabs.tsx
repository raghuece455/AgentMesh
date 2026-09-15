import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export interface TabItem<T extends string> {
  value: T
  label: ReactNode
  count?: number | string
  icon?: ReactNode
  disabled?: boolean
}

/** Underlined tabs, as in Vercel and GitHub project pages. */
export function Tabs<T extends string>({ value, onChange, items, className }: { value: T; onChange: (value: T) => void; items: Array<TabItem<T>>; className?: string }) {
  return (
    <div role="tablist" className={cn('flex min-w-0 items-center gap-1 overflow-x-auto overflow-y-hidden border-b border-line', className)}>
      {items.map(item => {
        const active = item.value === value
        return (
          <button
            key={item.value}
            role="tab"
            aria-selected={active}
            disabled={item.disabled}
            className={cn(
              'relative -mb-px inline-flex h-9 shrink-0 items-center gap-1.5 border-b-2 px-2.5 text-[13px] font-medium transition-colors disabled:opacity-40 [&_svg]:size-3.5',
              active ? 'border-accent text-fg' : 'border-transparent text-fg-muted hover:text-fg',
            )}
            onClick={() => onChange(item.value)}
          >
            {item.icon}
            {item.label}
            {item.count !== undefined && (
              <span className={cn('tabular rounded px-1 text-[11px]', active ? 'bg-accent-soft text-accent-text' : 'bg-surface-2 text-fg-subtle')}>{item.count}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/** Compact segmented control, for time ranges and view switches. */
export function Segmented<T extends string>({ value, onChange, options, className, size = 'md' }: { value: T; onChange: (value: T) => void; options: Array<{ value: T; label: ReactNode; title?: string }>; className?: string; size?: 'sm' | 'md' }) {
  return (
    <div className={cn('inline-flex shrink-0 items-center rounded-lg border border-line bg-surface-2 p-0.5', className)}>
      {options.map(option => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            title={option.title}
            aria-pressed={active}
            className={cn(
              'inline-flex items-center gap-1 rounded-md font-medium transition-colors [&_svg]:size-3.5',
              size === 'sm' ? 'h-6 px-2 text-xs' : 'h-7 px-2.5 text-[12.5px]',
              active ? 'bg-surface text-fg shadow-card ring-1 ring-line' : 'text-fg-muted hover:text-fg',
            )}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
