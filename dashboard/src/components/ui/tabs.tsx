import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export function Tabs({
  value,
  onChange,
  tabs,
}: {
  value: string
  onChange: (value: string) => void
  tabs: Array<{ value: string; label: string; icon?: ReactNode }>
}) {
  return (
    <nav className="flex flex-wrap gap-2">
      {tabs.map(tab => (
        <button
          key={tab.value}
          className={cn(
            'inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm/6 transition',
            value === tab.value
              ? 'border-mesh-teal bg-teal-50 text-mesh-teal dark:border-teal-400 dark:bg-teal-950 dark:text-teal-100'
              : 'border-mesh-border bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800',
          )}
          onClick={() => onChange(tab.value)}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </nav>
  )
}

