import { ArrowLeftRight, ArrowUpRight } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { getTrace, listTraces } from '../../api'
import { cn } from '../../lib/utils'
import type { SpanRecord, TraceDetail, TraceSummary } from '../../types'
import { errorText, formatMoney, formatMs, formatNumber, formatRelative, numeric, shortId } from '../../utils/format'
import { flattenSpans, spanKind, spanLabel, type SpanKind } from '../../utils/traces'
import { Badge, StatusBadge, StatusDot } from '../ui/Badge'
import { Button } from '../ui/Button'
import { EmptyState, Skeleton } from '../ui/Card'
import { SearchInput } from '../ui/Field'
import { Drawer } from '../ui/Overlay'
import { SpanKindIcon } from './SpanKindIcon'

const MAX_DIFF_SPANS = 400

interface DiffRow {
  kind: SpanKind
  label: string
  left: SpanRecord | null
  right: SpanRecord | null
}

/**
 * Pair the two traces' spans in execution order with a longest-common-subsequence match on
 * span kind and label, so a run that added, dropped, or repeated a step lines up with the other.
 */
export function diffSpans(left: SpanRecord[], right: SpanRecord[]): DiffRow[] {
  const a = flattenSpans(left).rows.slice(0, MAX_DIFF_SPANS).map(row => row.span)
  const b = flattenSpans(right).rows.slice(0, MAX_DIFF_SPANS).map(row => row.span)
  const key = (span: SpanRecord) => `${spanKind(span)}:${spanLabel(span)}`
  const keysA = a.map(key)
  const keysB = b.map(key)
  const lengths = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--)
      lengths[i][j] = keysA[i] === keysB[j] ? lengths[i + 1][j + 1] + 1 : Math.max(lengths[i + 1][j], lengths[i][j + 1])
  }
  const rows: DiffRow[] = []
  let i = 0
  let j = 0
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && keysA[i] === keysB[j]) {
      rows.push({ kind: spanKind(a[i]), label: spanLabel(a[i]), left: a[i], right: b[j] })
      i++
      j++
    }
    else if (j >= b.length || (i < a.length && lengths[i + 1][j] >= lengths[i][j + 1])) {
      rows.push({ kind: spanKind(a[i]), label: spanLabel(a[i]), left: a[i], right: null })
      i++
    }
    else {
      rows.push({ kind: spanKind(b[j]), label: spanLabel(b[j]), left: null, right: b[j] })
      j++
    }
  }
  return rows
}

