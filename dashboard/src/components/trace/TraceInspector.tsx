import { Copy, FileJson, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import type { PromptVersion, SpanRecord, TraceDetail, TraceEvent } from '../../types'
import { findFirstPayload, formatMoney, formatMs, formatNumber, formatTime } from '../../utils/format'
import { ActionButton } from '../common/Actions'
import { CopyableId, StatusBadge } from '../common/Badges'
import { EmptyState, Panel } from '../common/Cards'
import { JsonViewer } from '../common/JsonViewer'

const inspectorTabs = ['summary', 'input', 'output', 'prompt', 'model', 'tools', 'memory', 'rag', 'cost', 'error', 'raw']

export function TraceInspector({ detail, span, onReplay }: { detail: TraceDetail | null; span: SpanRecord | null; onReplay: (traceId: string, spanId?: string) => void }) {
  const [tab, setTab] = useState('summary')
  const traceId = detail?.trace?.trace_id
  const modelCalls = detail?.model_calls.filter(call => !span || call.span_id === span.span_id || call.parent_span_id === span.span_id) ?? []
  const toolCalls = detail?.tool_calls.filter(call => !span || call.span_id === span.span_id || call.parent_span_id === span.span_id) ?? []
  const memoryOps = detail?.memory_operations.filter(item => !span || item.span_id === span.span_id) ?? []
  const retrievals = detail?.rag_retrievals.filter(item => !span || item.span_id === span.span_id) ?? []
  const prompts = detail?.prompt_versions.filter(item => !span || item.prompt_id === span.prompt_version || item.task_id === span.task_id) ?? []
  return (
    <Panel title="Inspector" icon={<FileJson className="size-4" />}>
      {span ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-sm/6 font-semibold text-white">{span.event_type}</div>
              <CopyableId value={span.span_id} />
            </div>
            <StatusBadge status={span.status} />
          </div>
          <div className="vision-scroll flex gap-1 overflow-auto rounded-2xl border border-white/10 bg-slate-950/28 p-1">
            {inspectorTabs.map(item => (
              <button key={item} className={`shrink-0 rounded-xl px-2.5 py-1.5 text-xs/5 font-semibold capitalize ${tab === item ? 'bg-white/18 text-white' : 'text-white/58 hover:bg-white/10 hover:text-white'}`} onClick={() => setTab(item)}>
                {item === 'rag' ? 'RAG' : item}
              </button>
            ))}
          </div>
          <InspectorTabContent
            tab={tab}
            span={span}
            detail={detail}
            events={detail?.events}
            modelCalls={modelCalls}
            toolCalls={toolCalls}
            memoryOps={memoryOps}
            retrievals={retrievals}
            prompts={prompts}
          />
          {traceId && <ActionButton icon={<RotateCcw className="size-4" />} label="Replay from this span" tone="purple" onClick={() => onReplay(traceId, span.span_id)} />}
        </div>
      ) : <EmptyState icon={<FileJson className="size-5" />} title="Select a span" detail="Inspect inputs, outputs, prompts, tools, memory, RAG, costs, errors, and raw JSON." />}
    </Panel>
  )
}

