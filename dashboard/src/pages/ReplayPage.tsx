import { ArrowUpRight, Play, RotateCcw, ShieldOff } from 'lucide-react'
import { useState } from 'react'
import { Badge, StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, KeyValue, PageHeader } from '../components/ui/Card'
import { CopyableId, JsonViewer } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Field, Select } from '../components/ui/Field'
import { StatStrip } from '../components/ui/Stat'
import type { Checkpoint, ReplayRun, SpanRecord, TraceSummary } from '../types'
import { formatDateTime, formatRelative, shortId } from '../utils/format'

export function ReplayPage({ checkpoints, replay, traces, trace, selectedSpan, onReplay, onTrace }: { checkpoints: Checkpoint[]; replay: ReplayRun | null; traces: TraceSummary[]; trace: TraceSummary | null; selectedSpan: SpanRecord | null; onReplay: (traceId: string, spanId?: string) => void; onTrace: (traceId: string) => void }) {
  const [picked, setTraceId] = useState('')
  const traceId = picked || replay?.source_trace_id || trace?.trace_id || traces[0]?.trace_id || ''
  const source = traces.find(item => item.trace_id === traceId) ?? trace
  const spanForSource = selectedSpan && selectedSpan.trace_id === traceId ? selectedSpan : null
  const result = (replay?.result ?? {}) as { mode?: string; semantics?: string; outputs?: unknown[]; tool_calls?: unknown[]; prompts?: unknown[]; agent_interactions?: unknown[]; checkpoints?: unknown[] }
  const mode = replay?.mode ?? result.mode

  return (
    <>
      <PageHeader title="Replay" description="Re-run a trace from its recorded model and tool outputs, to reproduce a bug without calling providers or touching the outside world." />
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card title="Replay a trace" className="xl:sticky xl:top-20">
          <div className="flex flex-col gap-4">
            <Field label="Source trace">
              <Select className="w-full" value={traceId} onChange={event => setTraceId(event.target.value)}>
                {traces.map(item => <option key={item.trace_id} value={item.trace_id}>{item.workflow_name ?? item.name} · {shortId(item.trace_id)} · {item.status}</option>)}
              </Select>
            </Field>
            {source && (
              <KeyValue rows={[
                ['Status', <StatusBadge status={source.status} />],
                ['Started', formatRelative(source.started_at)],
                ['Selected span', spanForSource ? <CopyableId value={spanForSource.span_id} /> : <span className="text-fg-subtle">none (open the trace to pick one)</span>],
                ['Mode', 'deterministic'],
              ]} />
            )}
            <div className="flex items-start gap-2 rounded-lg border border-line bg-surface-2/60 px-3 py-2.5 text-xs text-fg-muted">
              <ShieldOff className="mt-0.5 size-3.5 shrink-0 text-success" />
              Side effects are disabled. Model and tool calls return what was recorded.
            </div>
            <div className="flex flex-col gap-2">
              <Button variant="primary" icon={<Play />} disabled={!traceId} onClick={() => onReplay(traceId)}>Replay full trace</Button>
              {spanForSource && <Button icon={<RotateCcw />} onClick={() => onReplay(traceId, spanForSource.span_id)}>Replay from selected span</Button>}
              {source && <Button variant="ghost" onClick={() => onTrace(source.trace_id)}>Open source trace<ArrowUpRight /></Button>}
            </div>
          </div>
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          {replay
            ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-base font-semibold text-fg">Replay result</h2>
                    <StatusBadge status={replay.status === 'completed' ? 'succeeded' : replay.status} label={replay.status.charAt(0).toUpperCase() + replay.status.slice(1)} />
                    {mode && <Badge outline>{mode}</Badge>}
                    <CopyableId value={replay.replay_id} />
                  </div>
                  <StatStrip items={[
                    { label: 'Model outputs', value: result.outputs?.length ?? 0 },
                    { label: 'Tool calls', value: result.tool_calls?.length ?? 0 },
                    { label: 'Prompts', value: result.prompts?.length ?? 0 },
                    { label: 'Agent events', value: result.agent_interactions?.length ?? 0 },
                    { label: 'Checkpoints', value: result.checkpoints?.length ?? 0 },
                  ]} />
                  {result.semantics && <p className="text-[13px] text-fg-muted">{result.semantics}</p>}
                  <JsonViewer value={replay} label="Replay" />
                </>
              )
            : <Card><EmptyState icon={<RotateCcw />} title="No replay yet" detail="Pick a trace and run a replay, or use Replay on any trace or span." /></Card>}

          <Card flush title="Checkpoints" description="Saved state you can resume from">
            <DataTable
              rows={checkpoints}
              rowKey={row => row.checkpoint_id}
              minWidth={600}
              onRow={row => setTraceId(row.trace_id)}
              selectedRow={row => row.trace_id === traceId}
              empty={<EmptyState title="No checkpoints" />}
              columns={[
                { label: 'Type', sortValue: row => row.checkpoint_type, render: row => <Badge tone={row.checkpoint_type.includes('fail') ? 'danger' : 'neutral'}>{row.checkpoint_type}</Badge> },
                { label: 'Step', sortValue: row => row.step_id ?? '', render: row => <span className="font-mono text-xs text-fg">{row.step_id ?? 'workflow'}</span> },
                { label: 'Trace', render: row => <CopyableId value={row.trace_id} /> },
                { label: 'Created', align: 'right', sortValue: row => Date.parse(row.created_at), render: row => <span className="text-fg-muted" title={formatDateTime(row.created_at)}>{formatRelative(row.created_at)}</span> },
              ]}
            />
          </Card>
        </div>
      </div>
    </>
  )
}
