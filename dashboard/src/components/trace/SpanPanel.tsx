import { AlertOctagon, RotateCcw } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { SpanRecord, TraceDetail } from '../../types'
import { findFirstPayload, formatDateTime, formatMoney, formatMs, formatNumber, numeric } from '../../utils/format'
import { spanKind, spanLabel } from '../../utils/traces'
import { Badge, CostStatusBadge, StatusBadge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card, EmptyState, KeyValue } from '../ui/Card'
import { CopyableId, JsonViewer } from '../ui/Code'
import { Tabs } from '../ui/Tabs'
import { ContentView } from './ContentView'
import { KIND_META, SpanKindIcon } from './SpanKindIcon'

type Tab = 'overview' | 'input' | 'output' | 'model' | 'tool' | 'retrieval' | 'memory' | 'error' | 'raw'

/** Runtime events carry content inside their payload; take the content field, never the whole payload. */
function payloadField(payload: unknown, keys: string[]): unknown {
  if (!payload || typeof payload !== 'object')
    return null
  const record = payload as Record<string, unknown>
  const key = keys.find(name => record[name] !== undefined && record[name] !== null)
  return key ? record[key] : null
}

export function SpanPanel({ detail, span, onReplay }: { detail: TraceDetail; span: SpanRecord | null; onReplay: (traceId: string, spanId?: string) => void }) {
  const [tab, setTab] = useState<Tab>('overview')
  const traceId = detail.trace?.trace_id

  const related = useMemo(() => {
    if (!span)
      return null
    // Runtime traces record a call and its response as parent and child spans, so an LLM or tool
    // span may own its record through a child. Other spans (agents, workflows) never borrow one.
    const kind = spanKind(span)
    const direct = <T extends { span_id: string; parent_span_id?: string | null }>(items: T[], owner: 'llm' | 'tool') => {
      const exact = items.filter(item => item.span_id === span.span_id)
      return exact.length || kind !== owner ? exact : items.filter(item => item.parent_span_id === span.span_id)
    }
    return {
      modelCalls: direct(detail.model_calls, 'llm'),
      toolCalls: direct(detail.tool_calls, 'tool'),
      retrievals: detail.rag_retrievals.filter(item => item.span_id === span.span_id),
      memory: detail.memory_operations.filter(item => item.span_id === span.span_id),
      prompts: detail.prompt_versions.filter(item => item.prompt_id === span.prompt_version),
    }
  }, [detail, span])

  const failed = Boolean(span && (span.status === 'failed' || span.error_message))

  if (!span || !related)
    return <Card title="Span"><EmptyState title="Select a span" detail="Pick a row in the timeline to see its input, output, tokens, and errors." /></Card>

  const kind = spanKind(span)
  const model = related.modelCalls[0]
  const tool = related.toolCalls[0]
  const input = span.input ?? model?.prompt ?? tool?.input ?? (related.prompts[0] ? [{ role: 'system', content: related.prompts[0].system_prompt ?? '' }, { role: 'user', content: related.prompts[0].user_prompt }].filter(message => message.content) : null) ?? payloadField(findFirstPayload(detail.events, span.span_id, ['started', 'call', 'requested']), ['input', 'messages', 'prompt', 'arguments', 'args'])
  const output = span.output ?? model?.output ?? tool?.output ?? payloadField(findFirstPayload(detail.events, span.span_id, ['finished', 'response', 'succeeded', 'completed']), ['output', 'result', 'response', 'answer'])
  const tokens = numeric(span.total_tokens) || numeric(model?.total_tokens)
  const cost = numeric(span.estimated_cost) || numeric(model?.estimated_cost)

  const tabs: Array<{ value: Tab; label: string; count?: number }> = [
    { value: 'overview', label: 'Overview' },
    { value: 'input', label: 'Input' },
    { value: 'output', label: 'Output' },
    ...(related.modelCalls.length ? [{ value: 'model' as const, label: 'Model', count: related.modelCalls.length > 1 ? related.modelCalls.length : undefined }] : []),
    ...(related.toolCalls.length ? [{ value: 'tool' as const, label: 'Tool' }] : []),
    ...(related.retrievals.length ? [{ value: 'retrieval' as const, label: 'Retrieval', count: related.retrievals.length }] : []),
    ...(related.memory.length ? [{ value: 'memory' as const, label: 'Memory', count: related.memory.length }] : []),
    ...(failed ? [{ value: 'error' as const, label: 'Error' }] : []),
    { value: 'raw', label: 'Raw' },
  ]
  const activeTab = tabs.some(item => item.value === tab) ? tab : 'overview'

  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-line bg-surface shadow-card">
      <header className="flex flex-col gap-2 px-4 pt-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <SpanKindIcon kind={kind} failed={failed} className="size-7 rounded-md [&_svg]:size-4" />
            <div className="min-w-0">
              <h2 className="truncate text-[14.5px] font-semibold text-fg" title={spanLabel(span)}>{spanLabel(span)}</h2>
              <div className="flex min-w-0 items-center gap-2 text-xs text-fg-subtle">
                <span>{KIND_META[kind].label}</span>
                <span>·</span>
                <CopyableId value={span.span_id} />
              </div>
            </div>
          </div>
          {!/\.(started|call)$/.test(span.event_type) || failed ? <StatusBadge status={span.status} /> : null}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {numeric(span.duration_ms) > 0 && <Badge outline>{formatMs(span.duration_ms)}</Badge>}
          {tokens > 0 && <Badge outline>{formatNumber(tokens)} tokens</Badge>}
          {cost > 0 && <Badge tone="warning">{formatMoney(cost)}</Badge>}
          {(span.model ?? model?.model) && <Badge tone="violet">{span.model ?? model?.model}</Badge>}
          {(span.tool_name ?? tool?.tool_name) && <Badge tone="warning">{span.tool_name ?? tool?.tool_name}</Badge>}
          {(span.retry_count ?? 0) > 0 && <Badge tone="warning">{span.retry_count} retries</Badge>}
        </div>
      </header>
      <Tabs className="mt-3 px-2" value={activeTab} onChange={setTab} items={tabs} />
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {activeTab === 'overview' && (
          <div className="flex flex-col gap-4">
            {failed && (
              <div className="flex gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2.5 text-[13px] text-danger-text">
                <AlertOctagon className="mt-0.5 size-4 shrink-0" />
                <div className="min-w-0">
                  <div className="font-medium">{span.error_type ?? 'Error'}</div>
                  {span.error_message && <div className="break-words text-fg-muted">{span.error_message}</div>}
                </div>
              </div>
            )}
            <KeyValue rows={[
              ['Event', <span className="font-mono text-xs">{span.event_type}</span>],
              ['Agent', span.agent_name],
              ['Task', span.task_name ?? span.task_id],
              ['Provider', span.provider ?? model?.provider],
              ['Model', span.model ?? model?.model],
              ['Tool', span.tool_name ?? tool?.tool_name],
              ['Started', formatDateTime(span.started_at)],
              ['Duration', numeric(span.duration_ms) > 0 ? formatMs(span.duration_ms) : null],
              ['Parent', span.parent_span_id ? <CopyableId value={span.parent_span_id} /> : null],
            ]} />
            {(tokens > 0 || cost > 0) && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  ['Input', numeric(span.prompt_tokens) || numeric(model?.prompt_tokens)],
                  ['Output', numeric(span.completion_tokens) || numeric(model?.completion_tokens)],
                  ['Cached', numeric(span.cached_tokens) || numeric(model?.cached_tokens)],
                  ['Reasoning', numeric(span.reasoning_tokens) || numeric(model?.reasoning_tokens)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg border border-line bg-surface-2/50 px-2.5 py-2">
                    <div className="text-[11px] text-fg-subtle">{label} tokens</div>
                    <div className="tabular text-[13px] font-semibold text-fg">{formatNumber(value)}</div>
                  </div>
                ))}
              </div>
            )}
            {model && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
                <CostStatusBadge status={model.cost_status} />
                {model.temperature != null && <Badge outline>temperature {model.temperature}</Badge>}
                {model.max_tokens != null && <Badge outline>max_tokens {model.max_tokens}</Badge>}
                {model.context_window != null && <Badge outline>context {formatNumber(model.context_window)}</Badge>}
              </div>
            )}
            {traceId && (
              <Button icon={<RotateCcw />} onClick={() => onReplay(traceId, span.span_id)}>Replay from this span</Button>
            )}
          </div>
        )}
        {activeTab === 'input' && <ContentView value={input} emptyTitle="No input captured" label="Input" />}
        {activeTab === 'output' && <ContentView value={output} emptyTitle="No output captured" label="Output" />}
        {activeTab === 'model' && <JsonViewer value={related.modelCalls.length === 1 ? related.modelCalls[0] : related.modelCalls} label="Model call" />}
        {activeTab === 'tool' && (
          <div className="flex flex-col gap-3">
            {tool?.stderr && <ContentView value={tool.stderr} />}
            <JsonViewer value={related.toolCalls.length === 1 ? related.toolCalls[0] : related.toolCalls} label="Tool call" />
          </div>
        )}
        {activeTab === 'retrieval' && (
          <div className="flex flex-col gap-3">
            {related.retrievals.map(retrieval => (
              <div key={retrieval.retrieval_id} className="flex flex-col gap-2 rounded-lg border border-line p-3">
                <div className="text-[13px] font-medium text-fg">{retrieval.query ?? 'Retrieval'}</div>
                <div className="flex flex-wrap gap-1.5">
                  {retrieval.vector_store && <Badge outline>{retrieval.vector_store}</Badge>}
                  {retrieval.embedding_model && <Badge outline>{retrieval.embedding_model}</Badge>}
                  <Badge tone={retrieval.used_in_answer ? 'success' : 'neutral'}>{retrieval.used_in_answer ? 'used in answer' : 'not used'}</Badge>
                  <Badge outline>{retrieval.chunk_ids.length} chunks</Badge>
                </div>
                {retrieval.chunk_preview && <ContentView value={retrieval.chunk_preview} />}
                <JsonViewer value={retrieval.retrieved_documents} label="Documents" maxHeight="max-h-64" />
              </div>
            ))}
          </div>
        )}
        {activeTab === 'memory' && <JsonViewer value={related.memory} label="Memory operations" />}
        {activeTab === 'error' && <JsonViewer value={{ error_type: span.error_type, error_message: span.error_message, diagnosis: detail.diagnosis }} label="Error" />}
        {activeTab === 'raw' && <JsonViewer value={span} label="Span" />}
      </div>
    </section>
  )
}
