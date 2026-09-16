import { AlertTriangle, ArrowLeft, ArrowUpRight, Bot, CircleDollarSign, GitFork, Info, ListTree, MessagesSquare, Network, OctagonX, ScrollText, Users, Waypoints } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Area, Bar, CartesianGrid, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { createHalt, getSwarm, listSwarms } from '../api'
import { EDGE_STYLE, SwarmGraph } from '../components/swarm/SwarmGraph'
import { Badge, StatusBadge, StatusDot } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Callout, Card, EmptyState, KeyValue, PageHeader, Skeleton } from '../components/ui/Card'
import { axisProps, ChartTooltip, gridProps } from '../components/ui/Chart'
import { CodeBlock, CopyableId } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { SearchInput, TextField } from '../components/ui/Field'
import { Drawer, Toast } from '../components/ui/Overlay'
import { StatCard, StatStrip } from '../components/ui/Stat'
import { Segmented, Tabs } from '../components/ui/Tabs'
import { cn } from '../lib/utils'
import type { SwarmDetail, SwarmNode, SwarmSummaryRow } from '../types'
import { errorText, formatDateTime, formatMoney, formatMs, formatNumber, formatRelative, formatTime, jsonPreview } from '../utils/format'

/** Above this many agents the graph starts grouped by role; one card per agent stops being readable. */
const ROLE_VIEW_THRESHOLD = 120
const MAX_AGENT_GRAPH = 600
const MAX_TABLE_ROWS = 500

const SETUP = `import agentmesh

with agentmesh.swarm("market research"):
    with agentmesh.trace("orchestrator"):
        context = agentmesh.swarm_context()   # send with each task
        queue.publish(tasks, context=context)

# in each worker process
with agentmesh.trace("worker", spawned_by=task.context):
    researcher(task)                           # @agentmesh.observe(kind="agent")
    agentmesh.send_message("writer", notes)`

export function SwarmsPage({ refreshKey, range, selectedId, onSelect, onTrace }: {
  refreshKey: string | null
  range: string
  selectedId: string
  onSelect: (swarmId: string) => void
  onTrace: (traceId: string, spanId?: string) => void
}) {
  return selectedId
    ? <SwarmView key={selectedId} swarmId={selectedId} refreshKey={refreshKey} onBack={() => onSelect('')} onTrace={onTrace} />
    : <SwarmList refreshKey={refreshKey} range={range} onSelect={onSelect} />
}

const RANGE_HOURS: Record<string, number | undefined> = { '1h': 1, '24h': 24, '7d': 24 * 7, '30d': 24 * 30, all: undefined }

