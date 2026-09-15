import { Bot, Brain, CircleDot, Database, Flag, GitBranch, RotateCcw, Save, Search, ShieldCheck, Wrench } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { SpanKind } from '../../utils/traces'

export const KIND_META: Record<SpanKind, { label: string; className: string; bar: string }> = {
  workflow: { label: 'Workflow', className: 'bg-surface-3 text-fg-muted', bar: 'bg-fg-subtle/60' },
  agent: { label: 'Agent', className: 'bg-accent-soft text-accent-text', bar: 'bg-accent' },
  llm: { label: 'LLM', className: 'bg-violet-soft text-violet-text', bar: 'bg-violet' },
  tool: { label: 'Tool', className: 'bg-warning-soft text-warning-text', bar: 'bg-warning' },
  retrieval: { label: 'Retrieval', className: 'bg-info-soft text-info-text', bar: 'bg-info' },
  memory: { label: 'Memory', className: 'bg-success-soft text-success-text', bar: 'bg-success' },
  approval: { label: 'Approval', className: 'bg-warning-soft text-warning-text', bar: 'bg-warning' },
  checkpoint: { label: 'Checkpoint', className: 'bg-surface-3 text-fg-muted', bar: 'bg-fg-subtle/60' },
  replay: { label: 'Replay', className: 'bg-violet-soft text-violet-text', bar: 'bg-violet' },
  span: { label: 'Span', className: 'bg-surface-3 text-fg-muted', bar: 'bg-fg-subtle/70' },
}

export function SpanKindIcon({ kind, failed = false, className }: { kind: SpanKind; failed?: boolean; className?: string }) {
  const icon = {
    workflow: <GitBranch />,
    agent: <Bot />,
    llm: <Brain />,
    tool: <Wrench />,
    retrieval: <Search />,
    memory: <Database />,
    approval: <ShieldCheck />,
    checkpoint: <Save />,
    replay: <RotateCcw />,
    span: <CircleDot />,
  }[kind]
  return (
    <span
      title={KIND_META[kind].label}
      className={cn('grid size-5 shrink-0 place-items-center rounded-[5px] [&_svg]:size-3', failed ? 'bg-danger-soft text-danger-text' : KIND_META[kind].className, className)}
    >
      {failed ? <Flag /> : icon}
    </span>
  )
}
