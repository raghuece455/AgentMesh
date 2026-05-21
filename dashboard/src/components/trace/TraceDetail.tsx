import { Activity, Download, FileJson, GitBranch, ListTree, RotateCcw, ShieldCheck, TimerReset } from 'lucide-react'
import type { CompareResult, SpanRecord, TraceDetail as TraceDetailData } from '../../types'
import { formatCost, formatMs, formatNumber, formatTime, numeric, traceCostStatus } from '../../utils/format'
import { ActionButton } from '../common/Actions'
import { CopyableId, CostStatusBadge, EnvironmentBadge, ProviderBadge, StatusBadge } from '../common/Badges'
import { AnswerCard, EmptyState, Panel } from '../common/Cards'
import { DataTable } from '../tables/DataTable'
import { SpanTree } from './SpanTree'
import { TraceInspector } from './TraceInspector'
import { WaterfallTimeline } from './WaterfallTimeline'

export function TraceDetail({
  detail,
  selectedSpan,
  onSelectSpan,
  onExport,
  onReplay,
  onCompare,
  onValidate,
  compareResult,
}: {
  detail: TraceDetailData | null
  selectedSpan: SpanRecord | null
  onSelectSpan: (span: SpanRecord) => void
  onExport: (traceId: string, format?: 'json' | 'otel-json') => void
  onReplay: (traceId: string, spanId?: string) => void
  onCompare: (traceId: string) => void
  onValidate: (traceId: string) => void
  compareResult: CompareResult | null
}) {
  const trace = detail?.trace
  const spans = detail?.spans ?? []
  if (!trace)
    return <Panel title="Trace Detail" icon={<FileJson className="size-4" />}><EmptyState title="Select a trace to inspect it" /></Panel>

  const provider = detail?.model_calls[0]?.provider ?? '-'
  const model = detail?.model_calls[0]?.model ?? '-'
  const slowest = [...spans].sort((a, b) => numeric(b.duration_ms) - numeric(a.duration_ms))[0]
  const expensive = [...spans].sort((a, b) => numeric(b.estimated_cost) - numeric(a.estimated_cost))[0]
  const failed = spans.find(span => span.status === 'failed' || span.error_message)
  const costStatus = traceCostStatus(trace, detail?.model_calls ?? [])

  return (
    <div className="flex flex-col gap-4">
      <Panel title="Trace Detail" icon={<Activity className="size-4" />}>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-xl/7 font-semibold text-white">{trace.workflow_name ?? trace.name}</h2>
              <StatusBadge status={trace.status} />
              <EnvironmentBadge trace={trace} />
              <CostStatusBadge status={costStatus} />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs/5 text-white/58">
              <CopyableId value={trace.trace_id} />
              <span>Started {formatTime(trace.started_at)}</span>
              <span>Duration {formatMs(trace.duration_ms ?? trace.max_latency_ms)}</span>
              <ProviderBadge provider={provider} model={model} />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <ActionButton icon={<RotateCcw className="size-4" />} label="Replay" tone="purple" onClick={() => onReplay(trace.trace_id)} />
            <ActionButton icon={<Download className="size-4" />} label="Export JSON" onClick={() => onExport(trace.trace_id)} />
            <ActionButton icon={<Download className="size-4" />} label="Export OTEL JSON" onClick={() => onExport(trace.trace_id, 'otel-json')} />
            <ActionButton icon={<GitBranch className="size-4" />} label="Compare" onClick={() => onCompare(trace.trace_id)} />
            <ActionButton icon={<ShieldCheck className="size-4" />} label="Validate" onClick={() => onValidate(trace.trace_id)} />
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-6">
          <AnswerCard label="Cost" value={formatCost(trace.estimated_cost, costStatus)} />
          <AnswerCard label="Tokens" value={formatNumber(trace.total_tokens)} />
          <AnswerCard label="Spans" value={formatNumber(trace.span_count)} />
          <AnswerCard label="Slowest" value={slowest ? `${slowest.event_type} / ${formatMs(slowest.duration_ms)}` : 'n/a'} />
          <AnswerCard label="Expensive" value={expensive ? `${expensive.event_type} / ${formatCost(expensive.estimated_cost, costStatus)}` : 'n/a'} />
          <AnswerCard label="Failure" value={failed ? `${failed.agent_name ?? 'workflow'} / ${failed.error_type ?? failed.event_type}` : 'none'} tone={failed ? 'danger' : 'good'} />
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[320px_minmax(0,1fr)_420px]">
        <Panel title="Span Tree" icon={<ListTree className="size-4" />}>
          <SpanTree spans={spans} selected={selectedSpan?.span_id ?? ''} onSelect={onSelectSpan} />
        </Panel>
        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="Waterfall Timeline" icon={<TimerReset className="size-4" />}>
            <WaterfallTimeline spans={spans} onSelect={onSelectSpan} />
          </Panel>
          <Panel title="Execution Events" icon={<FileJson className="size-4" />}>
            <DataTable
              rows={(detail?.events ?? []).slice(0, 120)}
              minWidth={820}
              columns={[
                { label: 'Time', render: row => formatTime(row.timestamp), sortValue: row => Date.parse(row.timestamp) },
                { label: 'Event', render: row => row.event_type, sortValue: row => row.event_type },
                { label: 'Actor', render: row => row.actor, sortValue: row => row.actor },
                { label: 'Span', render: row => <CopyableId value={row.span_id} />, sortValue: row => row.span_id },
              ]}
            />
          </Panel>
          {compareResult && (
            <Panel title="Run Comparison" icon={<GitBranch className="size-4" />}>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <AnswerCard label="Original events" value={compareResult.left_event_count} />
                <AnswerCard label="Compared events" value={compareResult.right_event_count} />
                <AnswerCard label="Event type parity" value={compareResult.event_types_match ? 'matching' : 'changed'} tone={compareResult.event_types_match ? 'good' : 'warn'} />
              </div>
            </Panel>
          )}
        </div>
        <TraceInspector detail={detail} span={selectedSpan} onReplay={onReplay} />
      </div>
    </div>
  )
}