export function TraceCompare({
  open,
  onClose,
  detail,
  candidates,
  onOpenTrace,
}: {
  open: boolean
  onClose: () => void
  detail: TraceDetail
  candidates: TraceSummary[]
  onOpenTrace: (traceId: string) => void
}) {
  const trace = detail.trace!
  const [otherId, setOtherId] = useState('')
  const [other, setOther] = useState<TraceDetail | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [changesOnly, setChangesOnly] = useState(false)

  useEffect(() => {
    if (!otherId) {
      setOther(null)
      return
    }
    let cancelled = false
    setOther(null)
    setError('')
    getTrace(otherId)
      .then(result => { if (!cancelled) setOther(result) })
      .catch(caught => { if (!cancelled) setError(errorText(caught)) })
    return () => { cancelled = true }
  }, [otherId])

  // The loaded list may be filtered (for example to failures only), so also fetch this workflow's
  // other runs: comparing a failed run with a successful one is the usual reason to compare.
  const [sameWorkflow, setSameWorkflow] = useState<TraceSummary[]>([])
  useEffect(() => {
    if (!open)
      return
    let cancelled = false
    listTraces({ workflow: trace.workflow_name ?? trace.name, limit: 100 })
      .then(rows => { if (!cancelled) setSameWorkflow(rows) })
      .catch(() => { if (!cancelled) setSameWorkflow([]) })
    return () => { cancelled = true }
  }, [open, trace.workflow_name, trace.name])

  // Most useful comparisons first: other runs of the same workflow, newest first.
  const options = useMemo(() => {
    const terms = query.trim().toLowerCase()
    const seen = new Set<string>()
    return [...sameWorkflow, ...candidates]
      .filter(item => !seen.has(item.trace_id) && Boolean(seen.add(item.trace_id)))
      .filter(item => item.trace_id !== trace.trace_id)
      .filter(item => !terms || `${item.workflow_name ?? item.name} ${item.trace_id} ${item.status}`.toLowerCase().includes(terms))
      .sort((x, y) => Number((y.workflow_name ?? y.name) === (trace.workflow_name ?? trace.name)) - Number((x.workflow_name ?? x.name) === (trace.workflow_name ?? trace.name)) || y.started_at.localeCompare(x.started_at))
      .slice(0, 100)
  }, [candidates, sameWorkflow, query, trace])

  const rows = useMemo(() => other ? diffSpans(detail.spans, other.spans) : [], [detail, other])
  const shown = changesOnly ? rows.filter(row => !row.left || !row.right || row.left.status !== row.right.status) : rows
  const summary = useMemo(() => ({
    added: rows.filter(row => !row.left).length,
    removed: rows.filter(row => !row.right).length,
    statusChanged: rows.filter(row => row.left && row.right && row.left.status !== row.right.status).length,
  }), [rows])

  const close = () => {
    setOtherId('')
    setQuery('')
    onClose()
  }

  return (
    <Drawer
      open={open}
      onClose={close}
      width="max-w-5xl"
      title="Compare traces"
      description={other ? undefined : `Pick a trace to compare with ${trace.workflow_name ?? trace.name}.`}
    >
      {!otherId && (
        <div className="flex flex-col gap-3">
          <SearchInput className="w-full" value={query} onChange={setQuery} placeholder="Filter by name, id, or status" />
          {options.length === 0
            ? <EmptyState title="No other traces" detail="Widen the time range to find more traces to compare with." />
            : (
                <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
                  {options.map(option => (
                    <li key={option.trace_id}>
                      <button className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2/70" onClick={() => setOtherId(option.trace_id)}>
                        <StatusDot status={option.status} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-fg">{option.workflow_name ?? option.name}</span>
                          <span className="block truncate font-mono text-[11px] text-fg-subtle">{shortId(option.trace_id)}</span>
                        </span>
                        {(option.workflow_name ?? option.name) === (trace.workflow_name ?? trace.name) && <Badge tone="accent">same workflow</Badge>}
                        <span className="tabular w-16 text-right text-xs text-fg-muted">{formatMs(option.duration_ms)}</span>
                        <span className="w-20 text-right text-xs text-fg-subtle">{formatRelative(option.started_at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
        </div>
      )}

      {otherId && error && <EmptyState title="Could not load the other trace" detail={error} action={<Button onClick={() => setOtherId('')}>Pick another</Button>} />}
      {otherId && !error && !other && <div className="flex flex-col gap-3"><Skeleton className="h-24" /><Skeleton className="h-64" /></div>}

      {other?.trace && (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-[1fr_auto_1fr] items-stretch gap-3">
            <TraceHeader label="This trace" trace={trace} />
            <div className="grid place-items-center text-fg-subtle"><ArrowLeftRight className="size-4" /></div>
            <TraceHeader
              label="Compared with"
              trace={other.trace}
              actions={(
                <>
                  <Button size="xs" variant="ghost" onClick={() => setOtherId('')}>Change</Button>
                  <Button size="xs" variant="ghost" onClick={() => { const id = other.trace!.trace_id; close(); onOpenTrace(id) }}>Open<ArrowUpRight /></Button>
                </>
              )}
            />
          </div>

          <div className="overflow-hidden rounded-lg border border-line">
            <table className="w-full text-[13px]">
              <thead className="bg-surface-2/60 text-[11.5px] text-fg-subtle">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Metric</th>
                  <th className="px-3 py-2 text-right font-medium">This trace</th>
                  <th className="px-3 py-2 text-right font-medium">Compared</th>
                  <th className="px-3 py-2 text-right font-medium" title="The compared trace minus this trace">Compared vs this</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                <MetricRow label="Duration" left={numeric(trace.duration_ms)} right={numeric(other.trace.duration_ms)} format={formatMs} lowerIsBetter />
                <MetricRow label="Spans" left={detail.spans.length} right={other.spans.length} format={formatNumber} />
                <MetricRow label="LLM calls" left={detail.model_calls.length} right={other.model_calls.length} format={formatNumber} lowerIsBetter />
                <MetricRow label="Tool calls" left={detail.tool_calls.length} right={other.tool_calls.length} format={formatNumber} />
                <MetricRow label="Tokens" left={numeric(trace.total_tokens)} right={numeric(other.trace.total_tokens)} format={formatNumber} lowerIsBetter />
                <MetricRow label="Cost" left={numeric(trace.estimated_cost)} right={numeric(other.trace.estimated_cost)} format={formatMoney} lowerIsBetter />
                <MetricRow label="Failed spans" left={detail.spans.filter(span => span.status === 'failed').length} right={other.spans.filter(span => span.status === 'failed').length} format={formatNumber} lowerIsBetter />
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-[13.5px] font-semibold text-fg">Execution steps</h3>
                <p className="text-xs text-fg-subtle">
                  {summary.added || summary.removed || summary.statusChanged
                    ? `${summary.removed} only in this trace · ${summary.added} only in the compared trace · ${summary.statusChanged} changed status`
                    : 'Both traces ran the same steps in the same order.'}
                </p>
              </div>
              <Button size="sm" variant={changesOnly ? 'subtle' : 'ghost'} aria-pressed={changesOnly} onClick={() => setChangesOnly(value => !value)}>Differences only</Button>
            </div>
            <div className="overflow-hidden rounded-lg border border-line">
              <table className="w-full text-[13px]">
                <thead className="bg-surface-2/60 text-[11.5px] text-fg-subtle">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Step</th>
                    <th className="w-40 px-3 py-2 text-left font-medium">This trace</th>
                    <th className="w-40 px-3 py-2 text-left font-medium">Compared</th>
                    <th className="w-28 px-3 py-2 text-right font-medium" title="The compared trace minus this trace">Compared vs this</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {shown.map((row, index) => {
                    const statusChanged = row.left && row.right && row.left.status !== row.right.status
                    const delta = row.left && row.right ? numeric(row.right.duration_ms) - numeric(row.left.duration_ms) : null
                    return (
                      <tr key={index} className={cn(!row.right && 'bg-danger-soft/30', !row.left && 'bg-success-soft/30', statusChanged && 'bg-warning-soft/40')}>
                        <td className="px-3 py-1.5">
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="w-3 shrink-0 text-center font-mono text-xs text-fg-subtle">{!row.right ? '−' : !row.left ? '+' : ''}</span>
                            <SpanKindIcon kind={row.kind} />
                            <span className="truncate text-fg">{row.label}</span>
                          </span>
                        </td>
                        <td className="px-3 py-1.5"><SideCell span={row.left} /></td>
                        <td className="px-3 py-1.5"><SideCell span={row.right} /></td>
                        <td className={cn('tabular px-3 py-1.5 text-right text-xs', delta === null ? 'text-fg-subtle' : delta > 0 ? 'text-warning-text' : delta < 0 ? 'text-success-text' : 'text-fg-subtle')}>
                          {delta === null ? (row.left ? 'removed' : 'added') : delta === 0 ? '-' : `${delta > 0 ? '+' : '-'}${formatMs(Math.abs(delta))}`}
                        </td>
                      </tr>
                    )
                  })}
                  {shown.length === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-[13px] text-fg-subtle">No differences in the steps.</td></tr>}
                </tbody>
              </table>
            </div>
            {(detail.spans.length > MAX_DIFF_SPANS || other.spans.length > MAX_DIFF_SPANS) && <p className="text-xs text-fg-subtle">Only the first {MAX_DIFF_SPANS} spans of each trace are compared.</p>}
          </div>
        </div>
      )}
    </Drawer>
  )
}

function TraceHeader({ label, trace, actions }: { label: string; trace: TraceSummary; actions?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-surface-2/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium tracking-wide text-fg-subtle uppercase">{label}</span>
        {actions && <span className="flex items-center gap-1">{actions}</span>}
      </div>
      <div className="mt-1 flex min-w-0 items-center gap-2">
        <span className="truncate text-[13.5px] font-semibold text-fg">{trace.workflow_name ?? trace.name}</span>
        <StatusBadge status={trace.status} />
      </div>
      <div className="mt-0.5 truncate font-mono text-[11px] text-fg-subtle">{shortId(trace.trace_id)} · {formatRelative(trace.started_at)}</div>
    </div>
  )
}

function MetricRow({ label, left, right, format, lowerIsBetter = false }: { label: string; left: number; right: number; format: (value: number) => string; lowerIsBetter?: boolean }) {
  const delta = right - left
  const better = lowerIsBetter ? delta < 0 : false
  const worse = lowerIsBetter ? delta > 0 : false
  const percent = left ? Math.round((delta / left) * 100) : null
  return (
    <tr>
      <td className="px-3 py-2 text-fg-muted">{label}</td>
      <td className="tabular px-3 py-2 text-right text-fg">{format(left)}</td>
      <td className="tabular px-3 py-2 text-right text-fg">{format(right)}</td>
      <td className={cn('tabular px-3 py-2 text-right', Math.abs(delta) < 1e-9 ? 'text-fg-subtle' : better ? 'text-success-text' : worse ? 'text-danger-text' : 'text-fg')}>
        {Math.abs(delta) < 1e-9 ? 'no change' : `${delta > 0 ? '+' : '-'}${format(Math.abs(delta))}${percent !== null && Number.isFinite(percent) ? ` (${delta > 0 ? '+' : ''}${percent}%)` : ''}`}
      </td>
    </tr>
  )
}

function SideCell({ span }: { span: SpanRecord | null }) {
  if (!span)
    return <span className="text-xs text-fg-subtle">not run</span>
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <StatusDot status={span.status === 'running' ? 'unknown' : span.status} />
      <span className="tabular text-fg-muted">{numeric(span.duration_ms) ? formatMs(span.duration_ms) : 'instant'}</span>
      {span.status === 'failed' && <span className="truncate text-danger-text">{span.error_type ?? 'failed'}</span>}
    </span>
  )
}
