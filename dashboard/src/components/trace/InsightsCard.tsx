import { AlertTriangle, CheckCircle2, Info, OctagonAlert, Sparkles, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import { createScore } from '../../api'
import { cn } from '../../lib/utils'
import type { ScoreRecord, SpanRecord, TraceInsights } from '../../types'
import { errorText, formatMoney, formatMs } from '../../utils/format'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'

export function InsightsCard({
  traceId,
  insights,
  scores,
  spans,
  onSelectSpan,
}: {
  traceId: string
  insights: TraceInsights | null | undefined
  scores: ScoreRecord[]
  spans: SpanRecord[]
  onSelectSpan: (span: SpanRecord) => void
}) {
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null)
  const [feedbackError, setFeedbackError] = useState('')
  const findings = insights?.findings ?? []

  async function sendFeedback(value: 'up' | 'down') {
    try {
      await createScore({ trace_id: traceId, name: 'user_feedback', value: value === 'up', source: 'dashboard' })
      setFeedback(value)
      setFeedbackError('')
    }
    catch (caught) {
      setFeedbackError(errorText(caught))
    }
  }

  const jump = (spanId?: string | null) => {
    const span = spans.find(item => item.span_id === spanId)
    if (span)
      onSelectSpan(span)
  }

  return (
    <Card
      flush
      title="Insights"
      icon={<Sparkles />}
      description={insights?.summary}
      actions={(
        <div className="flex items-center gap-1">
          <span className="mr-1 hidden text-xs text-fg-subtle sm:inline">{feedback ? 'Thanks for the feedback' : 'Was this run good?'}</span>
          <Button size="icon-sm" variant={feedback === 'up' ? 'subtle' : 'ghost'} aria-label="Mark trace as good" aria-pressed={feedback === 'up'} onClick={() => void sendFeedback('up')}><ThumbsUp className={cn(feedback === 'up' && 'text-success')} /></Button>
          <Button size="icon-sm" variant={feedback === 'down' ? 'subtle' : 'ghost'} aria-label="Mark trace as bad" aria-pressed={feedback === 'down'} onClick={() => void sendFeedback('down')}><ThumbsDown className={cn(feedback === 'down' && 'text-danger')} /></Button>
        </div>
      )}
    >
      {feedbackError && <p className="px-4 pt-3 text-xs text-danger-text">{feedbackError}</p>}
      {findings.length === 0
        ? (
            <div className="flex items-center gap-2 px-4 py-3 text-[13px] text-fg-muted">
              <CheckCircle2 className="size-4 text-success" />
              No problems detected: no failures, loops, repeated prompts, or runaway context.
            </div>
          )
        : (
            <ul className="divide-y divide-line">
              {findings.map((finding, index) => {
                const high = finding.severity === 'high'
                const warning = finding.severity === 'warning'
                return (
                  <li key={`${finding.kind}-${index}`}>
                    <button className={cn('flex w-full items-start gap-3 px-4 py-2.5 text-left', finding.span_id ? 'hover:bg-surface-2/60' : 'cursor-default')} onClick={() => jump(finding.span_id)}>
                      <span className={cn('mt-0.5 grid size-6 shrink-0 place-items-center rounded-md [&_svg]:size-3.5', high ? 'bg-danger-soft text-danger-text' : warning ? 'bg-warning-soft text-warning-text' : 'bg-info-soft text-info-text')}>
                        {high ? <OctagonAlert /> : warning ? <AlertTriangle /> : <Info />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-medium text-fg">{finding.message}</span>
                        {finding.path && finding.path.length > 1 && <span className="block truncate font-mono text-[11.5px] text-fg-subtle">{finding.path.join(' → ')}</span>}
                      </span>
                      <Badge tone={high ? 'danger' : warning ? 'warning' : 'info'}>{finding.kind.replaceAll('_', ' ')}</Badge>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
      {((insights?.slowest_spans?.length ?? 0) > 0 || scores.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-line px-4 py-2.5">
          {insights?.slowest_spans?.slice(0, 3).map(span => (
            <button key={span.span_id} className="inline-flex h-6 items-center gap-1 rounded-md border border-line px-2 text-xs text-fg-muted hover:border-line-strong hover:text-fg" onClick={() => jump(span.span_id)}>
              <span className="text-fg-subtle">slow</span>{span.label}<span className="tabular font-medium text-fg">{formatMs(span.self_time_ms)}</span>
            </button>
          ))}
          {insights?.costliest_calls?.slice(0, 2).map(call => (
            <button key={call.span_id} className="inline-flex h-6 items-center gap-1 rounded-md border border-line px-2 text-xs text-fg-muted hover:border-line-strong hover:text-fg" onClick={() => jump(call.span_id)}>
              <span className="text-fg-subtle">costly</span>{call.model ?? 'model'}<span className="tabular font-medium text-fg">{formatMoney(call.estimated_cost)}</span>
            </button>
          ))}
          {scores.map(score => (
            <Badge key={score.score_id} tone={score.passed === false || score.value === 0 ? 'danger' : 'success'} title={score.comment ?? undefined}>
              {score.name}: {score.label ?? String(score.value ?? '-')}
            </Badge>
          ))}
        </div>
      )}
    </Card>
  )
}
