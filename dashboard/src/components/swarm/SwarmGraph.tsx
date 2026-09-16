import { Background, Controls, MarkerType, Position, ReactFlow, type Edge as FlowEdge, type Node as FlowNode } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Network } from 'lucide-react'
import { useMemo } from 'react'
import { cn } from '../../lib/utils'
import type { SwarmDetail, SwarmEdgeKind } from '../../types'
import { formatMoney, formatNumber } from '../../utils/format'
import { StatusDot } from '../ui/Badge'
import { EmptyState } from '../ui/Card'

const NODE_WIDTH = 208
const NODE_HEIGHT = 64
const MAX_ROWS = 10
const ROW_STEP = NODE_HEIGHT + 18
const COLUMN_GAP = 96

export const EDGE_STYLE: Record<SwarmEdgeKind, { color: string; dash?: string; label: string }> = {
  spawn: { color: 'var(--border-strong)', label: 'started' },
  message: { color: 'var(--chart-2)', dash: '5 4', label: 'message' },
  handoff: { color: 'var(--chart-3)', label: 'handoff' },
  link: { color: 'var(--fg-subtle)', dash: '2 4', label: 'link' },
}

interface GraphItem {
  id: string
  name: string
  depth: number
  order: string
  status: string
  kind: 'agent' | 'trace' | 'role'
  instances?: number
  failed?: number
  running?: number
  calls: number
  cost: number
  errors: number
}

/** Columns by depth (who started whom reads left to right); tall columns wrap into sub-columns. */
function layout(items: GraphItem[]): { positions: Map<string, { x: number; y: number }>; rows: number } {
  const columns = new Map<number, GraphItem[]>()
  for (const item of items)
    columns.set(item.depth, [...(columns.get(item.depth) ?? []), item])
  const positions = new Map<string, { x: number; y: number }>()
  const tallest = Math.min(Math.max(...[...columns.values()].map(column => column.length), 1), MAX_ROWS)
  let x = 0
  for (const depth of [...columns.keys()].sort((a, b) => a - b)) {
    const column = (columns.get(depth) ?? []).sort((a, b) => a.order.localeCompare(b.order))
    const chunks = Math.ceil(column.length / MAX_ROWS)
    for (let chunk = 0; chunk < chunks; chunk++) {
      const slice = column.slice(chunk * MAX_ROWS, (chunk + 1) * MAX_ROWS)
      const offset = ((tallest - slice.length) * ROW_STEP) / 2
      slice.forEach((item, row) => positions.set(item.id, { x: x + chunk * (NODE_WIDTH + 28), y: offset + row * ROW_STEP }))
    }
    x += chunks * (NODE_WIDTH + 28) + COLUMN_GAP
  }
  return { positions, rows: tallest }
}