function SwarmList({ refreshKey, range, onSelect }: { refreshKey: string | null; range: string; onSelect: (swarmId: string) => void }) {
  const [rows, setRows] = useState<SwarmSummaryRow[] | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const hours = RANGE_HOURS[range]

  useEffect(() => {
    let cancelled = false
    listSwarms({ q: query.trim() || undefined, hours, limit: 100 })
      .then((result) => { if (!cancelled) { setRows(result); setError('') } })
      .catch((caught) => { if (!cancelled) setError(errorText(caught)) })
    return () => { cancelled = true }
  }, [refreshKey, query, hours])

  const totals = useMemo(() => (rows ?? []).reduce((sum, row) => ({
    agents: sum.agents + row.agents,
    failed: sum.failed + row.failed_agents,
    running: sum.running + (row.status === 'running' ? 1 : 0),
    cost: sum.cost + row.cost,
  }), { agents: 0, failed: 0, running: 0, cost: 0 }), [rows])

  return (
    <>
      <PageHeader title="Swarms" description="Many agents working as one run, across traces and processes: who started whom, who talked to whom, what failed, and what it cost." />
      {error && <Callout tone="danger" title="Could not load swarms">{error}</Callout>}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Swarms" icon={<Network />} value={rows ? formatNumber(rows.length) : '-'} sub={totals.running ? `${totals.running} running now` : 'None running'} />
        <StatCard label="Agents" icon={<Bot />} value={formatNumber(totals.agents)} sub="Across these swarms" />
        <StatCard label="Failed agents" icon={<AlertTriangle />} value={formatNumber(totals.failed)} tone={totals.failed ? 'danger' : 'neutral'} sub={totals.agents ? `${((totals.failed / totals.agents) * 100).toFixed(1)}% of agents` : ' '} />
        <StatCard label="Spend" icon={<CircleDollarSign />} value={formatMoney(totals.cost)} sub="LLM cost of these swarms" />
      </div>
      <Card
        flush
        title="Swarm runs"
        actions={<SearchInput value={query} onChange={setQuery} placeholder="Name, id, or service" className="w-56" />}
      >
        {rows === null && !error
          ? <div className="flex flex-col gap-2 p-4">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-9" />)}</div>
          : rows?.length === 0 && !query
            ? (
                <div className="flex flex-col gap-4 p-4">
                  <EmptyState icon={<Network />} title="No swarms yet" detail="Group agents into a swarm to see them as one run, even when they run in different processes. OpenTelemetry apps can set the agentmesh.swarm.id resource attribute instead." />
                  <CodeBlock code={SETUP} language="python" />
                </div>
              )
            : (
                <DataTable
                  rows={rows ?? []}
                  rowKey={row => row.swarm_id}
                  minWidth={940}
                  onRow={row => onSelect(row.swarm_id)}
                  rowClassName={row => row.failed_agents ? 'shadow-[inset_2px_0_0_var(--danger)]' : ''}
                  empty={<EmptyState title="No matching swarms" />}
                  columns={[
                    { label: 'Status', width: '110px', sortValue: row => row.status, render: row => <StatusBadge status={row.status} /> },
                    {
                      label: 'Swarm',
                      sortValue: row => row.name,
                      render: row => (
                        <span className="flex min-w-0 flex-col">
                          <span className="flex items-center gap-1.5"><span className="truncate font-medium text-fg">{row.name}</span>{row.is_demo && <Badge outline>demo</Badge>}</span>
                          <span className="truncate font-mono text-[11px] text-fg-subtle">{row.service_name ? `${row.service_name} · ` : ''}{row.swarm_id}</span>
                        </span>
                      ),
                    },
                    { label: 'Agents', align: 'right', sortValue: row => row.agents, render: row => <span className="tabular text-fg">{formatNumber(row.agents)}</span> },
                    { label: 'Failed', align: 'right', sortValue: row => row.failed_agents, render: row => <span className={cn('tabular', row.failed_agents ? 'font-medium text-danger-text' : 'text-fg-subtle')}>{formatNumber(row.failed_agents)}</span> },
                    { label: 'Traces', align: 'right', sortValue: row => row.traces, render: row => <span className="tabular text-fg-muted">{formatNumber(row.traces)}</span> },
                    { label: 'Calls', align: 'right', sortValue: row => row.llm_calls + row.tool_calls, render: row => <span className="tabular text-fg-muted" title={`${row.llm_calls} LLM, ${row.tool_calls} tool`}>{formatNumber(row.llm_calls + row.tool_calls)}</span> },
                    { label: 'Cost', align: 'right', sortValue: row => row.cost, render: row => <span className="tabular text-fg">{row.cost ? formatMoney(row.cost) : '-'}</span> },
                    { label: 'Duration', align: 'right', sortValue: row => row.duration_ms ?? 0, render: row => <span className="tabular text-fg-muted">{formatMs(row.duration_ms)}</span> },
                    { label: 'Last activity', align: 'right', sortValue: row => Date.parse(row.last_seen_at) || 0, render: row => <span className="whitespace-nowrap text-fg-muted" title={formatDateTime(row.last_seen_at)}>{formatRelative(row.last_seen_at)}</span> },
                  ]}
                />
              )}
      </Card>
    </>
  )
}

