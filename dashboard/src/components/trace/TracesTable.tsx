import { Download, GitBranch, RotateCcw, Route } from 'lucide-react'
import type { ModelCallRecord, ToolCallRecord, TraceSummary } from '../../types'
import {
  formatCost,
  formatMs,
  formatNumber,
  formatTime,
  numeric,
  shortId,
  traceCostStatus,
  traceModel,
  traceModelCalls,
  traceProvider,
  traceToolCalls,
} from '../../utils/format'
import { InlineAction } from '../common/Actions'
import { CopyableId, CostStatusBadge, EnvironmentBadge, ProviderBadge, StatusBadge } from '../common/Badges'
import { EmptyState } from '../common/Cards'

export function TracesTable({
  traces,
  modelCalls,
  toolCalls,
  selectedTraceId,
  onOpen,
  onReplay,
  onExport,
  onCompare,
}: {
  traces: TraceSummary[]
  modelCalls: ModelCallRecord[]
  toolCalls: ToolCallRecord[]
  selectedTraceId?: string
  onOpen: (traceId: string) => void
  onReplay: (traceId: string) => void
  onExport: (traceId: string) => void
  onCompare: (traceId: string) => void
}) {
  if (traces.length === 0)
    return <EmptyState title="No records" />

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-3 px-3 text-xs/5 font-semibold text-white/58">
        <span>Workflow / Trace ID</span>
        <span>Provider / Model</span>
        <span>Cost / Duration</span>
        <span>Actions</span>
      </div>
      {traces.map(trace => {
        const calls = traceModelCalls(trace, modelCalls)
        const provider = traceProvider(trace, modelCalls)
        const model = traceModel(trace, modelCalls)
        const costStatus = traceCostStatus(trace, modelCalls)
        const selected = trace.trace_id === selectedTraceId
        return (
          <div
            key={trace.trace_id}
            role="button"
            tabIndex={0}
            className={`group flex w-full cursor-pointer flex-wrap gap-3 rounded-2xl border p-3 text-left transition focus:outline-none focus:ring-2 focus:ring-sky-200/45 ${selected ? 'border-sky-200/48 bg-sky-400/18 shadow-[0_0_0_1px_rgb(125_211_252/0.22)]' : 'border-white/10 bg-slate-950/42 hover:border-sky-200/34 hover:bg-sky-400/12'}`}
            title="Open trace detail"
            onClick={() => onOpen(trace.trace_id)}
            onKeyDown={event => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onOpen(trace.trace_id)
              }
            }}
          >
            <div className="flex min-w-64 flex-[2_1_280px] items-start gap-2">
              <InlineAction label="Open" icon={<Route className="size-3.5" />} onClick={() => onOpen(trace.trace_id)} />
              <div className="min-w-0">
                <div className="truncate text-sm/6 font-semibold text-white" title={trace.workflow_name ?? trace.name}>{trace.workflow_name ?? trace.name}</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2">
                  <CopyableId value={trace.trace_id} label={shortId(trace.trace_id)} />
                  <StatusBadge status={trace.status} />
                  <EnvironmentBadge trace={trace} />
                </div>
                <div className="mt-1 text-xs/5 text-white/54">Started {formatTime(trace.started_at)}</div>
              </div>
            </div>

            <div className="min-w-40 flex-[1_1_160px] rounded-xl border border-white/8 bg-black/16 px-3 py-2">
              <ProviderBadge provider={provider} model={model} />
              <div className="mt-1 grid grid-cols-2 gap-x-2 text-xs/5 text-white/58">
                <span>{formatNumber(trace.span_count)} spans</span>
                <span>{calls.length} LLM</span>
                <span>{traceToolCalls(trace, toolCalls).length} tools</span>
                <span>{formatNumber(trace.total_tokens ?? calls.reduce((sum, call) => sum + numeric(call.total_tokens), 0))} tok</span>
              </div>
            </div>

            <div className="min-w-36 flex-[1_1_150px] rounded-xl border border-white/8 bg-black/16 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm/6 font-semibold text-white">{formatCost(trace.estimated_cost, costStatus)}</span>
                <CostStatusBadge status={costStatus} />
              </div>
              <div className="mt-1 text-xs/5 text-white/58">Duration {formatMs(trace.duration_ms ?? trace.max_latency_ms)}</div>
            </div>

            <div className="flex min-w-48 flex-[1_1_210px] flex-wrap items-center justify-start gap-1.5">
              <InlineAction label="Replay" icon={<RotateCcw className="size-3.5" />} onClick={() => onReplay(trace.trace_id)} tone="purple" />
              <InlineAction label="Export" icon={<Download className="size-3.5" />} onClick={() => onExport(trace.trace_id)} />
              <InlineAction label="Compare" icon={<GitBranch className="size-3.5" />} onClick={() => onCompare(trace.trace_id)} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
