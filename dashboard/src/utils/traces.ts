import type { SpanRecord, TraceSummary } from '../types'
import { numeric } from './format'

export type TimeRange = '1h' | '24h' | '7d' | '30d' | 'all'

export const TIME_RANGES: Array<{ value: TimeRange; label: string; title: string; ms: number | null }> = [
  { value: '1h', label: '1h', title: 'Last hour', ms: 3600_000 },
  { value: '24h', label: '24h', title: 'Last 24 hours', ms: 86_400_000 },
  { value: '7d', label: '7d', title: 'Last 7 days', ms: 7 * 86_400_000 },
  { value: '30d', label: '30d', title: 'Last 30 days', ms: 30 * 86_400_000 },
  { value: 'all', label: 'All', title: 'All time', ms: null },
]

export function rangeStart(range: TimeRange, now = Date.now()): string | undefined {
  const ms = TIME_RANGES.find(item => item.value === range)?.ms
  return ms ? new Date(now - ms).toISOString() : undefined
}

export function isFailed(trace: { status?: string | null; error_type?: string | null }): boolean {
  return trace.status === 'failed'
}

export function traceDuration(trace: TraceSummary): number {
  return numeric(trace.duration_ms ?? trace.max_latency_ms)
}

export function percentile(values: number[], p: number): number {
  if (!values.length)
    return 0
  const sorted = [...values].sort((a, b) => a - b)
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1))
  return sorted[index]
}

export interface SeriesPoint {
  start: number
  label: string
  runs: number
  errors: number
  ok: number
  cost: number
  tokens: number
  p95: number
  avg: number
}

/**
 * Bucket traces into a fixed number of time slots covering the selected range (or, for
 * "all", the span of the data), so charts keep a stable x-axis as data arrives.
 */
export function buildSeries(traces: TraceSummary[], range: TimeRange, now = Date.now()): SeriesPoint[] {
  const times = traces.map(trace => Date.parse(trace.started_at)).filter(Number.isFinite)
  const config: Record<TimeRange, { buckets: number; ms: number | null }> = {
    '1h': { buckets: 30, ms: 3600_000 },
    '24h': { buckets: 48, ms: 86_400_000 },
    '7d': { buckets: 42, ms: 7 * 86_400_000 },
    '30d': { buckets: 30, ms: 30 * 86_400_000 },
    all: { buckets: 40, ms: null },
  }
  const { buckets } = config[range]
  let start: number
  let end = now
  if (config[range].ms) {
    start = now - (config[range].ms as number)
  }
  else {
    start = times.length ? Math.min(...times) : now - 86_400_000
    end = Math.max(now, ...times)
    if (end - start < 3600_000)
      start = end - 3600_000
  }
  const size = (end - start) / buckets
  const spanDays = (end - start) / 86_400_000
  const points: Array<SeriesPoint & { durations: number[] }> = Array.from({ length: buckets }, (_, index) => {
    const at = start + index * size
    return { start: at, label: bucketLabel(at, spanDays), runs: 0, errors: 0, ok: 0, cost: 0, tokens: 0, p95: 0, avg: 0, durations: [] }
  })
  for (const trace of traces) {
    const time = Date.parse(trace.started_at)
    if (!Number.isFinite(time) || time < start || time > end)
      continue
    const point = points[Math.min(buckets - 1, Math.floor((time - start) / size))]
    point.runs += 1
    if (isFailed(trace))
      point.errors += 1
    else
      point.ok += 1
    point.cost += numeric(trace.estimated_cost)
    point.tokens += numeric(trace.total_tokens)
    const duration = traceDuration(trace)
    if (duration)
      point.durations.push(duration)
  }
  return points.map(({ durations, ...point }) => ({
    ...point,
    p95: percentile(durations, 95),
    avg: durations.length ? durations.reduce((sum, value) => sum + value, 0) / durations.length : 0,
  }))
}

