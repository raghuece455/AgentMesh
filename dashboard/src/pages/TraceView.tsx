import { ArrowLeft, ChevronDown, ChevronLeft, ChevronRight, Download, GitCompare, ListTree, MessagesSquare, MoreHorizontal, RotateCcw, ScrollText, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { AddToDataset } from '../components/trace/AddToDataset'
import { InsightsCard } from '../components/trace/InsightsCard'
import { SpanPanel } from '../components/trace/SpanPanel'
import { TraceCompare } from '../components/trace/TraceCompare'
import { TraceTimeline } from '../components/trace/TraceTimeline'
import { Badge, StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Callout, Card, Skeleton } from '../components/ui/Card'
import { CopyableId } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Menu } from '../components/ui/Overlay'
import { StatStrip } from '../components/ui/Stat'
import { Tabs } from '../components/ui/Tabs'
import { useShortcuts } from '../lib/shortcuts'
import type { SpanRecord, TraceDetail, TraceSummary } from '../types'
import { formatDateTime, formatMoney, formatMs, formatNumber, numeric } from '../utils/format'
import { flattenSpans, spanKind } from '../utils/traces'

export function TraceView({
  detail,
  loading,
  selectedSpan,
  candidates,
  position,
  onSelectSpan,
  onClose,
  onPrev,
  onNext,
  onExport,
  onReplay,
  onOpenTrace,
  onValidate,
  onOpenSession,
  onNotify,
}: {
  detail: TraceDetail | null
  loading: boolean
  selectedSpan: SpanRecord | null
  /** Traces offered in the Compare picker. */
  candidates: TraceSummary[]
  position: { index: number; total: number } | null
  onSelectSpan: (span: SpanRecord) => void
  onClose: () => void
  onPrev?: () => void
  onNext?: () => void
  onExport: (traceId: string, format?: 'json' | 'otel-json') => void
  onReplay: (traceId: string, spanId?: string) => void
  onOpenTrace: (traceId: string) => void
  onValidate: (traceId: string) => void
  onOpenSession: (sessionId: string) => void
  onNotify: (message: string, tone?: 'neutral' | 'danger' | 'success') => void
}) {
  const [tab, setTab] = useState<'timeline' | 'events'>('timeline')
  const [comparing, setComparing] = useState(false)
  const trace = detail?.trace
  const spans = useMemo(() => detail?.spans ?? [], [detail])
  const order = useMemo(() => flattenSpans(spans).rows.map(row => row.span), [spans])
  const counts = useMemo(() => ({
    llm: spans.filter(span => spanKind(span) === 'llm' && !/\.call$/.test(span.event_type)).length,
    tool: spans.filter(span => spanKind(span) === 'tool').length,
    failed: spans.filter(span => span.status === 'failed').length,
  }), [spans])

  const stepSpan = (offset: number) => {
    if (!order.length)
      return
    const index = order.findIndex(span => span.span_id === selectedSpan?.span_id)
    const next = index < 0 ? 0 : Math.min(Math.max(index + offset, 0), order.length - 1)
    setTab('timeline')
    onSelectSpan(order[next])
  }
  useShortcuts({
    j: () => stepSpan(1),
    k: () => stepSpan(-1),
    ArrowDown: () => stepSpan(1),
    ArrowUp: () => stepSpan(-1),
    '[': () => onPrev?.(),
    ']': () => onNext?.(),
    Escape: onClose,
    c: () => setComparing(true),
  }, Boolean(trace))

  if (!trace) {
    return (
      <div className="flex flex-col gap-4">
        <Button variant="ghost" className="self-start" icon={<ArrowLeft />} onClick={onClose}>Traces</Button>
        {loading
          ? (
              <>
                <Skeleton className="h-10 w-80" />
                <Skeleton className="h-16 rounded-xl" />
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_440px]"><Skeleton className="h-96 rounded-xl" /><Skeleton className="h-96 rounded-xl" /></div>
              </>
            )
          : <Callout tone="warning" title="Trace not found">It may have been deleted, or the link points at another AgentMesh server.</Callout>}
      </div>
    )
  }

  const promptTokens = numeric(detail?.costs?.prompt_tokens)
  const completionTokens = numeric(detail?.costs?.completion_tokens)
  const events = detail?.events ?? []
  const traceStart = Date.parse(trace.started_at)

  return (
    <>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" size="sm" icon={<ArrowLeft />} onClick={onClose}>All traces</Button>
          {position && (
            <div className="flex items-center gap-1 text-xs text-fg-subtle">
              <span className="tabular mr-1">{position.index + 1} of {position.total}</span>
              <Button variant="secondary" size="icon-sm" aria-label="Previous trace" title="Previous trace ([)" disabled={!onPrev} onClick={onPrev}><ChevronLeft /></Button>
              <Button variant="secondary" size="icon-sm" aria-label="Next trace" title="Next trace (])" disabled={!onNext} onClick={onNext}><ChevronRight /></Button>
            </div>
          )}
        </div>
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2.5">
              <h1 className="truncate text-xl font-semibold tracking-tight text-fg">{trace.workflow_name ?? trace.name}</h1>
              <StatusBadge status={trace.status} />
              {trace.is_demo && <Badge outline>demo</Badge>}
              {trace.source && trace.source !== 'runtime' && <Badge tone="accent">{trace.source}{trace.service_name ? ` · ${trace.service_name}` : ''}</Badge>}
              {(trace.tags ?? []).map(tag => <Badge key={tag} outline>#{tag}</Badge>)}
            </div>
            <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-fg-muted">
              <CopyableId value={trace.trace_id} full />
              <span>{formatDateTime(trace.started_at)}</span>
              {trace.session_id && (
                <button className="inline-flex items-center gap-1 text-accent-text hover:underline" onClick={() => onOpenSession(trace.session_id!)}>
                  <MessagesSquare className="size-3.5" />{trace.session_id}
                </button>
              )}
              {trace.user_id && <span>user <span className="text-fg">{trace.user_id}</span></span>}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <AddToDataset traceId={trace.trace_id} onDone={message => onNotify(message, 'success')} />
            <Button icon={<GitCompare />} onClick={() => setComparing(true)}>Compare</Button>
            <Menu
              trigger={({ toggle }) => <Button icon={<Download />} onClick={toggle}>Export<ChevronDown /></Button>}
              items={[
                { label: 'AgentMesh JSON', icon: <Download />, onSelect: () => onExport(trace.trace_id) },
                { label: 'OpenTelemetry JSON', icon: <Download />, onSelect: () => onExport(trace.trace_id, 'otel-json'), hint: 'OTLP' },
              ]}
            />
            <Menu
              trigger={({ toggle }) => <Button size="icon" aria-label="More actions" onClick={toggle}><MoreHorizontal /></Button>}
              items={[{ label: 'Copy validation command', icon: <ShieldCheck />, onSelect: () => onValidate(trace.trace_id) }]}
            />
            <Button variant="primary" icon={<RotateCcw />} onClick={() => onReplay(trace.trace_id)}>Replay</Button>
          </div>
        </div>
      </div>

      {trace.status === 'failed' && (trace.error_message || trace.error_type) && (
        <Callout tone="danger" title={trace.error_type ?? 'Trace failed'}>{trace.error_message}</Callout>
      )}

      <StatStrip items={[
        { label: 'Duration', value: formatMs(trace.duration_ms ?? trace.max_latency_ms) },
        { label: 'Spans', value: formatNumber(trace.span_count ?? spans.length) },
        { label: 'LLM calls', value: formatNumber(detail?.model_calls.length ?? counts.llm) },
        { label: 'Tool calls', value: formatNumber(detail?.tool_calls.length ?? counts.tool) },
        { label: 'Tokens', value: <span title={`${formatNumber(promptTokens)} in / ${formatNumber(completionTokens)} out`}>{formatNumber(trace.total_tokens)}</span> },
        { label: 'Cost', value: numeric(trace.estimated_cost) ? formatMoney(trace.estimated_cost) : '-' },
        { label: 'Failed spans', value: formatNumber(counts.failed), tone: counts.failed ? 'danger' : undefined },
      ]} />

      <InsightsCard key={trace.trace_id} traceId={trace.trace_id} insights={detail?.insights} scores={detail?.scores ?? []} spans={spans} onSelectSpan={onSelectSpan} />

      {detail && <TraceCompare open={comparing} onClose={() => setComparing(false)} detail={detail} candidates={candidates} onOpenTrace={onOpenTrace} />}

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
        <Card flush bodyClassName="flex flex-col">
          <div className="flex items-center justify-between gap-2 px-2">
            <Tabs
              className="flex-1 border-b-0"
              value={tab}
              onChange={setTab}
              items={[
                { value: 'timeline', label: 'Timeline', icon: <ListTree />, count: spans.length },
                { value: 'events', label: 'Events', icon: <ScrollText />, count: events.length },
              ]}
            />
          </div>
          <div className="border-t border-line">
            {tab === 'timeline'
              ? <TraceTimeline spans={spans} selectedId={selectedSpan?.span_id} onSelect={onSelectSpan} />
              : (
                  <DataTable
                    rows={events}
                    maxHeight="max-h-[70vh]"
                    minWidth={560}
                    rowKey={row => row.event_id}
                    onRow={row => {
                      const span = spans.find(item => item.span_id === row.span_id)
                      if (span)
                        onSelectSpan(span)
                    }}
                    selectedRow={row => row.span_id === selectedSpan?.span_id}
                    columns={[
                      { label: 'Offset', align: 'right', width: '90px', sortValue: row => Date.parse(row.timestamp), render: row => <span className="text-fg-muted">+{formatMs(Math.max(Date.parse(row.timestamp) - traceStart, 0))}</span> },
                      { label: 'Event', sortValue: row => row.event_type, render: row => <span className={row.event_type.includes('fail') || row.event_type.includes('error') ? 'font-mono text-xs text-danger-text' : 'font-mono text-xs text-fg'}>{row.event_type}</span> },
                      { label: 'Actor', sortValue: row => row.actor, render: row => <span className="text-fg-muted">{row.actor}</span> },
                      { label: 'Span', render: row => <CopyableId value={row.span_id} /> },
                    ]}
                  />
                )}
          </div>
        </Card>
        <div className="xl:sticky xl:top-20">
          {detail && <SpanPanel detail={detail} span={selectedSpan} onReplay={onReplay} />}
        </div>
      </div>
    </>
  )
}
