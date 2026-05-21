import { AlertTriangle, GitBranch } from 'lucide-react'
import { useMemo } from 'react'
import type { SpanRecord } from '../../types'
import { formatMs, shortId } from '../../utils/format'
import { Badge, StatusBadge } from '../common/Badges'
import { EmptyState } from '../common/Cards'

export function SpanTree({ spans, selected, onSelect }: { spans: SpanRecord[]; selected: string; onSelect: (span: SpanRecord) => void }) {
  const children = useMemo(() => {
    const map = new Map<string | null, SpanRecord[]>()
    for (const span of spans) {
      const parent = span.parent_span_id ?? null
      map.set(parent, [...(map.get(parent) ?? []), span])
    }
    return map
  }, [spans])
  const roots = children.get(null) ?? spans.filter(span => !spans.some(item => item.span_id === span.parent_span_id))
  if (spans.length === 0)
    return <EmptyState icon={<GitBranch className="size-5" />} title="No spans" detail="This trace does not have persisted span data yet." />
  return (
    <div className="vision-scroll max-h-[680px] overflow-auto pr-1">
      {roots.map(span => <SpanNode key={span.span_id} span={span} childrenMap={children} depth={0} selected={selected} onSelect={onSelect} />)}
    </div>
  )
}

function SpanNode({
  span,
  childrenMap,
  depth,
  selected,
  onSelect,
}: {
  span: SpanRecord
  childrenMap: Map<string | null, SpanRecord[]>
  depth: number
  selected: string
  onSelect: (span: SpanRecord) => void
}) {
  const children = childrenMap.get(span.span_id) ?? []
  return (
    <div>
      <button
        className={`mb-1 flex w-full items-center justify-between gap-2 rounded-2xl border px-3 py-2 text-left transition ${selected === span.span_id ? 'border-sky-200/62 bg-sky-400/18' : span.status === 'failed' ? 'border-rose-200/30 bg-rose-500/12 hover:bg-rose-500/18' : 'border-white/12 bg-slate-950/20 hover:bg-white/10'}`}
        style={{ paddingLeft: `${12 + depth * 14}px` }}
        onClick={() => onSelect(span)}
      >
        <span className="min-w-0">
          <span className="block truncate text-sm/6 font-semibold text-white">{span.event_type}</span>
          <span className="block truncate text-xs/5 text-white/52">{span.agent_name ?? span.workflow_name ?? 'workflow'} / {shortId(span.span_id)}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {span.error_message && <AlertTriangle className="size-4 text-rose-100" />}
          <Badge>{formatMs(span.duration_ms)}</Badge>
          <StatusBadge status={span.status} />
        </span>
      </button>
      {children.map(child => <SpanNode key={child.span_id} span={child} childrenMap={childrenMap} depth={depth + 1} selected={selected} onSelect={onSelect} />)}
    </div>
  )
}
