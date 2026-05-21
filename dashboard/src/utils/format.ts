import type { JsonRecord, ModelCallRecord, ToolCallRecord, TraceEvent, TraceSummary } from '../types'

export function numeric(value: unknown): number {
  const number = Number(value ?? 0)
  return Number.isFinite(number) ? number : 0
}

export function formatMoney(value: unknown): string {
  return `$${numeric(value).toFixed(4)}`
}

export function formatCost(value: unknown, status?: string | null): string {
  if (status === 'unknown' || status === 'unavailable')
    return status
  if (status === 'local/free')
    return 'local/free'
  return formatMoney(value)
}

export function formatNumber(value: unknown): string {
  return Math.round(numeric(value)).toLocaleString()
}

export function formatMs(value: unknown): string {
  const number = numeric(value)
  if (!number)
    return '0 ms'
  if (number >= 1000)
    return `${(number / 1000).toFixed(2)} s`
  return `${Math.round(number)} ms`
}

export function formatPercent(value: unknown): string {
  return `${(numeric(value) * 100).toFixed(1)}%`
}

export function formatDecimal(value: unknown): string {
  if (value === null || value === undefined)
    return '-'
  return numeric(value).toFixed(2)
}

export function formatTime(value: string | undefined | null): string {
  if (!value)
    return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime()))
    return value
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function shortId(value: string | undefined | null): string {
  if (!value)
    return '-'
  return value.length > 14 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value
}

export function stringValue(value: unknown): string {
  if (value === null || value === undefined)
    return ''
  return String(value)
}

export function parseFailedEndpoint(message: string): string | null {
  const match = message.match(/(?:GET|POST)\s+(\S+)\s+failed/i)
  return match?.[1] ?? null
}

export function jsonPreview(value: unknown): string {
  try {
    const text = JSON.stringify(value)
    return text.length > 160 ? `${text.slice(0, 160)}...` : text
  }
  catch {
    return String(value)
  }
}

export function findFirstPayload(events: TraceEvent[] | undefined, spanId: string, terms: string[]): unknown {
  return events?.find(event => event.span_id === spanId && terms.some(term => event.event_type.includes(term)))?.payload ?? null
}

export function scopeFromFilters(filters: JsonRecord): string {
  const isDemo = stringValue(filters.is_demo).toLowerCase()
  if (isDemo === 'true' || isDemo === '1' || isDemo === 'demo')
    return 'demo'
  if (isDemo === 'false' || isDemo === '0')
    return 'real'
  return 'all'
}

export function traceModelCalls(trace: TraceSummary, calls: ModelCallRecord[]): ModelCallRecord[] {
  return calls.filter(call => call.trace_id === trace.trace_id)
}

export function traceToolCalls(trace: TraceSummary, calls: ToolCallRecord[]): ToolCallRecord[] {
  return calls.filter(call => call.trace_id === trace.trace_id)
}

export function traceProvider(trace: TraceSummary, calls: ModelCallRecord[]): string {
  return trace.provider ?? traceModelCalls(trace, calls)[0]?.provider ?? '-'
}

export function traceModel(trace: TraceSummary, calls: ModelCallRecord[]): string {
  return trace.model ?? traceModelCalls(trace, calls)[0]?.model ?? '-'
}

export function traceCostStatus(trace: TraceSummary, calls: ModelCallRecord[]): string {
  return trace.cost_status ?? traceModelCalls(trace, calls).find(call => call.cost_status)?.cost_status ?? 'unknown'
}
