import { AlertTriangle, Info, Lightbulb, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import { createScore } from '../../api'
import type { ScoreRecord, SpanRecord, TraceInsights } from '../../types'
import { formatCost, formatMs } from '../../utils/format'
import { Badge } from '../common/Badges'
import { Panel } from '../common/Cards'

export function InsightsPanel({
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
      setFeedbackError(caught instanceof Error ? caught.message : 'Could not save feedback')
    }
  }

  function jump(spanId?: string | null) {
    const span = spans.find(item => item.span_id === spanId)
    if (span)
      onSelectSpan(span)
  }

  return (
    <Panel
      title="Insights & Scores"
      icon={<Lightbulb className="size-4" />}
      actions={(
        <div className="flex items-center gap-1.5">
          {feedback && <span className="text-xs/5 text-white/60">Saved</span>}
          <button aria-label="Mark trace as good" className={`rounded-xl border px-2 py-1 ${feedback === 'up' ? 'border-emerald-200/50 bg-emerald-400/24' : 'border-white/14 hover:bg-white/12'}`} onClick={() => void sendFeedback('up')}><ThumbsUp className="size-4 text-white" /></button>
          <button aria-label="Mark trace as bad" className={`rounded-xl border px-2 py-1 ${feedback === 'down' ? 'border-rose-200/50 bg-rose-400/24' : 'border-white/14 hover:bg-white/12'}`} onClick={() => void sendFeedback('down')}><ThumbsDown className="size-4 text-white" /></button>
        </div>
      )}
    >
      {insights?.summary && <p className="mb-3 text-sm/6 text-white/78">{insights.summary}</p>}
      {feedbackError && <p className="mb-3 text-xs/5 text-rose-100">{feedbackError}</p>}
      <div className="flex flex-col gap-2">
        {findings.length === 0 && <p className="text-sm/6 text-white/60">No problems detected: no failures, loops, repeated prompts, or runaway context.</p>}
        {findings.map((finding, index) => (
          <button
            key={`${finding.kind}-${index}`}
            className={`flex items-start gap-2 rounded-2xl border p-3 text-left ${finding.severity === 'high' ? 'border-rose-200/30 bg-rose-500/12' : finding.severity === 'warning' ? 'border-amber-200/30 bg-amber-400/10' : 'border-white/12 bg-slate-950/22'} ${finding.span_id ? 'hover:bg-white/10' : 'cursor-default'}`}
            onClick={() => jump(finding.span_id)}
          >
            {finding.severity === 'info' ? <Info className="mt-0.5 size-4 shrink-0 text-sky-100" /> : <AlertTriangle className={`mt-0.5 size-4 shrink-0 ${finding.severity === 'high' ? 'text-rose-100' : 'text-amber-100'}`} />}
            <span className="min-w-0">
              <span className="block text-sm/6 font-semibold text-white">{finding.message}</span>
              {finding.path && finding.path.length > 1 && <span className="block truncate text-xs/5 text-white/55">{finding.path.join(' > ')}</span>}
            </span>
          </button>
        ))}
      </div>
      {(insights?.slowest_spans?.length ?? 0) > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-xs/5 font-semibold text-white/58">Self-time hotspots</div>
          <div className="flex flex-wrap gap-2">
            {insights?.slowest_spans?.slice(0, 3).map(span => (
              <button key={span.span_id} className="rounded-xl border border-white/12 bg-slate-950/22 px-2 py-1 text-xs/5 text-white/82 hover:bg-white/10" onClick={() => jump(span.span_id)}>
                {span.label} / {formatMs(span.self_time_ms)}
              </button>
            ))}
            {insights?.costliest_calls?.slice(0, 2).map(call => (
              <button key={call.span_id} className="rounded-xl border border-amber-200/20 bg-amber-400/10 px-2 py-1 text-xs/5 text-amber-50 hover:bg-amber-400/18" onClick={() => jump(call.span_id)}>
                {call.model ?? 'model'} / {formatCost(call.estimated_cost, 'estimated')}
              </button>
            ))}
          </div>
        </div>
      )}
      {scores.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-xs/5 font-semibold text-white/58">Scores</div>
          <div className="flex flex-wrap gap-2">
            {scores.map(score => (
              <Badge key={score.score_id} tone={score.passed === false || score.value === 0 ? 'danger' : 'good'}>
                {score.name}: {score.label ?? (score.value ?? '-')}{score.source ? ` (${score.source})` : ''}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}
