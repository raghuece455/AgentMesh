import { Download, RotateCcw, Route } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ModelCallRecord, ToolCallRecord, TraceSummary } from '../../types'
import { formatCost, formatMs, shortId, traceCostStatus, traceModel, traceProvider, traceToolCalls } from '../../utils/format'
import { InlineAction } from '../common/Actions'
import { Badge, CostStatusBadge } from '../common/Badges'
import { EmptyState } from '../common/Cards'
import { FilterSelect } from '../common/Inputs'

export function FailureInbox({
  traces,
  modelCalls,
  toolCalls,
  onOpen,
  onReplay,
  onExport,
}: {
  traces: TraceSummary[]
  modelCalls: ModelCallRecord[]
  toolCalls: ToolCallRecord[]
  onOpen: (traceId: string) => void
  onReplay: (traceId: string) => void
  onExport: (traceId: string) => void
}) {
  const [groupBy, setGroupBy] = useState('error_type')
  const failures = traces.filter(trace => trace.status === 'failed' || trace.error_type || trace.error_message)
  const groups = useMemo(() => groupFailures(failures, groupBy, modelCalls, toolCalls), [failures, groupBy, modelCalls, toolCalls])
  if (failures.length === 0)
    return <EmptyState title="No failed traces in the current window" />
  return (
    <div className="flex flex-col gap-3">
      <FilterSelect
        label="Group failures by"
        value={groupBy}
        options={[
          ['error_type', 'Error type'],
          ['workflow', 'Workflow'],
          ['provider', 'Provider'],
          ['model', 'Model'],
          ['tool', 'Tool'],
        ]}
        onChange={setGroupBy}
      />
      <div className="vision-scroll max-h-[540px] overflow-auto pr-1">
        {groups.map(group => (
          <div key={group.name} className="mb-3">
            <div className="mb-2 flex items-center justify-between text-xs/5 font-semibold uppercase tracking-wide text-white/48">
              <span>{group.name}</span>
              <span>{group.traces.length}</span>
            </div>
            <div className="flex flex-col gap-2">
              {group.traces.map(trace => {
                const provider = traceProvider(trace, modelCalls)
                const model = traceModel(trace, modelCalls)
                const tools = traceToolCalls(trace, toolCalls)
                const failedTool = tools.find(tool => tool.status === 'failed') ?? tools[0]
                return (
                  <div key={trace.trace_id} className="rounded-2xl border border-rose-200/20 bg-rose-500/10 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm/6 font-semibold text-white">{trace.workflow_name ?? trace.name}</div>
                        <div className="mt-1 text-xs/5 text-white/55">{shortId(trace.trace_id)} / {provider}{model !== '-' ? ` / ${model}` : ''}{failedTool ? ` / ${failedTool.tool_name}` : ''}</div>
                      </div>
                      <Badge tone="danger">{trace.error_type ?? 'failed'}</Badge>
                    </div>
                    <div className="mt-2 line-clamp-2 text-xs/5 text-white/70">{trace.error_message ?? 'Open trace for failure diagnosis.'}</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Badge>{formatMs(trace.duration_ms ?? trace.max_latency_ms)}</Badge>
                      <Badge tone="danger">waste {formatCost(trace.estimated_cost, traceCostStatus(trace, modelCalls))}</Badge>
                      <CostStatusBadge status={traceCostStatus(trace, modelCalls)} />
                      <Badge>retries {tools.reduce((sum, tool) => sum + (tool.retry_count ?? 0), 0)}</Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <InlineAction label="Open Trace" icon={<Route className="size-3.5" />} onClick={() => onOpen(trace.trace_id)} />
                      <InlineAction label="Replay From Failure" icon={<RotateCcw className="size-3.5" />} tone="purple" onClick={() => onReplay(trace.trace_id)} />
                      <InlineAction label="Export" icon={<Download className="size-3.5" />} onClick={() => onExport(trace.trace_id)} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function groupFailures(traces: TraceSummary[], groupBy: string, modelCalls: ModelCallRecord[], toolCalls: ToolCallRecord[]) {
  const map = new Map<string, TraceSummary[]>()
  for (const trace of traces) {
    const tools = traceToolCalls(trace, toolCalls)
    const key = groupBy === 'workflow'
      ? trace.workflow_name ?? trace.name
      : groupBy === 'provider'
        ? traceProvider(trace, modelCalls)
        : groupBy === 'model'
          ? traceModel(trace, modelCalls)
          : groupBy === 'tool'
            ? tools.find(tool => tool.status === 'failed')?.tool_name ?? tools[0]?.tool_name ?? 'no tool'
            : trace.error_type ?? 'unknown_error'
    map.set(key, [...(map.get(key) ?? []), trace])
  }
  return [...map.entries()].map(([name, groupedTraces]) => ({ name, traces: groupedTraces }))
}
