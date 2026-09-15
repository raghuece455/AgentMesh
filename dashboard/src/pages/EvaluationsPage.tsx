import { ArrowRight, ClipboardCheck, FlaskConical, Play, ShieldCheck, Sparkles, Target } from 'lucide-react'
import type { Section } from '../appTypes'
import { Badge, StatusDot } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Callout, Card, EmptyState, Meter, PageHeader } from '../components/ui/Card'
import { DataTable } from '../components/ui/DataTable'
import { StatCard } from '../components/ui/Stat'
import type { EvaluationRecord, EvaluationSummary } from '../types'
import { formatNumber, formatPercent, formatRelative } from '../utils/format'

export function EvaluationsPage({ summary, evaluations, onRun, onTrace, onSection }: { summary: EvaluationSummary | null; evaluations: EvaluationRecord[]; onRun: () => void; onTrace: (traceId: string) => void; onSection: (section: Section) => void }) {
  const quality = [...(summary?.quality_by_workflow ?? [])].sort((a, b) => a.score - b.score)
  return (
    <>
      <PageHeader
        title="Evaluations"
        description="Scores from evaluators, LLM judges, and user feedback, attached to traces."
        actions={<Button icon={<Play />} onClick={onRun}>Run sample evaluation</Button>}
      />
      <Callout
        tone="info"
        icon={<FlaskConical />}
        title="Testing a prompt or model change?"
        actions={<Button size="sm" onClick={() => onSection('datasets')}>Open datasets<ArrowRight /></Button>}
      >
        Run an experiment over a dataset to compare versions item by item, and gate releases in CI.
      </Callout>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Task success" icon={<Target />} value={summary?.task_success_score == null ? '-' : formatPercent(summary.task_success_score)} sub={`${formatNumber(summary?.count ?? 0)} evaluations`} />
        <StatCard label="Schema pass rate" icon={<ShieldCheck />} value={summary?.schema_validation_pass_rate == null ? '-' : formatPercent(summary.schema_validation_pass_rate)} />
        <StatCard label="RAG faithfulness" icon={<Sparkles />} value={summary?.rag_faithfulness_score == null ? '-' : formatPercent(summary.rag_faithfulness_score)} sub={summary?.rag_faithfulness_score == null ? 'No faithfulness evaluator yet' : undefined} />
        <StatCard label="Regression status" icon={<ClipboardCheck />} value={<span className="capitalize">{summary?.regression_status ?? '-'}</span>} tone={summary?.regression_status === 'failing' ? 'danger' : 'neutral'} />
      </div>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
        <Card title="Quality by workflow" description="Lowest first">
          {quality.length === 0
            ? <EmptyState title="No scored workflows" />
            : (
                <ul className="flex flex-col gap-3">
                  {quality.map(item => (
                    <li key={item.name} className="flex flex-col gap-1.5">
                      <div className="flex items-baseline justify-between gap-2 text-[13px]">
                        <span className="truncate text-fg">{item.name}</span>
                        <span className="tabular font-medium text-fg">{formatPercent(item.score)}</span>
                      </div>
                      <Meter value={item.score} max={1} tone={item.score >= 0.8 ? 'success' : item.score >= 0.5 ? 'warning' : 'danger'} />
                    </li>
                  ))}
                </ul>
              )}
        </Card>
        <Card flush title="Recent evaluations" className="xl:col-span-2">
          <DataTable
            rows={evaluations}
            rowKey={row => row.evaluation_id}
            minWidth={680}
            onRow={row => row.trace_id && onTrace(row.trace_id)}
            empty={<EmptyState icon={<ClipboardCheck />} title="No evaluations yet" />}
            columns={[
              { label: 'Evaluator', sortValue: row => row.evaluator, render: row => <span className="flex items-center gap-2"><StatusDot status={row.passed === false ? 'failed' : row.passed ? 'succeeded' : 'unknown'} /><span className="flex flex-col"><span className="font-medium text-fg">{row.evaluator}</span><span className="text-xs text-fg-subtle">{row.evaluator_type}</span></span></span> },
              { label: 'Target', sortValue: row => row.workflow_name ?? '', render: row => <span className="text-fg-muted">{row.workflow_name ?? row.agent_name ?? '-'}</span> },
              {
                label: 'Score',
                width: '160px',
                sortValue: row => row.score ?? -1,
                render: row => row.score == null
                  ? <span className="text-fg-subtle">-</span>
                  : <span className="flex items-center gap-2"><Meter value={row.score} max={1} tone={row.score >= 0.8 ? 'success' : row.score >= 0.5 ? 'warning' : 'danger'} /><span className="tabular w-10 text-right">{row.score.toFixed(2)}</span></span>,
              },
              { label: 'Result', sortValue: row => String(row.passed), render: row => row.passed == null ? <span className="text-fg-subtle">-</span> : <Badge tone={row.passed ? 'success' : 'danger'}>{row.passed ? 'passed' : 'failed'}</Badge> },
              { label: 'When', align: 'right', sortValue: row => Date.parse(row.created_at), render: row => <span className="text-fg-muted">{formatRelative(row.created_at)}</span> },
            ]}
          />
        </Card>
      </div>
    </>
  )
}