export function SwarmGraph({ detail, view, selected, onSelect }: { detail: SwarmDetail; view: 'agents' | 'roles'; selected: string | null; onSelect: (id: string) => void }) {
  const { nodes, edges, rows } = useMemo(() => {
    let items: GraphItem[]
    let rawEdges: Array<{ source: string; target: string; kind: SwarmEdgeKind; count: number }>
    if (view === 'roles') {
      items = detail.roles.nodes.map(role => ({
        id: role.name,
        name: role.name,
        depth: role.min_depth,
        order: role.name,
        status: role.running ? 'running' : role.failed ? 'failed' : 'succeeded',
        kind: 'role',
        instances: role.instances,
        failed: role.failed,
        running: role.running,
        calls: role.llm_calls + role.tool_calls,
        cost: role.cost,
        errors: role.failed,
      }))
      rawEdges = detail.roles.edges
    }
    else {
      // Order siblings by their parent's position, then by start time, so a fan-out stays together.
      const byKey = new Map(detail.nodes.map(node => [node.key, node]))
      const orderOf = (key: string | null, guard = 0): string => {
        const node = key ? byKey.get(key) : undefined
        if (!node || guard > 32)
          return ''
        return `${orderOf(node.parent_key, guard + 1)}/${node.started_at ?? ''}${node.key}`
      }
      items = detail.nodes.map(node => ({
        id: node.key,
        name: node.name,
        depth: node.depth,
        order: orderOf(node.key),
        status: node.status,
        kind: node.kind,
        calls: node.llm_calls + node.tool_calls,
        cost: node.cost,
        errors: node.errors,
      }))
      rawEdges = detail.edges
    }
    const known = new Set(items.map(item => item.id))
    const running = new Set(items.filter(item => item.status === 'running').map(item => item.id))
    const { positions, rows } = layout(items)
    return {
      rows,
      nodes: items.map((item): FlowNode => ({
        id: item.id,
        position: positions.get(item.id) ?? { x: 0, y: 0 },
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
                selected === item.id ? 'border-accent ring-2 ring-accent/25' : item.status === 'failed' || item.failed ? 'border-danger/60' : 'border-line hover:border-line-strong',
              )}
              onClick={() => onSelect(item.id)}
            >
              <span className="flex w-full items-center gap-2">
                <StatusDot status={item.status} pulse={item.status === 'running'} />
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg" title={item.name}>{item.name}</span>
                {item.kind === 'role'
                  ? <span className="tabular rounded bg-accent-soft px-1.5 text-[10.5px] font-semibold text-accent-text">×{formatNumber(item.instances)}</span>
                  : <span className={cn('rounded px-1 text-[10px] font-medium uppercase', item.kind === 'agent' ? 'bg-accent-soft text-accent-text' : 'bg-surface-3 text-fg-muted')}>{item.kind}</span>}
              </span>
              <span className="flex w-full items-center gap-2 text-[11px] text-fg-subtle">
                <span className="tabular">{formatNumber(item.calls)} calls</span>
                {item.cost > 0 && <span className="tabular">{formatMoney(item.cost)}</span>}
                {item.kind === 'role' && item.failed ? <span className="tabular text-danger-text">{formatNumber(item.failed)} failed</span> : item.errors ? <span className="tabular text-danger-text">{formatNumber(item.errors)} errors</span> : null}
              </span>
            </button>
          ),
        },
      })),
      edges: rawEdges
        .filter(edge => known.has(edge.source) && known.has(edge.target))
        .map((edge, index): FlowEdge => {
          const style = EDGE_STYLE[edge.kind] ?? EDGE_STYLE.link
          return {
            id: `${edge.kind}-${edge.source}-${edge.target}-${index}`,
            source: edge.source,
            target: edge.target,
            type: edge.kind === 'spawn' ? 'smoothstep' : 'default',
            animated: edge.kind === 'spawn' && running.has(edge.target),
            label: edge.count > 1 ? `×${edge.count}` : edge.kind === 'handoff' ? 'handoff' : undefined,
            labelStyle: { fontSize: 10, fill: 'var(--fg-muted)' },
            labelBgStyle: { fill: 'var(--surface)' },
            markerEnd: edge.kind === 'spawn' ? undefined : { type: MarkerType.ArrowClosed, color: style.color, width: 14, height: 14 },
            style: { stroke: style.color, strokeWidth: edge.kind === 'spawn' ? 1.5 : 1.25, strokeDasharray: style.dash },
          }
        }),
    }
  }, [detail, view, selected, onSelect])

  if (nodes.length === 0)
    return <EmptyState icon={<Network />} title="No agents yet" detail="Agents appear here as their spans arrive." />
  const height = Math.min(Math.max(440, rows * ROW_STEP * 0.75 + 110), 760)
  return (
    <div className="min-w-0" style={{ height }}>
      <ReactFlow
        key={`${detail.swarm_id}-${view}`}
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.1, maxZoom: 1.1 }}
        minZoom={0.1}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        zoomOnDoubleClick={false}
        onlyRenderVisibleElements
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--border)" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
