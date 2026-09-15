import { ArrowUpRight, Bot, MessagesSquare, User } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { getSession } from '../api'
import { Badge, StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, PageHeader, Skeleton } from '../components/ui/Card'
import { CodeBlock } from '../components/ui/Code'
import { SearchInput } from '../components/ui/Field'
import { StatStrip } from '../components/ui/Stat'
import { cn } from '../lib/utils'
import type { SessionDetail, SessionSummary } from '../types'
import { errorText, formatMoney, formatMs, formatNumber, formatRelative, jsonPreview, numeric } from '../utils/format'

export function SessionsPage({ sessions, initialSessionId = '', onTraceSelect }: { sessions: SessionSummary[]; initialSessionId?: string; onTraceSelect: (traceId: string) => void }) {
  const [selectedId, setSelectedId] = useState(initialSessionId)
  const [query, setQuery] = useState('')
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [error, setError] = useState('')
  const activeId = selectedId || sessions[0]?.session_id || ''

  useEffect(() => {
    if (!activeId) {
      setDetail(null)
      return
    }
    let cancelled = false
    getSession(activeId)
      .then(result => { if (!cancelled) { setDetail(result); setError('') } })
      .catch(caught => { if (!cancelled) setError(errorText(caught)) })
    return () => { cancelled = true }
  }, [activeId])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return term ? sessions.filter(session => `${session.session_id} ${session.user_id ?? ''}`.toLowerCase().includes(term)) : sessions
  }, [sessions, query])

  if (sessions.length === 0) {
    return (
      <>
        <PageHeader title="Sessions" description="Multi-turn conversations, grouped by session id." />
        <Card>
          <EmptyState
            icon={<MessagesSquare />}
            title="No sessions yet"
            detail="Group turns of a conversation by setting a session id on each trace."
          />
          <div className="mx-auto grid w-full max-w-2xl gap-3">
            <CodeBlock language="python" code={'with agentmesh.trace("support", session_id="chat-42", user_id="u-7"):\n    answer = run_agent(question)'} />
            <CodeBlock language="opentelemetry" code={'span.set_attribute("gen_ai.conversation.id", "chat-42")'} />
          </div>
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader title="Sessions" description={`${formatNumber(sessions.length)} ${sessions.length === 1 ? 'conversation' : 'conversations'}. Each turn is a trace.`} />
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Card flush className="xl:sticky xl:top-20">
          <div className="border-b border-line p-3">
            <SearchInput className="w-full" value={query} onChange={setQuery} placeholder="Filter by session or user" />
          </div>
          <ul className="max-h-[70vh] divide-y divide-line overflow-y-auto">
            {filtered.map(session => {
              const active = session.session_id === activeId
              return (
                <li key={session.session_id}>
                  <button className={cn('flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors', active ? 'bg-accent-soft/60 shadow-[inset_2px_0_0_var(--accent)]' : 'hover:bg-surface-2/60')} onClick={() => setSelectedId(session.session_id)}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-[12.5px] font-medium text-fg">{session.session_id}</span>
                      <span className="shrink-0 text-xs text-fg-subtle">{formatRelative(session.last_activity_at)}</span>
                    </span>
                    <span className="flex items-center gap-2 text-xs text-fg-muted">
                      <span>{session.trace_count} {session.trace_count === 1 ? 'turn' : 'turns'}</span>
                      {session.user_id && <span className="truncate">· {session.user_id}</span>}
                      {session.failed_traces > 0 && <Badge tone="danger" className="ml-auto">{session.failed_traces} failed</Badge>}
                    </span>
                  </button>
                </li>
              )
            })}
            {filtered.length === 0 && <li className="px-4 py-6 text-center text-[13px] text-fg-subtle">No sessions match.</li>}
          </ul>
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          {error && <Card><EmptyState title="Could not load session" detail={error} /></Card>}
          {!error && !detail && <Skeleton className="h-96 rounded-xl" />}
          {detail && (
            <>
              <div>
                <h2 className="font-mono text-base font-semibold text-fg">{detail.session_id}</h2>
                <p className="text-[13px] text-fg-muted">{detail.user_id ? `User ${detail.user_id} · ` : ''}started {formatRelative(detail.started_at)}</p>
              </div>
              <StatStrip items={[
                { label: 'Turns', value: detail.trace_count },
                { label: 'Failed turns', value: detail.failed_traces, tone: detail.failed_traces ? 'danger' : undefined },
                { label: 'Tokens', value: formatNumber(detail.total_tokens) },
                { label: 'Cost', value: numeric(detail.estimated_cost) ? formatMoney(detail.estimated_cost) : '-' },
                { label: 'Total time', value: formatMs(detail.total_duration_ms ?? detail.traces.reduce((sum, trace) => sum + numeric(trace.duration_ms), 0)) },
              ]} />
              <Card flush title="Conversation">
                <ol className="flex flex-col">
                  {detail.traces.map((trace, index) => {
                    const scores = detail.scores.filter(score => score.trace_id === trace.trace_id)
                    const failed = trace.status === 'failed'
                    return (
                      <li key={trace.trace_id} className="border-b border-line px-4 py-4 last:border-b-0">
                        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-fg-subtle">
                          <span className="font-medium text-fg-muted">Turn {index + 1}</span>
                          <StatusBadge status={trace.status} />
                          <span>{formatRelative(trace.started_at)}</span>
                          <span>· {formatMs(trace.duration_ms)}</span>
                          {numeric(trace.estimated_cost) > 0 && <span>· {formatMoney(trace.estimated_cost)}</span>}
                          {scores.map(score => <Badge key={score.score_id} tone={score.value === 0 || score.passed === false ? 'danger' : 'success'}>{score.name}: {score.label ?? String(score.value)}</Badge>)}
                          <Button size="xs" variant="ghost" className="ml-auto" onClick={() => onTraceSelect(trace.trace_id)}>Open trace<ArrowUpRight /></Button>
                        </div>
                        <div className="flex flex-col gap-2.5">
                          <Bubble role="user" value={trace.input} />
                          <Bubble role="assistant" value={failed ? trace.error_message ?? trace.output : trace.output} danger={failed} />
                        </div>
                      </li>
                    )
                  })}
                </ol>
              </Card>
            </>
          )}
        </div>
      </div>
    </>
  )
}

function Bubble({ role, value, danger = false }: { role: 'user' | 'assistant'; value: unknown; danger?: boolean }) {
  if (value === null || value === undefined || value === '')
    return null
  const text = typeof value === 'string' ? value : jsonPreview(value)
  const user = role === 'user'
  return (
    <div className={cn('flex items-start gap-2.5', user ? '' : 'flex-row-reverse text-right')}>
      <span className={cn('grid size-7 shrink-0 place-items-center rounded-full [&_svg]:size-3.5', user ? 'bg-surface-3 text-fg-muted' : danger ? 'bg-danger-soft text-danger-text' : 'bg-accent-soft text-accent-text')}>
        {user ? <User /> : <Bot />}
      </span>
      <div className={cn('max-w-[80%] rounded-2xl px-3.5 py-2 text-left text-[13.5px] leading-6 whitespace-pre-wrap break-words', user ? 'rounded-tl-sm bg-surface-2 text-fg' : danger ? 'rounded-tr-sm border border-danger/30 bg-danger-soft text-danger-text' : 'rounded-tr-sm bg-accent text-accent-fg')}>
        <span className="line-clamp-[12]">{text}</span>
      </div>
    </div>
  )
}
