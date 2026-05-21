import { Activity, Moon, RefreshCw, Search, Sun } from 'lucide-react'
import type { TraceSummary } from '../../types'
import { StatusBadge } from '../common/Badges'

export function TopBar({
  activeTrace,
  query,
  loading,
  dark,
  onQuery,
  onRefresh,
  onTheme,
}: {
  activeTrace: TraceSummary | null
  query: string
  loading: boolean
  dark: boolean
  onQuery: (query: string) => void
  onRefresh: () => void
  onTheme: () => void
}) {
  return (
    <header className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl/8 font-semibold tracking-normal text-white">Trace-first Agent Observability</h1>
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs/5 text-white/70">
          <Activity className="size-4 text-cyan-200" />
          <span>{activeTrace ? `${activeTrace.workflow_name ?? activeTrace.name} / ${activeTrace.trace_id}` : 'No trace selected'}</span>
          {activeTrace && <StatusBadge status={activeTrace.status} />}
          {loading && <span className="rounded-full bg-sky-400/20 px-2 py-0.5 text-sky-100">loading</span>}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <label className="vision-pill flex h-11 min-w-0 items-center gap-2.5 px-4 sm:min-w-80">
          <Search className="size-4 text-white/70" />
          <input
            className="min-w-0 flex-1 bg-transparent text-sm/6 text-white outline-hidden placeholder:text-white/45"
            value={query}
            onChange={event => onQuery(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter')
                onRefresh()
            }}
            placeholder="Search traces, agents, tools"
          />
        </label>
        <button className="vision-pill grid size-11 place-items-center hover:bg-white/12" onClick={onRefresh} aria-label="Refresh">
          <RefreshCw className="size-4" />
        </button>
        <button className="vision-pill grid size-11 place-items-center lg:hidden" onClick={onTheme} aria-label="Theme">
          {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </button>
      </div>
    </header>
  )
}
