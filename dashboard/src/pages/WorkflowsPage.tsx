import { ArrowUpRight, GitBranch, RotateCcw } from 'lucide-react'
import { useCallback, useState } from 'react'
import { Badge, StatusBadge, StatusDot } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, KeyValue, PageHeader } from '../components/ui/Card'
import { CopyableId, JsonViewer } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Drawer } from '../components/ui/Overlay'
import { Tabs } from '../components/ui/Tabs'
import { WorkflowGraphView } from '../components/workflow/WorkflowGraphView'
import type { ApprovalRecord, Checkpoint, TraceSummary, WorkflowGraph, WorkflowSummary } from '../types'
import { formatMoney, formatMs, formatNumber, formatPercent, formatRelative, numeric } from '../utils/format'

type GraphNode = WorkflowGraph['nodes'][number]

export function WorkflowsPage({
  workflows,
  traces,
  approvals,
  checkpoints,
  activeGraph,
  onGraph,
  onNodeReplay,
  onTrace,
}: {
  workflows: WorkflowSummary[]
  traces: TraceSummary[]
  approvals: ApprovalRecord[]
  checkpoints: Checkpoint[]
  activeGraph: WorkflowGraph | null
  onGraph: (workflowId: string) => void
  onNodeReplay: (traceId: string, spanId?: string) => void
  onTrace: (traceId: string) => void
}) {
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [tab, setTab] = useState<'runs' | 'checkpoints' | 'approvals'>('runs')
  const onSelect = useCallback((node: GraphNode) => setSelectedNode(node), [])
  const workflow = workflows.find(item => item.workflow_id === activeGraph?.workflow_id)
  const runs = traces.filter(trace => trace.workflow_id === activeGraph?.workflow_id || (workflow && trace.workflow_name === workflow.workflow_name))
  const graphCheckpoints = checkpoints.filter(checkpoint => runs.some(run => run.trace_id === checkpoint.trace_id))
  const graphApprovals = approvals.filter(approval => runs.some(run => run.trace_id === approval.trace_id) || approval.workflow === workflow?.workflow_name)

  return (
    <>
      <PageHeader title="Workflows" description="Orchestrated runs as execution graphs: which agent called which model and tool, and where it failed." />
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card flush title="Workflows" description={`${workflows.length} total`} className="xl:sticky xl:top-20">
          {workflows.length === 0
            ? <EmptyState icon={<GitBranch />} title="No workflows yet" />
            : (
                <ul className="max-h-[70vh] divide-y divide-line overflow-y-auto">
                  {workflows.map(item => {
                    const active = item.workflow_id === activeGraph?.workflow_id
                    const failureRate = item.runs ? item.failed_runs / item.runs : 0
                    return (
                      <li key={item.workflow_id}>
                        <button className={`flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors ${active ? 'bg-accent-soft/60 shadow-[inset_2px_0_0_var(--accent)]' : 'hover:bg-surface-2/60'}`} onClick={() => { setSelectedNode(null); onGraph(item.workflow_id) }}>
                          <span className="flex items-center justify-between gap-2">
                            <span className="truncate text-[13px] font-medium text-fg">{item.workflow_name}</span>
                            {item.active_runs > 0 && <Badge tone="info">{item.active_runs} running</Badge>}
                          </span>
                          <span className="flex items-center gap-2 text-xs text-fg-subtle">
                            <span>{formatNumber(item.runs)} runs</span>
                            <span className={failureRate > 0 ? 'text-danger-text' : ''}>{formatPercent(failureRate)} failed</span>
                            <span>{formatMs(item.avg_latency_ms)}</span>
                            {numeric(item.total_cost) > 0 && <span>{formatMoney(item.total_cost)}</span>}
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          <Card
            flush
            title={workflow?.workflow_name ?? 'Execution graph'}
            description={activeGraph?.trace_id ? 'Latest run' : undefined}
            actions={activeGraph?.trace_id && <Button size="sm" variant="ghost" onClick={() => onTrace(activeGraph.trace_id!)}>Open trace<ArrowUpRight /></Button>}
          >
            <WorkflowGraphView graph={activeGraph} selectedNode={selectedNode?.id ?? ''} onSelect={onSelect} />
          </Card>

          <Card flush>
            <Tabs
              className="px-2"
              value={tab}
              onChange={setTab}
              items={[
                { value: 'runs', label: 'Runs', count: runs.length },
                { value: 'checkpoints', label: 'Checkpoints', count: graphCheckpoints.length },
                { value: 'approvals', label: 'Approvals', count: graphApprovals.length },
              ]}
            />
            {tab === 'runs' && (
              <DataTable
                rows={runs}
                rowKey={row => row.trace_id}
                minWidth={560}
                onRow={row => onTrace(row.trace_id)}
                empty={<EmptyState title="No runs in the current time range" />}
                columns={[
                  { label: 'Run', render: row => <span className="flex items-center gap-2"><StatusDot status={row.status} /><CopyableId value={row.trace_id} /></span> },
                  { label: 'Status', sortValue: row => row.status, render: row => <StatusBadge status={row.status} /> },
                  { label: 'Duration', align: 'right', sortValue: row => numeric(row.duration_ms), render: row => formatMs(row.duration_ms) },
                  { label: 'Cost', align: 'right', sortValue: row => numeric(row.estimated_cost), render: row => numeric(row.estimated_cost) ? formatMoney(row.estimated_cost) : '-' },
                  { label: 'Started', align: 'right', sortValue: row => Date.parse(row.started_at), render: row => <span className="text-fg-muted">{formatRelative(row.started_at)}</span> },
                ]}
              />
            )}
            {tab === 'checkpoints' && (
              <DataTable
                rows={graphCheckpoints}
                rowKey={row => row.checkpoint_id}
                minWidth={560}
                empty={<EmptyState title="No checkpoints" />}
                columns={[
                  { label: 'Type', render: row => <Badge tone={row.checkpoint_type.includes('fail') ? 'danger' : 'neutral'}>{row.checkpoint_type}</Badge> },
                  { label: 'Step', render: row => <span className="font-mono text-xs">{row.step_id ?? 'workflow'}</span> },
                  { label: 'Created', align: 'right', render: row => <span className="text-fg-muted">{formatRelative(row.created_at)}</span> },
                  { label: '', align: 'right', render: row => <Button size="xs" variant="ghost" icon={<RotateCcw />} onClick={() => onNodeReplay(row.trace_id, row.step_id ?? undefined)}>Replay</Button> },
                ]}
              />
            )}
            {tab === 'approvals' && (
              <DataTable
                rows={graphApprovals}
                rowKey={row => row.approval_id}
                minWidth={560}
                empty={<EmptyState title="No approvals" />}
                columns={[
                  { label: 'Tool', render: row => <span className="font-mono text-xs font-medium">{row.tool}</span> },
                  { label: 'Agent', render: row => <span className="text-fg-muted">{row.agent}</span> },
                  { label: 'Status', render: row => <StatusBadge status={row.status} /> },
                  { label: 'Created', align: 'right', render: row => <span className="text-fg-muted">{formatRelative(row.created_at)}</span> },
                ]}
              />
            )}
          </Card>
        </div>
      </div>

      <Drawer
        open={Boolean(selectedNode)}
        onClose={() => setSelectedNode(null)}
        title={selectedNode?.name ?? ''}
        description={selectedNode?.type}
        width="max-w-xl"
        footer={activeGraph?.trace_id && selectedNode && <Button variant="primary" icon={<RotateCcw />} onClick={() => onNodeReplay(activeGraph.trace_id!, selectedNode.id)}>Replay from this node</Button>}
      >
        {selectedNode && (
          <div className="flex flex-col gap-4">
            <KeyValue rows={[
              ['Status', <StatusBadge status={selectedNode.status} />],
              ['Duration', formatMs(selectedNode.duration_ms)],
              ['Cost', numeric(selectedNode.cost) ? formatMoney(selectedNode.cost) : null],
              ['Tokens', numeric(selectedNode.tokens) ? formatNumber(selectedNode.tokens) : null],
              ['Retries', selectedNode.retry_count || null],
              ['Error', selectedNode.error ? <span className="text-danger-text">{selectedNode.error}</span> : null],
            ]} />
            <JsonViewer value={selectedNode.raw ?? selectedNode} label="Node" />
          </div>
        )}
      </Drawer>
    </>
  )
}
