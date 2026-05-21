import { FileJson, Route } from 'lucide-react'
import type { CompareResult, JsonRecord, ModelCallRecord, SpanRecord, ToolCallRecord, TraceDetail as TraceDetailData, TraceSummary } from '../types'
import { FilterField } from '../components/common/Inputs'
import { EmptyState, Panel } from '../components/common/Cards'
import { TracesTable } from '../components/trace/TracesTable'
import { TraceDetail } from '../components/trace/TraceDetail'

export function TraceExplorerPage({
  traces,
  detail,
  selectedTraceId,
  selectedSpan,
  filters,
  modelCalls,
  toolCalls,
  compareResult,
  onFilters,
  onSelectTrace,
  onSelectSpan,
  onExport,
  onReplay,
  onCompare,
  onValidate,
}: {
  traces: TraceSummary[]
  detail: TraceDetailData | null
  selectedTraceId: string
  selectedSpan: SpanRecord | null
  filters: JsonRecord
  modelCalls: ModelCallRecord[]
  toolCalls: ToolCallRecord[]
  compareResult: CompareResult | null
  onFilters: (filters: JsonRecord) => void
  onSelectTrace: (traceId: string) => void
  onSelectSpan: (span: SpanRecord) => void
  onExport: (traceId: string, format?: 'json' | 'otel-json') => void
  onReplay: (traceId: string, spanId?: string) => void
  onCompare: (traceId: string) => void
  onValidate: (traceId: string) => void
}) {
  const traceIndex = (
    <Panel
      title="Trace Explorer"
      icon={<Route className="size-4" />}
      actions={<div className="grid grid-cols-3 gap-2"><FilterField label="Agent" value={String(filters.agent ?? '')} onChange={value => onFilters({ ...filters, agent: value })} /><FilterField label="Tool" value={String(filters.tool ?? '')} onChange={value => onFilters({ ...filters, tool: value })} /><FilterField label="Error type" value={String(filters.error_type ?? '')} onChange={value => onFilters({ ...filters, error_type: value })} /></div>}
    >
      <TracesTable traces={traces} modelCalls={modelCalls} toolCalls={toolCalls} selectedTraceId={selectedTraceId} onOpen={onSelectTrace} onReplay={onReplay} onExport={onExport} onCompare={onCompare} />
    </Panel>
  )

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {detail?.trace ? (
        <>
          <TraceDetail detail={detail} selectedSpan={selectedSpan} onSelectSpan={onSelectSpan} onExport={onExport} onReplay={onReplay} onCompare={onCompare} onValidate={onValidate} compareResult={compareResult} />
          {traceIndex}
        </>
      ) : (
        <>
          {traceIndex}
          <Panel title="Trace Detail" icon={<FileJson className="size-4" />}>
            <EmptyState icon={<Route className="size-5" />} title="Select a trace to inspect span tree, waterfall, prompts, tools, memory, RAG, cost, and replay controls" />
          </Panel>
        </>
      )}
    </div>
  )
}
