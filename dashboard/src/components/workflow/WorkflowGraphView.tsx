import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge as FlowEdge,
  type Node as FlowNode,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { EmptyState } from '../common/Cards'
import { StatusBadge } from '../common/Badges'
import type { WorkflowGraph } from '../../types'
import { formatCost, formatMs, formatNumber } from '../../utils/format'
import { Route } from 'lucide-react'

export function WorkflowGraphView({ graph, selectedNode, onSelect }: { graph: WorkflowGraph | null; selectedNode: string; onSelect: (node: WorkflowGraph['nodes'][number]) => void }) {
  if (!graph || graph.nodes.length === 0)
    return <EmptyState icon={<Route className="size-5" />} title="No workflow graph" detail="Run or select a workflow to view execution topology." />
  const failedNodeIds = new Set(graph.nodes.filter(node => node.status === 'failed').map(node => node.id))
  const flowNodes: FlowNode[] = graph.nodes.map((node, index) => {
    const col = index % 4
    const row = Math.floor(index / 4)
    return {
      id: node.id,
      position: { x: col * 260, y: row * 126 },
      data: {
        label: (
          <button className={`flow-node ${selectedNode === node.id ? 'flow-node-active' : ''} ${node.status === 'failed' ? 'flow-node-failed' : ''}`} onClick={() => onSelect(node)}>
            <span className="flex items-center justify-between gap-2">
              <span className="block truncate text-sm font-semibold">{node.name}</span>
              <StatusBadge status={node.status} />
            </span>
            <span className="mt-1 block text-xs font-semibold uppercase tracking-wide text-white/52">{node.type}</span>
            <span className="mt-1 flex flex-wrap gap-1.5 text-xs text-white/62">
              <span>{formatMs(node.duration_ms)}</span>
              <span>{formatCost(node.cost)}</span>
              <span>{formatNumber(node.tokens)} tok</span>
            </span>
          </button>
        ),
      },
      style: { background: 'transparent', border: 0, width: 220, height: 98 },
      draggable: false,
      selectable: false,
    }
  })
  const flowEdges: FlowEdge[] = graph.edges.map((edge, index) => ({
    id: `${edge.source}-${edge.target}-${index}`,
    source: edge.source,
    target: edge.target,
    animated: graph.nodes.some(node => node.id === edge.target && node.status === 'running'),
    style: { stroke: failedNodeIds.has(edge.target) ? '#fb7185' : 'rgb(255 255 255 / 0.32)', strokeWidth: failedNodeIds.has(edge.target) ? 3 : 2 },
  }))
  return (
    <div className="h-[520px] overflow-hidden rounded-3xl border border-white/12 bg-slate-950/28">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        defaultViewport={{ x: 32, y: 70, zoom: 0.86 }}
        minZoom={0.35}
        maxZoom={1.35}
        nodesDraggable={false}
        nodesConnectable={false}
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="rgb(255 255 255 / 0.18)" gap={24} />
        <MiniMap pannable zoomable style={{ width: 132, height: 92 }} nodeColor="#38bdf8" maskColor="rgb(0 0 0 / 0.42)" />
        <Controls showInteractive={false} fitViewOptions={{ padding: 0.2 }} />
      </ReactFlow>
    </div>
  )
}
