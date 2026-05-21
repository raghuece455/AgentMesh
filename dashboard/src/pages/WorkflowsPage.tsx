import { FileJson, GitBranch, History, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import type { ApprovalRecord, Checkpoint, TraceSummary, WorkflowGraph, WorkflowSummary } from '../types'
import { ActionButton } from '../components/common/Actions'
import { StatusBadge } from '../components/common/Badges'
import { EmptyState, Panel, PanelInset } from '../components/common/Cards'
import { JsonViewer } from '../components/common/JsonViewer'
import { DataTable } from '../components/tables/DataTable'
import { WorkflowGraphView } from '../components/workflow/WorkflowGraphView'
import { formatCost, formatMs, formatTime, shortId } from '../utils/format'
import { KeyValueGrid } from '../components/trace/TraceInspector'

export function WorkflowsPage({
  workflows,
  traces,
  approvals,
  checkpoints,
  activeGraph,
  onGraph,
  onNodeReplay,
}: {
  workflows: WorkflowSummary[]
  traces: TraceSummary[]
  approvals: ApprovalRecord[]
  checkpoints: Checkpoint[]
  activeGraph: WorkflowGraph | null
  onGraph: (workflowId: string) => void
  onNodeReplay: (traceId: string, spanId?: string) => void
}) {
  const [selectedNode, setSelectedNode] = useState<WorkflowGraph['nodes'][number] | null>(null)
  const activeTrace = traces.find(trace => trace.trace_id === activeGraph?.trace_id)
  const graphCheckpoints = checkpoints.filter(checkpoint => checkpoint.trace_id === activeGraph?.trace_id)
  const graphApprovals = approvals.filter(approval => approval.trace_id === activeGraph?.trace_id || approval.workflow === activeTrace?.workflow_name)
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[360px_1fr]">
      <Panel title="Workflows" icon={<GitBranch className="size-4" />}>
        <DataTable
          rows={workflows}
          minWidth={500}
          columns={[
            { label: 'Workflow', render: row => row.workflow_name, sortValue: row => row.workflow_name },
            { label: 'Runs', render: row => row.runs, sortValue: row => row.runs },
            { label: 'Failures', render: row => row.failed_runs, sortValue: row => row.failed_runs },
            { label: 'Cost', render: row => formatCost(row.total_cost), sortValue: row => row.total_cost },
          ]}
          onRow={row => onGraph(row.workflow_id)}
        />
      </Panel>
      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel title="Temporal Execution View" icon={<GitBranch className="size-4" />}>
          <WorkflowGraphView graph={activeGraph} selectedNode={selectedNode?.id ?? ''} onSelect={setSelectedNode} />
        </Panel>
        <Panel title="Execution Inspector" icon={<FileJson className="size-4" />}>
          {selectedNode ? (
            <div className="flex flex-col gap-3">
              <KeyValueGrid
                rows={[
                  ['Name', selectedNode.name],
                  ['Type', selectedNode.type],
                  ['Status', <StatusBadge status={selectedNode.status} />],
                  ['Duration', formatMs(selectedNode.duration_ms)],
                  ['Cost', formatCost(selectedNode.cost)],
                  ['Tokens', selectedNode.tokens ?? 0],
                  ['Retries', selectedNode.retry_count ?? 0],
                  ['Error', selectedNode.error],
                ]}
              />
              {activeGraph?.trace_id && <ActionButton icon={<RotateCcw className="size-4" />} label="Replay from node" tone="purple" onClick={() => onNodeReplay(activeGraph.trace_id!, selectedNode.id)} />}
              <JsonViewer value={selectedNode.raw ?? selectedNode} />
            </div>
          ) : <EmptyState title="Select a node" />}
        </Panel>
        <Panel title="Execution History" icon={<History className="size-4" />} className="2xl:col-span-2">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <PanelInset title="State transitions">
              <div className="flex flex-col gap-2">
                {(activeGraph?.nodes ?? []).map(node => <button key={node.id} className="rounded-2xl border border-white/10 bg-slate-950/20 p-3 text-left hover:bg-white/10" onClick={() => setSelectedNode(node)}><div className="flex items-center justify-between gap-2"><span className="truncate text-sm/6 font-semibold text-white">{node.name}</span><StatusBadge status={node.status} /></div><div className="text-xs/5 text-white/54">{node.type} / {formatMs(node.duration_ms)} / {formatCost(node.cost)}</div></button>)}
              </div>
            </PanelInset>
            <PanelInset title="Pending approvals">
              <div className="flex flex-col gap-2">
                {graphApprovals.map(approval => <div key={approval.approval_id} className="rounded-2xl border border-white/10 bg-slate-950/20 p-3"><div className="text-sm/6 font-semibold text-white">{approval.tool}</div><div className="text-xs/5 text-white/54">{approval.agent} / {approval.risk_level ?? 'medium'} / {formatTime(approval.created_at)}</div></div>)}
                {graphApprovals.length === 0 && <EmptyState title="No pending approvals" />}
              </div>
            </PanelInset>
            <PanelInset title="Checkpoints and replay">
              <div className="flex flex-col gap-2">
                {graphCheckpoints.map(checkpoint => <button key={checkpoint.checkpoint_id} className="rounded-2xl border border-white/10 bg-slate-950/20 p-3 text-left hover:bg-white/10" onClick={() => activeGraph?.trace_id && onNodeReplay(activeGraph.trace_id, checkpoint.step_id ?? undefined)}><div className="text-sm/6 font-semibold text-white">{checkpoint.checkpoint_type}</div><div className="text-xs/5 text-white/54">{shortId(checkpoint.checkpoint_id)} / {checkpoint.step_id ?? 'workflow'} / {formatTime(checkpoint.created_at)}</div></button>)}
                {graphCheckpoints.length === 0 && <EmptyState title="No checkpoints" />}
              </div>
            </PanelInset>
          </div>
        </Panel>
      </div>
    </div>
  )
}
