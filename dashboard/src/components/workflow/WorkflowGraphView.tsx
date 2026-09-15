import { Background, Controls, Position, ReactFlow, type Edge as FlowEdge, type Node as FlowNode } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { GitBranch } from 'lucide-react'
import { useMemo } from 'react'
import { cn } from '../../lib/utils'
import type { WorkflowGraph } from '../../types'
import { formatMoney, formatMs, numeric } from '../../utils/format'
import { StatusDot } from '../ui/Badge'
import { EmptyState } from '../ui/Card'

type GraphNode = WorkflowGraph['nodes'][number]

const NODE_WIDTH = 220
const NODE_HEIGHT = 76
const MAX_ROWS = 12
const ROW_STEP = NODE_HEIGHT + 20

/** Layer nodes by their longest path from a root, so the graph reads left to right. */
function layout(graph: WorkflowGraph): { positions: Map<string, { x: number; y: number }>; rows: number } {
  const incoming = new Map<string, string[]>()
  for (const edge of graph.edges)
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source])
  const depth = new Map<string, number>()
  const visiting = new Set<string>()
  const depthOf = (id: string): number => {
    if (depth.has(id))
      return depth.get(id)!
    if (visiting.has(id))
      return 0
    visiting.add(id)
    const parents = incoming.get(id) ?? []
    const value = parents.length ? Math.max(...parents.map(parent => depthOf(parent) + 1)) : 0
    visiting.delete(id)
    depth.set(id, value)
    return value
  }
  const columns = new Map<number, string[]>()
  for (const node of graph.nodes) {
    const column = depthOf(node.id)
    columns.set(column, [...(columns.get(column) ?? []), node.id])
  }
  // Each layer is one column, centered on the tallest. Only very wide fan-outs wrap into extra
  // sub-columns, since edges into a wrapped column have to cross the column before it.
  const positions = new Map<string, { x: number; y: number }>()
  const tallest = Math.min(Math.max(...[...columns.values()].map(ids => ids.length), 1), MAX_ROWS)
  let x = 0
  for (const column of [...columns.keys()].sort((a, b) => a - b)) {
    const ids = columns.get(column) ?? []
    const chunks = Math.ceil(ids.length / MAX_ROWS)
    for (let chunk = 0; chunk < chunks; chunk++) {
      const slice = ids.slice(chunk * MAX_ROWS, (chunk + 1) * MAX_ROWS)
      const offset = ((tallest - slice.length) * ROW_STEP) / 2
      slice.forEach((id, row) => positions.set(id, { x: x + chunk * (NODE_WIDTH + 40), y: offset + row * ROW_STEP }))
    }
    x += chunks * (NODE_WIDTH + 40) + 80
  }
  return { positions, rows: tallest }
}

const TYPE_STYLE: Record<string, string> = {
  agent: 'bg-accent-soft text-accent-text',
  model: 'bg-violet-soft text-violet-text',
  llm: 'bg-violet-soft text-violet-text',
  tool: 'bg-warning-soft text-warning-text',
  memory: 'bg-success-soft text-success-text',
  retrieval: 'bg-info-soft text-info-text',
}

export function WorkflowGraphView({ graph, selectedNode, onSelect }: { graph: WorkflowGraph | null; selectedNode: string; onSelect: (node: GraphNode) => void }) {
  const { nodes, edges, rows } = useMemo(() => {
    if (!graph)
      return { nodes: [] as FlowNode[], edges: [] as FlowEdge[], rows: 0 }
    const { positions, rows } = layout(graph)
    const failed = new Set(graph.nodes.filter(node => node.status === 'failed').map(node => node.id))
    return {
      nodes: graph.nodes.map(node => ({
        id: node.id,
        position: positions.get(node.id) ?? { x: 0, y: 0 },
        // The layout reads left to right, so edges leave from the right and enter on the left.
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        draggable: false,
        selectable: false,
        style: { background: 'transparent', border: 0, padding: 0, width: NODE_WIDTH, height: NODE_HEIGHT },
        data: {
          label: (
            <button
              className={cn(
                'flex h-full w-full flex-col justify-between rounded-lg border bg-surface px-3 py-2 text-left shadow-card transition-colors',
                selectedNode === node.id ? 'border-accent ring-2 ring-accent/25' : node.status === 'failed' ? 'border-danger/60' : 'border-line hover:border-line-strong',
              )}
              onClick={() => onSelect(node)}
            >
              <span className="flex w-full items-center gap-2">
                <StatusDot status={node.status} />
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">{node.name}</span>
                <span className={cn('rounded px-1 text-[10px] font-medium uppercase', TYPE_STYLE[node.type] ?? 'bg-surface-3 text-fg-muted')}>{node.type}</span>
              </span>
              <span className="flex w-full items-center gap-2 text-[11px] text-fg-subtle">
                <span className="tabular">{formatMs(node.duration_ms)}</span>
                {numeric(node.cost) > 0 && <span className="tabular">{formatMoney(node.cost)}</span>}
                {numeric(node.tokens) > 0 && <span className="tabular">{numeric(node.tokens).toLocaleString()} tok</span>}
              </span>
            </button>
          ),
        },
      })),
      edges: graph.edges.map((edge, index) => ({
        id: `${edge.source}-${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
        type: 'smoothstep',
        animated: graph.nodes.some(node => node.id === edge.target && node.status === 'running'),
        style: { stroke: failed.has(edge.target) ? 'var(--danger)' : 'var(--border-strong)', strokeWidth: failed.has(edge.target) ? 2 : 1.5 },
      })),
      rows,
    }
  }, [graph, selectedNode, onSelect])

  if (!graph || graph.nodes.length === 0)
    return <EmptyState icon={<GitBranch />} title="No workflow graph" detail="Select a workflow to see its latest execution as a graph." />
  // Grow the canvas with the tallest column so node labels stay readable at fit-to-view zoom.
  const height = Math.min(Math.max(420, rows * ROW_STEP * 0.7 + 100), 780)
  return (
    <div className="min-w-0" style={{ height }}>
      <ReactFlow
        key={graph.trace_id ?? graph.workflow_id}
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.08, maxZoom: 1.1 }}
        minZoom={0.3}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--border)" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
