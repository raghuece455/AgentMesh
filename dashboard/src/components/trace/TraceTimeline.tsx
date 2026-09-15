import { AlertOctagon, ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { cn } from '../../lib/utils'
import type { SpanRecord } from '../../types'
import { formatMoney, formatMs, numeric } from '../../utils/format'
import { flattenSpans, spanKind, spanLabel } from '../../utils/traces'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/Card'
import { SearchInput } from '../ui/Field'
import { KIND_META, SpanKindIcon } from './SpanKindIcon'

/**
 * Span tree and waterfall in one view, as in Datadog APM and Jaeger: each row is a span,
 * indented under its parent, with a bar placed on the trace's time axis.
 */
export function TraceTimeline({ spans, selectedId, onSelect }: { spans: SpanRecord[]; selectedId?: string; onSelect: (span: SpanRecord) => void }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')
  const [errorsOnly, setErrorsOnly] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const { rows, min, max } = useMemo(() => flattenSpans(spans), [spans])
  const total = Math.max(max - min, 1)
  const filtering = query.trim() !== '' || errorsOnly
  const failedCount = useMemo(() => spans.filter(isFailedSpan).length, [spans])

  // Parent chain for every span, used to keep a match's ancestors visible and to expand them on selection.
  const ancestors = useMemo(() => {
    const map = new Map<string, string[]>()
    const stack: Array<{ id: string; depth: number }> = []
    for (const row of rows) {
      while (stack.length && stack[stack.length - 1].depth >= row.depth)
        stack.pop()
      map.set(row.span.span_id, stack.map(item => item.id))
      stack.push({ id: row.span.span_id, depth: row.depth })
    }
    return map
  }, [rows])

  const matches = useMemo(() => {
    if (!filtering)
      return null
    const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const matched = new Set<string>()
    for (const { span } of rows) {
      if (errorsOnly && !isFailedSpan(span))
        continue
      const haystack = `${spanLabel(span)} ${span.event_type} ${span.agent_name ?? ''} ${span.model ?? ''} ${span.tool_name ?? ''} ${span.error_type ?? ''} ${span.error_message ?? ''}`.toLowerCase()
      if (terms.every(term => haystack.includes(term)))
        matched.add(span.span_id)
    }
    return matched
  }, [rows, query, errorsOnly, filtering])

  const visible = useMemo(() => {
    if (matches) {
      const keep = new Set<string>()
      for (const id of matches) {
        keep.add(id)
        ancestors.get(id)?.forEach(ancestor => keep.add(ancestor))
      }
      return rows.filter(row => keep.has(row.span.span_id))
    }
    const hidden = new Set<string>()
    const result = []
    const stack: Array<{ id: string; depth: number }> = []
    for (const row of rows) {
      while (stack.length && stack[stack.length - 1].depth >= row.depth)
        stack.pop()
      const parentHidden = stack.some(item => collapsed.has(item.id) || hidden.has(item.id))
      if (parentHidden)
        hidden.add(row.span.span_id)
      else
        result.push(row)
      stack.push({ id: row.span.span_id, depth: row.depth })
    }
    return result
  }, [rows, collapsed, matches, ancestors])

  // When the selection changes (for example with j/k), expand its parents and scroll it into view.
  // Only on a change, so Collapse all still works while a span is selected.
  const revealed = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!selectedId || revealed.current === selectedId)
      return
    const parents = ancestors.get(selectedId) ?? []
    if (parents.some(id => collapsed.has(id))) {
      setCollapsed(current => new Set([...current].filter(id => !parents.includes(id))))
      return
    }
    revealed.current = selectedId
    containerRef.current?.querySelector(`[data-span-id="${CSS.escape(selectedId)}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [selectedId, ancestors, collapsed])

  if (spans.length === 0)
    return <EmptyState title="No spans recorded" detail="This trace has no span data yet." />

  const ticks = [0, 0.25, 0.5, 0.75, 1]
  const parents = rows.filter(row => row.childCount > 0).map(row => row.span.span_id)
  const toggle = (id: string) => setCollapsed(current => {
    const next = new Set(current)
    if (next.has(id))
      next.delete(id)
    else
      next.add(id)
    return next
  })

  return (
    <div ref={containerRef} className="min-w-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <SearchInput className="w-56" value={query} onChange={setQuery} placeholder="Find spans" />
        <Button size="sm" variant={errorsOnly ? 'subtle' : 'ghost'} aria-pressed={errorsOnly} disabled={!failedCount && !errorsOnly} onClick={() => setErrorsOnly(value => !value)}>
          <AlertOctagon className={cn(errorsOnly && 'text-danger')} />Errors only{failedCount > 0 && <span className="tabular text-danger-text">{failedCount}</span>}
        </Button>
        {matches && <span className="text-xs text-fg-subtle">{matches.size} of {rows.length} spans match</span>}
        <div className="ml-auto flex items-center gap-1">
          <Button size="sm" variant="ghost" disabled={filtering || collapsed.size === 0} onClick={() => setCollapsed(new Set())}><ChevronsUpDown />Expand all</Button>
          <Button size="sm" variant="ghost" disabled={filtering || parents.length === 0} onClick={() => setCollapsed(new Set(parents))}><ChevronsDownUp />Collapse all</Button>
        </div>
      </div>
      {matches && matches.size === 0 && <EmptyState className="py-8" title="No spans match" detail="Try another search or turn off Errors only." />}
      <div className="max-h-[70vh] overflow-auto">
        <div className={cn('min-w-[720px]', matches && matches.size === 0 && 'hidden')}>
          <div className="sticky top-0 z-10 grid grid-cols-[minmax(260px,38%)_1fr] border-b border-line bg-surface text-[11px] text-fg-subtle">
            <div className="flex h-8 items-center px-4 font-medium">Span</div>
            <div className="relative h-8 border-l border-line">
              {ticks.map(tick => (
                <span key={tick} className={cn('absolute top-0 flex h-full items-center', tick === 1 ? '-translate-x-full pr-2' : 'pl-1.5')} style={{ left: `${tick * 100}%` }}>
                  <span className="tabular">{formatMs(total * tick)}</span>
                </span>
              ))}
            </div>
          </div>
          <div role="tree" aria-label="Spans">
            {visible.map(row => {
              const { span } = row
              const kind = spanKind(span)
              const failed = isFailedSpan(span)
              const selected = span.span_id === selectedId
              const context = matches !== null && !matches.has(span.span_id)
              const left = Number.isFinite(row.start) ? ((row.start - min) / total) * 100 : 0
              const width = Math.max(((row.end - row.start) / total) * 100, 0)
              const label = spanLabel(span)
              const secondary = label !== span.event_type ? span.event_type : span.agent_name ?? ''
              const duration = numeric(span.duration_ms) || row.end - row.start
              return (
                <div
                  key={span.span_id}
                  data-span-id={span.span_id}
                  role="treeitem"
                  aria-selected={selected}
                  tabIndex={0}
                  className={cn(
                    'group grid cursor-pointer grid-cols-[minmax(260px,38%)_1fr] border-b border-line/70 text-[13px] last:border-b-0',
                    selected ? 'bg-accent-soft/70' : 'hover:bg-surface-2/70',
                    // Ancestors shown only to place a match in the tree are dimmed.
                    context && !selected && 'opacity-50',
                  )}
                  onClick={() => onSelect(span)}
                  onKeyDown={event => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelect(span)
                    }
                  }}
                >
                  <div className={cn('relative flex h-9 min-w-0 items-center gap-1.5 pr-3', selected && 'shadow-[inset_2px_0_0_var(--accent)]')} style={{ paddingLeft: 12 + row.depth * 16 }}>
                    {Array.from({ length: row.depth }, (_, index) => (
                      <span key={index} className="absolute top-0 bottom-0 w-px bg-line" style={{ left: 21 + index * 16 }} />
                    ))}
                    {row.childCount > 0 && !matches
                      ? (
                          <button
                            aria-label={collapsed.has(span.span_id) ? 'Expand' : 'Collapse'}
                            className="relative grid size-4 shrink-0 place-items-center rounded text-fg-subtle hover:bg-surface-3 hover:text-fg"
                            onClick={event => {
                              event.stopPropagation()
                              toggle(span.span_id)
                            }}
                          >
                            {collapsed.has(span.span_id) ? <ChevronRight className="size-3" /> : <ChevronDown className="size-3" />}
                          </button>
                        )
                      : <span className="size-4 shrink-0" />}
                    <SpanKindIcon kind={kind} failed={failed} className="relative" />
                    <span className="min-w-0 truncate">
                      <span className={cn('font-medium', failed ? 'text-danger-text' : 'text-fg')}>{label}</span>
                      {secondary && <span className="ml-1.5 text-xs text-fg-subtle">{secondary}</span>}
                    </span>
                  </div>
                  <div className="relative h-9 border-l border-line">
                    {ticks.slice(1, -1).map(tick => <span key={tick} className="absolute top-0 bottom-0 w-px bg-line/60" style={{ left: `${tick * 100}%` }} />)}
                    {duration > 0
                      ? (
                          <>
                            <span
                              className={cn('absolute top-1/2 h-3.5 -translate-y-1/2 rounded-[3px]', failed ? 'bg-danger' : KIND_META[kind].bar, width < 0.4 && 'w-[3px]!', selected ? 'opacity-100 ring-2 ring-accent/30' : 'opacity-85 group-hover:opacity-100')}
                              style={{ left: `${Math.min(left, 99.5)}%`, width: `${width}%` }}
                            />
                            <span
                              className="tabular pointer-events-none absolute top-1/2 -translate-y-1/2 px-1.5 text-[11px] whitespace-nowrap text-fg-muted"
                              style={left + width > 70 ? { right: `${100 - left}%` } : { left: `${left + width}%` }}
                            >
                              {formatMs(duration)}{numeric(span.estimated_cost) > 0 ? ` · ${formatMoney(span.estimated_cost)}` : ''}
                            </span>
                          </>
                        )
                      : (
                          // An instant event: a point on the time axis rather than a bar.
                          <span
                            title="Instant event"
                            className={cn('absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[1px]', failed ? 'bg-danger' : KIND_META[kind].bar, selected && 'ring-2 ring-accent/40')}
                            style={{ left: `${Math.min(Math.max(left, 0.4), 99.6)}%` }}
                          />
                        )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

function isFailedSpan(span: SpanRecord): boolean {
  return span.status === 'failed' || Boolean(span.error_message)
}
