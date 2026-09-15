import { ArrowUpRight, Wrench } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Badge, StatusBadge, StatusDot } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, KeyValue, Meter, PageHeader } from '../components/ui/Card'
import { JsonViewer } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Drawer } from '../components/ui/Overlay'
import { StatCard } from '../components/ui/Stat'
import { ContentView } from '../components/trace/ContentView'
import type { ToolCallRecord } from '../types'
import { formatDateTime, formatMs, formatNumber, formatPercent, formatRelative, numeric } from '../utils/format'

interface ToolStats {
  name: string
  type: string
  calls: number
  failures: number
  avgMs: number
  risk: string | null
  sideEffects: boolean
  lastUsed: string
}

export function ToolsPage({ toolCalls, onTrace }: { toolCalls: ToolCallRecord[]; onTrace: (traceId: string) => void }) {
  const [selected, setSelected] = useState<ToolCallRecord | null>(null)
  const tools = useMemo<ToolStats[]>(() => {
    const map = new Map<string, ToolStats & { total: number }>()
    for (const call of toolCalls) {
      const stats = map.get(call.tool_name) ?? { name: call.tool_name, type: call.tool_type, calls: 0, failures: 0, avgMs: 0, total: 0, risk: null, sideEffects: false, lastUsed: call.started_at }
      stats.calls += 1
      stats.failures += call.status === 'failed' ? 1 : 0
      stats.total += numeric(call.duration_ms)
      stats.risk = call.risk_level ?? stats.risk
      stats.sideEffects = stats.sideEffects || call.side_effect
      if (call.started_at > stats.lastUsed)
        stats.lastUsed = call.started_at
      map.set(call.tool_name, stats)
    }
    return [...map.values()].map(({ total, ...stats }) => ({ ...stats, avgMs: stats.calls ? total / stats.calls : 0 }))
  }, [toolCalls])
  const failures = toolCalls.filter(call => call.status === 'failed').length
  const risky = toolCalls.filter(call => call.risk_level === 'high' || call.side_effect).length
  const maxCalls = Math.max(...tools.map(tool => tool.calls), 0)

  return (
    <>
      <PageHeader title="Tools" description="Every tool call your agents made, with failures, risk, and side effects." />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Tool calls" icon={<Wrench />} value={formatNumber(toolCalls.length)} sub={`${tools.length} distinct tools`} />
        <StatCard label="Failed calls" value={formatNumber(failures)} tone={failures ? 'danger' : 'neutral'} sub={toolCalls.length ? `${formatPercent(failures / toolCalls.length)} failure rate` : undefined} />
        <StatCard label="Risky or side-effecting" value={formatNumber(risky)} tone={risky ? 'warning' : 'neutral'} sub="High risk or writes to the outside world" />
        <StatCard label="Avg duration" value={formatMs(toolCalls.length ? toolCalls.reduce((sum, call) => sum + numeric(call.duration_ms), 0) / toolCalls.length : 0)} />
      </div>

      <Card flush title="By tool">
        <DataTable
          rows={tools}
          rowKey={row => row.name}
          minWidth={760}
          initialSort={{ column: 1 }}
          empty={<EmptyState icon={<Wrench />} title="No tool calls yet" />}
          columns={[
            { label: 'Tool', sortValue: row => row.name, render: row => <span className="flex items-center gap-2"><span className="font-mono text-[13px] font-medium text-fg">{row.name}</span><Badge outline>{row.type}</Badge></span> },
            { label: 'Calls', width: '180px', sortValue: row => row.calls, render: row => <span className="flex items-center gap-2"><Meter value={row.calls} max={maxCalls} tone="warning" /><span className="tabular w-8 text-right">{row.calls}</span></span> },
            { label: 'Failures', align: 'right', sortValue: row => row.failures, render: row => row.failures ? <span className="font-medium text-danger-text">{row.failures} ({formatPercent(row.failures / row.calls)})</span> : <span className="text-fg-subtle">0</span> },
            { label: 'Avg duration', align: 'right', sortValue: row => row.avgMs, render: row => formatMs(row.avgMs) },
            { label: 'Risk', sortValue: row => row.risk ?? '', render: row => <span className="flex gap-1">{row.risk ? <Badge tone={row.risk === 'high' ? 'danger' : row.risk === 'medium' ? 'warning' : 'neutral'}>{row.risk}</Badge> : <span className="text-fg-subtle">-</span>}{row.sideEffects && <Badge tone="warning">side effects</Badge>}</span> },
            { label: 'Last used', align: 'right', sortValue: row => Date.parse(row.lastUsed), render: row => <span className="text-fg-muted">{formatRelative(row.lastUsed)}</span> },
          ]}
        />
      </Card>

      <Card flush title="Recent calls" description="Click a call for its input, output, and logs">
        <DataTable
          rows={toolCalls.slice(0, 200)}
          rowKey={row => row.tool_call_id}
          minWidth={760}
          onRow={setSelected}
          selectedRow={row => row.tool_call_id === selected?.tool_call_id}
          empty={<EmptyState title="No tool calls yet" />}
          rowClassName={row => row.status === 'failed' ? 'shadow-[inset_2px_0_0_var(--danger)]' : ''}
          columns={[
            { label: 'Tool', sortValue: row => row.tool_name, render: row => <span className="flex items-center gap-2"><StatusDot status={row.status} /><span className="font-mono text-[13px] text-fg">{row.tool_name}</span></span> },
            { label: 'Agent', sortValue: row => row.agent_name ?? '', render: row => <span className="text-fg-muted">{row.agent_name ?? '-'}</span> },
            { label: 'Result', render: row => row.error_message ? <span className="line-clamp-1 max-w-sm text-[13px] text-danger-text">{row.error_message}</span> : <StatusBadge status={row.status} /> },
            { label: 'Duration', align: 'right', sortValue: row => numeric(row.duration_ms), render: row => formatMs(row.duration_ms) },
            { label: 'When', align: 'right', sortValue: row => Date.parse(row.started_at), render: row => <span className="text-fg-muted">{formatRelative(row.started_at)}</span> },
          ]}
        />
      </Card>

      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={<span className="font-mono">{selected?.tool_name}</span>}
        description={selected ? `${selected.agent_name ?? 'unknown agent'} · ${formatDateTime(selected.started_at)}` : undefined}
        width="max-w-2xl"
        footer={selected && <Button variant="primary" icon={<ArrowUpRight />} onClick={() => { const id = selected.trace_id; setSelected(null); onTrace(id) }}>Open trace</Button>}
      >
        {selected && (
          <div className="flex flex-col gap-5">
            <KeyValue rows={[
              ['Status', <StatusBadge status={selected.status} />],
              ['Duration', formatMs(selected.duration_ms)],
              ['Type', selected.tool_type],
              ['Permission', selected.permission_level],
              ['Approval', selected.approval_status],
              ['Risk', selected.risk_level],
              ['Retries', selected.retry_count],
              ['Error', selected.error_message ? <span className="text-danger-text">{selected.error_type ? `${selected.error_type}: ` : ''}{selected.error_message}</span> : null],
            ]} />
            <Section title="Input"><ContentView value={selected.input} emptyTitle="No input captured" label="Input" /></Section>
            <Section title="Output"><ContentView value={selected.output} emptyTitle="No output captured" label="Output" /></Section>
            {(selected.stdout || selected.stderr) && <Section title="Logs"><ContentView value={[selected.stdout, selected.stderr].filter(Boolean).join('\n')} /></Section>}
            {selected.side_effects != null && Array.isArray(selected.side_effects) && selected.side_effects.length > 0 && <Section title="Side effects"><JsonViewer value={selected.side_effects} label="Side effects" maxHeight="max-h-60" /></Section>}
          </div>
        )}
      </Drawer>
    </>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-[13px] font-semibold text-fg">{title}</h3>
      {children}
    </section>
  )
}
