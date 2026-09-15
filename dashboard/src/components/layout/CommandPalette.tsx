import { CornerDownLeft, Keyboard, MessagesSquare, Moon, RefreshCw, Search, Sun } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Section } from '../../appTypes'
import { cn } from '../../lib/utils'
import type { SessionSummary, TraceSummary } from '../../types'
import { formatRelative, shortId } from '../../utils/format'
import { StatusDot } from '../ui/Badge'
import { Kbd } from '../ui/Button'
import { ALL_NAV_ITEMS } from './nav'

interface Command {
  id: string
  group: string
  label: string
  detail?: string
  icon: ReactNode
  keywords: string
  run: () => void
}

export function CommandPalette({
  open,
  onClose,
  traces,
  sessions,
  onSection,
  onTrace,
  onSession,
  onRefresh,
  onToggleTheme,
  onShowShortcuts,
  dark,
}: {
  open: boolean
  onClose: () => void
  traces: TraceSummary[]
  sessions: SessionSummary[]
  onSection: (section: Section) => void
  onTrace: (traceId: string) => void
  onSession: (sessionId: string) => void
  onRefresh: () => void
  onToggleTheme: () => void
  onShowShortcuts: () => void
  dark: boolean
}) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
    }
  }, [open])

  const commands = useMemo<Command[]>(() => [
    ...ALL_NAV_ITEMS.map(item => ({
      id: `page-${item.id}`,
      group: 'Pages',
      label: item.label,
      detail: item.description,
      icon: item.icon,
      keywords: `${item.label} ${item.description}`,
      run: () => onSection(item.id),
    })),
    {
      id: 'action-theme',
      group: 'Actions',
      label: dark ? 'Switch to light theme' : 'Switch to dark theme',
      icon: dark ? <Sun /> : <Moon />,
      keywords: 'theme dark light appearance',
      run: onToggleTheme,
    },
    { id: 'action-refresh', group: 'Actions', label: 'Refresh data', icon: <RefreshCw />, keywords: 'refresh reload', run: onRefresh },
    { id: 'action-shortcuts', group: 'Actions', label: 'Keyboard shortcuts', detail: 'Press ? anywhere', icon: <Keyboard />, keywords: 'keyboard shortcuts hotkeys help', run: onShowShortcuts },
    ...traces.slice(0, 200).map(trace => ({
      id: `trace-${trace.trace_id}`,
      group: 'Traces',
      label: trace.workflow_name ?? trace.name,
      detail: `${shortId(trace.trace_id)} · ${formatRelative(trace.started_at)}${trace.error_message ? ` · ${trace.error_message}` : ''}`,
      icon: <StatusDot status={trace.status} />,
      keywords: `${trace.name} ${trace.workflow_name ?? ''} ${trace.trace_id} ${trace.status} ${trace.error_type ?? ''} ${trace.model ?? ''} ${trace.session_id ?? ''}`,
      run: () => onTrace(trace.trace_id),
    })),
    ...sessions.slice(0, 50).map(session => ({
      id: `session-${session.session_id}`,
      group: 'Sessions',
      label: session.session_id,
      detail: `${session.trace_count} turns${session.user_id ? ` · ${session.user_id}` : ''}`,
      icon: <MessagesSquare />,
      keywords: `session ${session.session_id} ${session.user_id ?? ''}`,
      run: () => onSession(session.session_id),
    })),
  ], [traces, sessions, dark, onSection, onTrace, onSession, onRefresh, onToggleTheme, onShowShortcuts])

  const results = useMemo(() => {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
    const matched = terms.length ? commands.filter(command => terms.every(term => command.keywords.toLowerCase().includes(term))) : commands.filter(command => command.group !== 'Sessions')
    const limited: Command[] = []
    const perGroup = new Map<string, number>()
    for (const command of matched) {
      const count = perGroup.get(command.group) ?? 0
      if (count < (terms.length ? 8 : command.group === 'Traces' ? 5 : 20)) {
        limited.push(command)
        perGroup.set(command.group, count + 1)
      }
    }
    return limited
  }, [commands, query])

  useEffect(() => {
    setActive(0)
  }, [query])

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active])

  if (!open)
    return null

  const run = (command: Command | undefined) => {
    if (!command)
      return
    onClose()
    command.run()
  }

  let lastGroup = ''
  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center px-4 pt-[12vh]">
      <button aria-label="Close search" className="animate-fade-in absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-label="Search" className="animate-fade-in relative w-full max-w-xl overflow-hidden rounded-xl border border-line bg-surface shadow-pop">
        <div className="flex items-center gap-2.5 border-b border-line px-4">
          <Search className="size-4 text-fg-subtle" />
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={event => setQuery(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setActive(value => Math.min(value + 1, results.length - 1))
              }
              else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setActive(value => Math.max(value - 1, 0))
              }
              else if (event.key === 'Enter') {
                event.preventDefault()
                run(results[active])
              }
              else if (event.key === 'Escape') {
                onClose()
              }
            }}
            placeholder="Search pages, traces, sessions, and actions"
            className="h-12 flex-1 bg-transparent text-[14px] text-fg outline-none placeholder:text-fg-subtle"
          />
          <Kbd>Esc</Kbd>
        </div>
        <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-1.5">
          {results.length === 0 && <div className="px-3 py-8 text-center text-[13px] text-fg-subtle">No results for "{query}"</div>}
          {results.map((command, index) => {
            const header = command.group !== lastGroup
            lastGroup = command.group
            return (
              <div key={command.id}>
                {header && <div className="px-2.5 pt-2 pb-1 text-[11px] font-medium tracking-wide text-fg-subtle uppercase">{command.group}</div>}
                <button
                  data-index={index}
                  className={cn('flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left [&_svg]:size-4', index === active ? 'bg-surface-2' : 'hover:bg-surface-2/60')}
                  onMouseMove={() => setActive(index)}
                  onClick={() => run(command)}
                >
                  <span className="grid size-5 shrink-0 place-items-center text-fg-subtle">{command.icon}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] text-fg">{command.label}</span>
                    {command.detail && <span className="block truncate text-xs text-fg-subtle">{command.detail}</span>}
                  </span>
                  {index === active && <CornerDownLeft className="size-3.5 text-fg-subtle" />}
                </button>
              </div>
            )
          })}
        </div>
        <div className="flex items-center gap-3 border-t border-line bg-surface-2/50 px-4 py-2 text-[11.5px] text-fg-subtle">
          <span className="inline-flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> navigate</span>
          <span className="inline-flex items-center gap-1"><Kbd>Enter</Kbd> open</span>
        </div>
      </div>
    </div>
  )
}