function InspectorTabContent({
  tab,
  span,
  detail,
  events,
  modelCalls,
  toolCalls,
  memoryOps,
  retrievals,
  prompts,
}: {
  tab: string
  span: SpanRecord
  detail: TraceDetail | null
  events?: TraceEvent[]
  modelCalls: unknown[]
  toolCalls: unknown[]
  memoryOps: unknown[]
  retrievals: unknown[]
  prompts: PromptVersion[]
}) {
  if (tab === 'summary')
    return (
      <KeyValueGrid rows={[
        ['Agent', span.agent_name],
        ['Task', span.task_name ?? span.task_id],
        ['Event', span.event_type],
        ['Status', <StatusBadge status={span.status} />],
        ['Duration', formatMs(span.duration_ms)],
        ['Started', formatTime(span.started_at)],
        ['Ended', formatTime(span.ended_at)],
        ['Retry count', span.retry_count ?? 0],
      ]} />
    )
  if (tab === 'input')
    return <TabJson value={span.input ?? findFirstPayload(events, span.span_id, ['started', 'call', 'requested'])} emptyTitle="No input captured for this span" />
  if (tab === 'output')
    return <TabJson value={span.output ?? findFirstPayload(events, span.span_id, ['finished', 'response', 'succeeded'])} emptyTitle="No output captured for this span" />
  if (tab === 'prompt')
    return prompts.length ? <PromptTab prompts={prompts} /> : <EmptyState title="No prompt linked to this span" />
  if (tab === 'model')
    return <TabJson value={modelCalls.length ? modelCalls : { provider: span.provider, model: span.model, tokens: span.total_tokens }} emptyTitle="No model call linked to this span" />
  if (tab === 'tools')
    return <TabJson value={toolCalls.length ? toolCalls : { tool_name: span.tool_name }} emptyTitle="No tool call linked to this span" />
  if (tab === 'memory')
    return <TabJson value={memoryOps.length ? memoryOps : { operation: span.memory_operation }} emptyTitle="No memory operation linked to this span" />
  if (tab === 'rag')
    return <TabJson value={retrievals.length ? retrievals : { rag_document_ids: span.rag_document_ids ?? [] }} emptyTitle="No RAG retrieval linked to this span" />
  if (tab === 'cost')
    return (
      <KeyValueGrid rows={[
        ['Estimated cost', formatMoney(span.estimated_cost)],
        ['Prompt tokens', formatNumber(span.prompt_tokens)],
        ['Completion tokens', formatNumber(span.completion_tokens)],
        ['Cached tokens', formatNumber(span.cached_tokens)],
        ['Reasoning tokens', formatNumber(span.reasoning_tokens)],
        ['Total tokens', formatNumber(span.total_tokens)],
      ]} />
    )
  if (tab === 'error')
    return <TabJson value={{ error_type: span.error_type, error_message: span.error_message, diagnosis: detail?.diagnosis }} emptyTitle="No error recorded for this span" />
  return <JsonViewer value={{ span, model_calls: modelCalls, tool_calls: toolCalls, memory_operations: memoryOps, rag_retrievals: retrievals }} />
}

function TabJson({ value, emptyTitle }: { value: unknown; emptyTitle: string }) {
  if (value === null || value === undefined || (Array.isArray(value) && value.length === 0))
    return <EmptyState title={emptyTitle} />
  return <JsonViewer value={value} />
}

function PromptTab({ prompts }: { prompts: PromptVersion[] }) {
  const text = prompts.map(prompt => `${prompt.system_prompt ?? ''}\n\n${prompt.user_prompt ?? ''}`).join('\n\n---\n\n')
  return (
    <div className="flex flex-col gap-3">
      <button className="inline-flex w-fit items-center gap-1 rounded-xl border border-white/12 bg-black/22 px-2 py-1 text-xs/5 text-white/72 hover:bg-white/12" onClick={() => void navigator.clipboard.writeText(text)}>
        <Copy className="size-3" />Copy prompt
      </button>
      <JsonViewer value={prompts} />
    </div>
  )
}

export function KeyValueGrid({ rows }: { rows: Array<[string, React.ReactNode]> }) {
  return (
    <div className="grid grid-cols-1 gap-2">
      {rows.filter(([, value]) => value !== undefined && value !== null && value !== '').map(([label, value]) => (
        <div key={label} className="grid grid-cols-[120px_1fr] gap-3 rounded-2xl bg-slate-950/24 px-3 py-2">
          <div className="text-xs/5 font-medium text-white/50">{label}</div>
          <div className="min-w-0 break-words text-sm/6 text-white/82">{value}</div>
        </div>
      ))}
    </div>
  )
}