function SwarmView({ swarmId, refreshKey, onBack, onTrace }: { swarmId: string; refreshKey: string | null; onBack: () => void; onTrace: (traceId: string, spanId?: string) => void }) {
  const [detail, setDetail] = useState<SwarmDetail | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'graph' | 'agents' | 'messages' | 'traces'>('graph')
  const [view, setView] = useState<'agents' | 'roles' | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [stopping, setStopping] = useState(false)
  const [notice, setNotice] = useState<{ message: string; tone?: 'neutral' | 'danger' | 'success' }>({ message: '' })
  const clearNotice = useCallback(() => setNotice({ message: '' }), [])

  useEffect(() => {
    let cancelled = false
    getSwarm(swarmId)
      .then((result) => { if (!cancelled) { setDetail(result); setError('') } })
      .catch((caught) => { if (!cancelled) setError(errorText(caught)) })
    return () => { cancelled = true }
  }, [swarmId, refreshKey])

  const graphView = view ?? (detail && detail.summary.agents > ROLE_VIEW_THRESHOLD ? 'roles' : 'agents')
  const nodesByKey = useMemo(() => new Map((detail?.nodes ?? []).map(node => [node.key, node])), [detail])
  const selectNode = useCallback((id: string) => setSelected(current => current === id ? null : id), [])
  const agents = useMemo(() => {
    const term = query.trim().toLowerCase()
    const nodes = detail?.nodes ?? []
    return term ? nodes.filter(node => `${node.name} ${node.status} ${node.error_message ?? ''} ${node.tools.join(' ')}`.toLowerCase().includes(term)) : nodes
  }, [detail, query])

  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <Button variant="ghost" className="self-start" icon={<ArrowLeft />} onClick={onBack}>Swarms</Button>
        <Callout tone="warning" title="Swarm not found">{error}</Callout>
      </div>
    )
  }
  if (!detail) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-16 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    )
  }

  const summary = detail.summary
  const tooManyForAgentGraph = detail.nodes.length > MAX_AGENT_GRAPH
  const selectedNode = selected ? nodesByKey.get(selected) : undefined
  const selectedRole = graphView === 'roles' && selected ? detail.roles.nodes.find(role => role.name === selected) : undefined
  const chart = detail.timeline.map(bucket => ({ ...bucket, label: formatTime(bucket.at) }))

  return (
    <>
      <div className="flex flex-col gap-3">
        <Button variant="ghost" size="sm" className="self-start" icon={<ArrowLeft />} onClick={onBack}>All swarms</Button>
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2.5">
              <h1 className="truncate text-xl font-semibold tracking-tight text-fg">{detail.name}</h1>
              <StatusBadge status={summary.status} />
              {detail.is_demo && <Badge outline>demo</Badge>}
              {detail.service_name && <Badge tone="accent">{detail.service_name}</Badge>}
              {detail.environment && <Badge outline>{detail.environment}</Badge>}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-fg-muted">
              <CopyableId value={detail.swarm_id} full />
              <span>{formatDateTime(summary.started_at)}</span>
            </div>
          </div>
          <Button variant="danger" icon={<OctagonX />} onClick={() => setStopping(true)}>Stop swarm</Button>
        </div>
      </div>
      <Toast message={notice.message} tone={notice.tone} onDone={clearNotice} />
      <StopSwarmDrawer open={stopping} detail={detail} onClose={() => setStopping(false)} onStopped={() => { setStopping(false); setNotice({ message: `Stopped ${detail.name}. Agents in it fail their next call until the halt is released on Guardrails.`, tone: 'success' }) }} />

      {(summary.truncated || summary.nodes_truncated) && (
        <Callout tone="warning" title="This swarm is larger than one view shows">Only the first {formatNumber(summary.spans)} spans are analyzed. Totals below cover those spans.</Callout>
      )}

      <StatStrip items={[
        { label: 'Agents', value: formatNumber(summary.agents) },
        { label: 'Roles', value: formatNumber(summary.roles) },
        { label: 'Traces', value: formatNumber(summary.traces) },
        { label: 'Max depth', value: formatNumber(summary.max_depth) },
        { label: 'Max fan-out', value: formatNumber(summary.max_fan_out) },
        { label: 'LLM calls', value: formatNumber(summary.llm_calls) },
        { label: 'Tool calls', value: formatNumber(summary.tool_calls) },
        { label: 'Cost', value: summary.cost ? formatMoney(summary.cost) : '-' },
        { label: 'Failed agents', value: formatNumber(summary.failed_agents), tone: summary.failed_agents ? 'danger' : undefined },
        { label: 'Duration', value: formatMs(summary.duration_ms) },
      ]} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        <Card title="Activity" description="Agents running and started over the swarm's lifetime" icon={<Waypoints />}>
          {chart.length === 0
            ? <EmptyState title="No timing data" />
            : (
                <div className="h-44">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={chart} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                      <defs>
                        <linearGradient id="swarm-active" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid {...gridProps} />
                      <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={48} />
                      <YAxis {...axisProps} allowDecimals={false} width={44} />
                      <Tooltip content={<ChartTooltip />} />
                      <Area type="stepAfter" dataKey="active" name="Running" stroke="var(--chart-1)" strokeWidth={1.5} fill="url(#swarm-active)" />
                      <Bar dataKey="started" name="Started" fill="var(--chart-2)" maxBarSize={10} />
                      <Bar dataKey="failed" name="Failed" fill="var(--danger)" maxBarSize={10} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}
        </Card>
        <Card title="Insights" icon={<Info />} flush>
          {detail.insights.length === 0
            ? <EmptyState title="Nothing unusual" detail="No failed agents, runaway fan-out, deep nesting, or cost hotspots." />
            : (
                <ul className="divide-y divide-line">
                  {detail.insights.map(insight => (
                    <li key={insight.kind}>
                      <button
                        className="flex w-full items-start gap-2.5 px-4 py-3 text-left hover:bg-surface-2/60 disabled:cursor-default disabled:hover:bg-transparent"
                        disabled={!insight.node_key}
                        onClick={() => {
                          if (!insight.node_key)
                            return
                          // Too many agents to draw one by one: show the agent in the table instead.
                          if (tooManyForAgentGraph) { setTab('agents'); setQuery('') }
                          else { setTab('graph'); setView('agents') }
                          setSelected(insight.node_key)
                        }}
                      >
                        <span className={cn('mt-0.5 [&_svg]:size-4', insight.severity === 'danger' ? 'text-danger-text' : insight.severity === 'warning' ? 'text-warning-text' : 'text-info-text')}>
                          {insight.severity === 'info' ? <Info /> : <AlertTriangle />}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[13px] font-medium text-fg">{insight.title}</span>
                          <span className="mt-0.5 line-clamp-2 block text-xs text-fg-muted">{insight.detail}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
        </Card>
      </div>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        <Card flush bodyClassName="flex flex-col">
          <div className="flex flex-wrap items-center justify-between gap-2 pr-3 pl-2">
            <Tabs
              className="flex-1 border-b-0"
              value={tab}
              onChange={setTab}
              items={[
                { value: 'graph', label: 'Graph', icon: <Network /> },
                { value: 'agents', label: 'Agents', icon: <Users />, count: summary.agents },
                { value: 'messages', label: 'Messages', icon: <MessagesSquare />, count: summary.messages + summary.handoffs },
                { value: 'traces', label: 'Traces', icon: <ListTree />, count: summary.traces },
              ]}
            />
            {tab === 'graph' && (
              <Segmented
                size="sm"
                value={graphView}
                onChange={(value) => { setView(value); setSelected(null) }}
                options={[
                  { value: 'agents', label: 'Agents', title: tooManyForAgentGraph ? `Over ${MAX_AGENT_GRAPH} agents: use Roles or the Agents tab` : 'One card per agent' },
                  { value: 'roles', label: 'Roles', title: 'Agents grouped by name' },
                ]}
              />
            )}
            {tab === 'agents' && <SearchInput value={query} onChange={setQuery} placeholder="Agent, status, tool, error" className="w-60" />}
          </div>
          <div className="border-t border-line">
            {tab === 'graph' && (
              graphView === 'agents' && tooManyForAgentGraph
                ? <EmptyState icon={<Network />} title={`${formatNumber(detail.nodes.length)} agents is too many to draw one by one`} detail="Switch to Roles to see the swarm grouped by agent name, or find an agent in the Agents tab." action={<Button onClick={() => setView('roles')}>Show roles</Button>} />
                : (
                    <>
                      <SwarmGraph detail={detail} view={graphView} selected={selected} onSelect={selectNode} />
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-4 py-2 text-xs text-fg-subtle">
                        {(['spawn', 'message', 'handoff'] as const).map(kind => (
                          <span key={kind} className="inline-flex items-center gap-1.5">
                            <svg width="22" height="6" aria-hidden><line x1="0" y1="3" x2="22" y2="3" stroke={EDGE_STYLE[kind].color} strokeWidth="2" strokeDasharray={EDGE_STYLE[kind].dash} /></svg>
                            {EDGE_STYLE[kind].label}
                          </span>
                        ))}
                        <span className="ml-auto">{graphView === 'roles' ? 'Grouped by agent name. Numbers on edges count the agents or messages.' : 'Left to right: who started whom.'}</span>
                      </div>
                    </>
                  )
            )}
            {tab === 'agents' && (
              <>
                <DataTable
                  rows={agents.slice(0, MAX_TABLE_ROWS)}
                  rowKey={row => row.key}
                  minWidth={980}
                  maxHeight="max-h-[70vh]"
                  onRow={row => selectNode(row.key)}
                  selectedRow={row => row.key === selected}
                  rowClassName={row => row.status === 'failed' ? 'shadow-[inset_2px_0_0_var(--danger)]' : ''}
                  empty={<EmptyState title="No matching agents" />}
                  columns={[
                    { label: 'Status', width: '100px', sortValue: row => row.status, render: row => <StatusBadge status={row.status} /> },
                    { label: 'Agent', sortValue: row => row.name, render: row => <span className="flex min-w-0 flex-col"><span className="truncate font-medium text-fg">{row.name}</span>{row.error_message && <span className="truncate text-xs text-danger-text" title={row.error_message}>{row.error_message}</span>}</span> },
                    { label: 'Started by', sortValue: row => nodesByKey.get(row.parent_key ?? '')?.name ?? '', render: row => <span className="truncate text-fg-muted">{nodesByKey.get(row.parent_key ?? '')?.name ?? '-'}</span> },
                    { label: 'Depth', align: 'right', sortValue: row => row.depth, render: row => <span className="tabular text-fg-muted">{row.depth}</span> },
                    { label: 'Started', align: 'right', sortValue: row => row.children, render: row => <span className="tabular text-fg-muted">{row.children || '-'}</span> },
                    { label: 'LLM', align: 'right', sortValue: row => row.llm_calls, render: row => <span className="tabular text-fg-muted">{row.llm_calls}</span> },
                    { label: 'Tools', align: 'right', sortValue: row => row.tool_calls, render: row => <span className="tabular text-fg-muted" title={row.tools.join(', ')}>{row.tool_calls}</span> },
                    { label: 'Cost', align: 'right', sortValue: row => row.cost, render: row => <span className="tabular text-fg">{row.cost ? formatMoney(row.cost) : '-'}</span> },
                    { label: 'Duration', align: 'right', sortValue: row => row.duration_ms ?? 0, render: row => <span className="tabular text-fg-muted">{formatMs(row.duration_ms)}</span> },
                  ]}
                />
                {agents.length > MAX_TABLE_ROWS && <p className="border-t border-line px-4 py-2 text-xs text-fg-subtle">Showing {MAX_TABLE_ROWS} of {formatNumber(agents.length)} agents. Search to narrow the list.</p>}
              </>
            )}
            {tab === 'messages' && (detail.messages.length === 0
              ? <EmptyState icon={<MessagesSquare />} title="No messages recorded" detail="Record agent-to-agent messages with agentmesh.send_message() and handoffs with agentmesh.handoff()." />
              : (
                  <ol className="max-h-[70vh] divide-y divide-line overflow-y-auto">
                    {detail.messages.map(message => (
                      <li key={message.message_id} className="flex items-start gap-3 px-4 py-2.5">
                        <span className="w-16 shrink-0 pt-0.5 text-xs text-fg-subtle tabular" title={formatDateTime(message.created_at)}>{formatTime(message.created_at)}</span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
                            <button className="font-medium text-fg hover:underline" onClick={() => message.source_key && selectNode(message.source_key)}>{message.from_agent ?? nodesByKey.get(message.source_key ?? '')?.name ?? 'unknown'}</button>
                            <span className="text-fg-subtle">→</span>
                            <button className={cn('font-medium hover:underline', message.target_key ? 'text-fg' : 'text-fg-subtle')} onClick={() => message.target_key && selectNode(message.target_key)}>{message.to_agent ?? 'unknown'}</button>
                            <Badge tone={message.kind === 'handoff' ? 'warning' : 'info'}>{message.kind}</Badge>
                            {!message.target_key && <Badge outline>outside swarm</Badge>}
                          </div>
                          {message.content !== null && message.content !== undefined && <p className="mt-0.5 line-clamp-2 text-xs text-fg-muted">{typeof message.content === 'string' ? message.content : jsonPreview(message.content)}</p>}
                        </div>
                        <Button size="icon-sm" variant="ghost" aria-label="Open trace" title="Open trace" onClick={() => onTrace(message.trace_id, message.span_id)}><ArrowUpRight /></Button>
                      </li>
                    ))}
                  </ol>
                )
            )}
            {tab === 'traces' && (
              <DataTable
                rows={detail.traces}
                rowKey={row => row.trace_id}
                minWidth={640}
                onRow={row => onTrace(row.trace_id)}
                columns={[
                  { label: 'Status', width: '110px', sortValue: row => row.status, render: row => <StatusBadge status={row.status} /> },
                  { label: 'Trace', sortValue: row => row.workflow_name ?? '', render: row => <span className="flex min-w-0 flex-col"><span className="truncate font-medium text-fg">{row.workflow_name ?? row.trace_id}</span><span className="truncate font-mono text-[11px] text-fg-subtle">{row.service_name ? `${row.service_name} · ` : ''}{row.trace_id}</span></span> },
                  { label: 'Duration', align: 'right', sortValue: row => row.duration_ms ?? 0, render: row => <span className="tabular text-fg-muted">{formatMs(row.duration_ms)}</span> },
                  { label: 'Started', align: 'right', sortValue: row => Date.parse(row.started_at) || 0, render: row => <span className="whitespace-nowrap text-fg-muted" title={formatDateTime(row.started_at)}>{formatTime(row.started_at)}</span> },
                ]}
              />
            )}
          </div>
        </Card>

        <div className="xl:sticky xl:top-20">
          {selectedNode
            ? <AgentPanel node={selectedNode} parent={nodesByKey.get(selectedNode.parent_key ?? '')} onSelect={selectNode} onTrace={onTrace} />
            : selectedRole
              ? (
                  <Card title={selectedRole.name} description={`${formatNumber(selectedRole.instances)} ${selectedRole.instances === 1 ? 'agent' : 'agents'} with this name`} icon={<Users />}>
                    <KeyValue rows={[
                      ['Running', formatNumber(selectedRole.running)],
                      ['Failed', <span key="failed" className={selectedRole.failed ? 'text-danger-text' : undefined}>{formatNumber(selectedRole.failed)}</span>],
                      ['LLM calls', formatNumber(selectedRole.llm_calls)],
                      ['Tool calls', formatNumber(selectedRole.tool_calls)],
                      ['Tokens', formatNumber(selectedRole.tokens)],
                      ['Cost', formatMoney(selectedRole.cost)],
                    ]} />
                    <Button className="mt-4 w-full" icon={<Users />} onClick={() => { setTab('agents'); setQuery(selectedRole.name) }}>List these agents</Button>
                  </Card>
                )
              : (
                  <Card title="Select an agent" icon={<Bot />}>
                    <p className="text-[13px] text-fg-muted">Click an agent in the graph or the table to see what it did, who started it, and to open its trace.</p>
                  </Card>
                )}
        </div>
      </div>
    </>
  )
}

function AgentPanel({ node, parent, onSelect, onTrace }: { node: SwarmNode; parent?: SwarmNode; onSelect: (key: string) => void; onTrace: (traceId: string, spanId?: string) => void }) {
  return (
    <Card
      title={<span className="flex items-center gap-2"><StatusDot status={node.status} />{node.name}</span>}
      description={node.kind === 'trace' ? 'Trace root' : node.folded_trace ? `Agent in trace “${node.folded_trace}”` : 'Agent'}
      icon={node.kind === 'trace' ? <ScrollText /> : <Bot />}
    >
      {node.error_message && <div className="mb-3"><Callout tone="danger" title="Failed">{node.error_message}</Callout></div>}
      <KeyValue rows={[
        ['Status', <StatusBadge key="status" status={node.status} />],
        ['Started by', parent ? <button key="parent" className="text-accent-text hover:underline" onClick={() => onSelect(parent.key)}>{parent.name}</button> : '-'],
        ['Agents started', formatNumber(node.children)],
        ['Depth', formatNumber(node.depth)],
        ['LLM calls', `${formatNumber(node.llm_calls)}${node.models.length ? ` · ${node.models.join(', ')}` : ''}`],
        ['Tool calls', `${formatNumber(node.tool_calls)}${node.tools.length ? ` · ${node.tools.join(', ')}` : ''}`],
        ['Tokens', formatNumber(node.tokens)],
        ['Cost', node.cost ? formatMoney(node.cost) : '-'],
        ['Duration', formatMs(node.duration_ms)],
        ['Started', formatDateTime(node.started_at)],
      ]} />
      <div className="mt-4 flex items-center gap-2">
        <Button variant="primary" className="flex-1" icon={<GitFork />} onClick={() => onTrace(node.trace_id, node.span_id)}>Open in trace</Button>
        <CopyableId value={node.trace_id} />
      </div>
    </Card>
  )
}

function StopSwarmDrawer({ open, detail, onClose, onStopped }: { open: boolean; detail: SwarmDetail; onClose: () => void; onStopped: () => void }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')

  async function stop() {
    try {
      await createHalt({ scope: 'swarm', value: detail.swarm_id, reason: reason.trim() || `Stopped ${detail.name} from the dashboard` })
      setReason('')
      setError('')
      onStopped()
    }
    catch (caught) {
      setError(errorText(caught).replace(/^POST \S+ failed with \d+: /, ''))
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={`Stop ${detail.name}`}
      description="A swarm halt: every agent in this swarm fails its next tool call, LLM call, or agent start, in every process, until you release it on the Guardrails page."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="danger" icon={<OctagonX />} onClick={() => void stop()}>Stop swarm</Button></>}
    >
      <form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); void stop() }}>
        <TextField label="Reason" value={reason} onChange={setReason} placeholder="Fan-out spiked to 400 agents" hint="Shown on the Guardrails page and in the error the agents receive." />
        <Callout tone="warning" title="Enforced by AgentMesh guardrails">Applies to agents traced with the Python SDK or its OpenAI and Anthropic instrumentation. Agents that only export OpenTelemetry spans are observed, not stopped.</Callout>
        {error && <p className="text-[13px] text-danger-text">{error}</p>}
      </form>
    </Drawer>
  )
}