function bucketLabel(time: number, spanDays: number): string {
  const date = new Date(time)
  if (spanDays <= 1.01)
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (spanDays <= 8)
    return date.toLocaleString([], { weekday: 'short', hour: '2-digit' })
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export interface Issue {
  key: string
  errorType: string
  workflow: string
  message: string
  count: number
  firstSeen: string
  lastSeen: string
  traces: TraceSummary[]
  cost: number
}

/** Sentry-style issue groups: failed traces grouped by error type and workflow. */
export function groupIssues(traces: TraceSummary[]): Issue[] {
  const groups = new Map<string, Issue>()
  for (const trace of traces) {
    if (!isFailed(trace))
      continue
    const errorType = trace.error_type || 'unknown_error'
    const workflow = trace.workflow_name ?? trace.name
    const key = `${errorType}::${workflow}`
    const issue = groups.get(key) ?? { key, errorType, workflow, message: trace.error_message ?? '', count: 0, firstSeen: trace.started_at, lastSeen: trace.started_at, traces: [], cost: 0 }
    issue.count += 1
    issue.traces.push(trace)
    issue.cost += numeric(trace.estimated_cost)
    if (trace.started_at > issue.lastSeen) {
      issue.lastSeen = trace.started_at
      issue.message = trace.error_message ?? issue.message
    }
    if (trace.started_at < issue.firstSeen)
      issue.firstSeen = trace.started_at
    groups.set(key, issue)
  }
  return [...groups.values()].sort((a, b) => b.count - a.count || b.lastSeen.localeCompare(a.lastSeen))
}

export type SpanKind = 'workflow' | 'agent' | 'llm' | 'tool' | 'retrieval' | 'memory' | 'approval' | 'checkpoint' | 'replay' | 'span'

export function spanKind(span: SpanRecord): SpanKind {
  const kind = (span.span_kind ?? '').toLowerCase()
  const type = (span.event_type ?? '').toLowerCase()
  if (kind === 'llm' || kind === 'generation' || kind === 'model' || type.startsWith('model') || (span.model && !span.tool_name))
    return 'llm'
  if (kind === 'tool' || type.startsWith('tool') || span.tool_name)
    return 'tool'
  if (kind === 'retriever' || kind === 'retrieval' || type.includes('rag') || type.includes('retriev') || (span.rag_document_ids?.length ?? 0) > 0)
    return 'retrieval'
  if (type.includes('memory') || span.memory_operation)
    return 'memory'
  if (type.includes('approval'))
    return 'approval'
  if (type.includes('checkpoint'))
    return 'checkpoint'
  if (type.includes('replay'))
    return 'replay'
  if (kind === 'agent' || type.startsWith('agent'))
    return 'agent'
  if (kind === 'workflow' || kind === 'chain' || type.startsWith('workflow'))
    return 'workflow'
  return 'span'
}

export function spanLabel(span: SpanRecord): string {
  const kind = spanKind(span)
  if (span.name && !/^(workflow|agent|model|tool)\.(started|finished|call|response|requested)$/.test(span.name))
    return span.name
  if (kind === 'llm' && span.model)
    return span.model
  if (kind === 'tool' && span.tool_name)
    return span.tool_name
  if (kind === 'agent' && span.agent_name)
    return span.agent_name
  if (kind === 'workflow' && span.workflow_name)
    return span.workflow_name
  return span.name ?? span.event_type
}

/**
 * The span to show first: the root cause of a failure when insights found one, otherwise the
 * deepest failed span, otherwise the first span that did real work (an LLM or tool call).
 */
export function defaultSpan(spans: SpanRecord[], rootCauseSpanId?: string | null): SpanRecord | null {
  if (!spans.length)
    return null
  const rootCause = rootCauseSpanId ? spans.find(span => span.span_id === rootCauseSpanId) : undefined
  if (rootCause)
    return rootCause
  const failed = spans.filter(span => span.status === 'failed')
  const leafFailure = failed.find(span => !failed.some(other => other.parent_span_id === span.span_id))
  if (leafFailure)
    return leafFailure
  return spans.find(span => numeric(span.duration_ms) > 0 && ['llm', 'tool', 'retrieval'].includes(spanKind(span))) ?? spans[0]
}

export interface SpanRow {
  span: SpanRecord
  depth: number
  childCount: number
  start: number
  end: number
}

/** Depth-first span order with depth, like the rows of a Jaeger or Datadog waterfall. */
export function flattenSpans(spans: SpanRecord[]): { rows: SpanRow[]; min: number; max: number } {
  const ids = new Set(spans.map(span => span.span_id))
  const children = new Map<string | null, SpanRecord[]>()
  for (const span of spans) {
    const parent = span.parent_span_id && ids.has(span.parent_span_id) ? span.parent_span_id : null
    children.set(parent, [...(children.get(parent) ?? []), span])
  }
  const startOf = (span: SpanRecord) => Date.parse(span.started_at)
  for (const list of children.values())
    list.sort((a, b) => (startOf(a) || 0) - (startOf(b) || 0))
  const rows: SpanRow[] = []
  const seen = new Set<string>()
  const visit = (span: SpanRecord, depth: number) => {
    if (seen.has(span.span_id))
      return
    seen.add(span.span_id)
    const start = startOf(span)
    const ended = span.ended_at ? Date.parse(span.ended_at) : Number.NaN
    // Some runtimes record an instant event with a separate duration, so take whichever is longer.
    const end = Math.max(Number.isFinite(ended) ? ended : start, start + numeric(span.duration_ms))
    const kids = children.get(span.span_id) ?? []
    rows.push({ span, depth, childCount: kids.length, start, end })
    kids.forEach(child => visit(child, depth + 1))
  }
  ;(children.get(null) ?? []).forEach(span => visit(span, 0))
  spans.forEach(span => visit(span, 0))
  const starts = rows.map(row => row.start).filter(Number.isFinite)
  const ends = rows.map(row => row.end).filter(Number.isFinite)
  const min = starts.length ? Math.min(...starts) : 0
  const max = ends.length ? Math.max(...ends, min + 1) : 1
  return { rows, min, max }
}
