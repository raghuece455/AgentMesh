import { ArrowUpRight, Bot } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, StatusDot } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, KeyValue, Meter, PageHeader } from '../components/ui/Card'
import { DataTable } from '../components/ui/DataTable'
import { SearchInput } from '../components/ui/Field'
import { Drawer } from '../components/ui/Overlay'
import { StatStrip } from '../components/ui/Stat'
import type { AgentSummary, ModelCallRecord, ToolCallRecord, TraceSummary } from '../types'
import { formatCompact, formatMoney, formatMs, formatNumber, formatPercent, formatRelative, numeric } from '../utils/format'

export function AgentsPage({ agents, traces, modelCalls, toolCalls, onTrace }: { agents: AgentSummary[]; traces: TraceSummary[]; modelCalls: ModelCallRecord[]; toolCalls: ToolCallRecord[]; onTrace: (traceId: string) => void }) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<AgentSummary | null>(null)
  const filtered = agents.filter(agent => `${agent.agent_name} ${agent.role ?? ''} ${agent.model ?? ''}`.toLowerCase().includes(query.trim().toLowerCase()))
  const maxCost = Math.max(...agents.map(agent => numeric(agent.total_cost)), 0)

  const agentTraces = useMemo(() => {
    if (!selected)
      return []
    const ids = new Set([...modelCalls, ...toolCalls].filter(call => call.agent_name === selected.agent_name).map(call => call.trace_id))
    return traces.filter(trace => ids.has(trace.trace_id))
  }, [selected, modelCalls, toolCalls, traces])
  const agentModels = useMemo(() => selected ? [...new Set(modelCalls.filter(call => call.agent_name === selected.agent_name).map(call => call.model).filter(Boolean))] : [], [selected, modelCalls])
  const agentTools = useMemo(() => selected ? [...new Set(toolCalls.filter(call => call.agent_name === selected.agent_name).map(call => call.tool_name))] : [], [selected, toolCalls])

  return (
    <>
      <PageHeader title="Agents" description={`${agents.length} agents seen in traces. Click one for its runs, models, and tools.`} actions={<SearchInput className="w-64" value={query} onChange={setQuery} placeholder="Filter agents" />} />

      {agents.length === 0
        ? <Card><EmptyState icon={<Bot />} title="No agents yet" detail="Agents appear once traces include agent spans (gen_ai.agent.name or the SDK's agent context)." /></Card>
        : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {filtered.map(agent => (
                <button key={agent.agent_id} className="group flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 text-left shadow-card transition-colors hover:border-line-strong" onClick={() => setSelected(agent)}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent-text"><Bot className="size-4.5" /></span>
                      <div className="min-w-0">
                        <div className="truncate text-[14px] font-semibold text-fg">{agent.agent_name}</div>
                        <div className="truncate text-xs text-fg-subtle">{agent.role ?? 'No role set'}{agent.model ? ` · ${agent.model}` : ''}</div>
                      </div>
                    </div>
                    <ArrowUpRight className="size-4 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                  <div className="grid grid-cols-4 gap-2 text-xs">
                    <Stat label="LLM calls" value={formatNumber(agent.model_calls)} />
                    <Stat label="Tokens" value={formatCompact(agent.total_tokens)} />
                    <Stat label="Latency" value={formatMs(agent.avg_latency_ms)} />
                    <Stat label="Cost" value={numeric(agent.total_cost) ? formatMoney(agent.total_cost) : '-'} />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-fg-subtle">Success rate</span>
                      <span className={agent.success_rate < 0.9 ? 'tabular font-medium text-warning-text' : 'tabular font-medium text-fg'}>{formatPercent(agent.success_rate)}</span>
                    </div>
                    <Meter value={agent.success_rate} max={1} tone={agent.success_rate < 0.7 ? 'danger' : agent.success_rate < 0.9 ? 'warning' : 'success'} />
                  </div>
                  {maxCost > 0 && (
                    <div className="flex items-center gap-2 text-xs text-fg-subtle">
                      <span className="w-16 shrink-0">Cost share</span>
                      <Meter value={numeric(agent.total_cost)} max={maxCost} />
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}

      <Drawer open={Boolean(selected)} onClose={() => setSelected(null)} title={selected?.agent_name ?? ''} description={selected?.role ?? undefined} width="max-w-2xl">
        {selected && (
          <div className="flex flex-col gap-5">
            <StatStrip items={[
              { label: 'LLM calls', value: formatNumber(selected.model_calls) },
              { label: 'Tokens', value: formatCompact(selected.total_tokens) },
              { label: 'Cost', value: numeric(selected.total_cost) ? formatMoney(selected.total_cost) : '-' },
              { label: 'Success', value: formatPercent(selected.success_rate), tone: selected.success_rate < 0.9 ? 'warning' : undefined },
            ]} />
            <KeyValue rows={[
              ['Status', <span className="inline-flex items-center gap-1.5"><StatusDot status={selected.status} />{selected.status}</span>],
              ['Provider', selected.provider],
              ['Models', agentModels.length ? <span className="flex flex-wrap gap-1">{agentModels.map(model => <Badge key={model} tone="violet">{model}</Badge>)}</span> : selected.model],
              ['Tools', agentTools.length ? <span className="flex flex-wrap gap-1">{agentTools.map(tool => <Badge key={tool} tone="warning">{tool}</Badge>)}</span> : `${selected.tools_available} available`],
              ['Memory', selected.memory_permissions.join(', ')],
              ['Current task', selected.current_task],
            ]} />
            <div>
              <h3 className="mb-2 text-[13px] font-semibold text-fg">Recent traces</h3>
              <Card flush>
                <DataTable
                  rows={agentTraces.slice(0, 30)}
                  rowKey={row => row.trace_id}
                  minWidth={480}
                  onRow={row => { setSelected(null); onTrace(row.trace_id) }}
                  empty={<EmptyState title="No traces in the current time range" />}
                  columns={[
                    { label: 'Trace', render: row => <span className="flex items-center gap-2"><StatusDot status={row.status} /><span className="font-medium text-fg">{row.workflow_name ?? row.name}</span></span> },
                    { label: 'Duration', align: 'right', render: row => formatMs(row.duration_ms) },
                    { label: 'Started', align: 'right', render: row => <span className="text-fg-muted">{formatRelative(row.started_at)}</span> },
                  ]}
                />
              </Card>
            </div>
            {agentTraces[0] && <Button className="self-start" icon={<ArrowUpRight />} onClick={() => { const id = agentTraces[0].trace_id; setSelected(null); onTrace(id) }}>Open latest trace</Button>}
          </div>
        )}
      </Drawer>
    </>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-fg-subtle">{label}</div>
      <div className="tabular truncate text-[13px] font-medium text-fg">{value}</div>
    </div>
  )
}
