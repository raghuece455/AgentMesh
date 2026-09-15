import { ArrowDownRight, ArrowUpRight, Database, FlaskConical, GitCompare, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  addDatasetItems,
  compareExperiments,
  createDataset,
  deleteDatasetItem,
  getDataset,
  getExperiment,
  listDatasets,
  listExperiments,
} from '../api'
import { InlineAction } from '../components/common/Actions'
import { TextField } from '../components/common/Inputs'
import { Badge, CopyableId, StatusBadge } from '../components/common/Badges'
import { AnswerCard, EmptyState, Panel } from '../components/common/Cards'
import { DataTable } from '../components/tables/DataTable'
import type { ComparedResult, DatasetDetail, DatasetSummary, EvaluatorScore, ExperimentComparison, ExperimentDetail, ExperimentSummary } from '../types'
import { errorText, formatCost, formatMs, formatTime, jsonPreview } from '../utils/format'

type View = { kind: 'experiments' } | { kind: 'items' } | { kind: 'experiment'; id: string } | { kind: 'compare'; base: string; candidate: string }

export function DatasetsPage({ refreshKey, initialExperimentId, onTraceSelect }: { refreshKey: string | null; initialExperimentId?: string; onTraceSelect: (traceId: string) => void }) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [selected, setSelected] = useState('')
  const [dataset, setDataset] = useState<DatasetDetail | null>(null)
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([])
  const [view, setView] = useState<View>(initialExperimentId ? { kind: 'experiment', id: initialExperimentId } : { kind: 'experiments' })
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  const reload = useCallback(() => setVersion(value => value + 1), [])

  useEffect(() => {
    listDatasets().then(setDatasets).catch(caught => setError(errorText(caught)))
  }, [refreshKey, version])

  const activeName = selected || datasets[0]?.name || ''
  useEffect(() => {
    if (!activeName) {
      setDataset(null)
      setExperiments([])
      return
    }
    let cancelled = false
    Promise.all([getDataset(activeName), listExperiments(activeName)])
      .then(([detail, runs]) => {
        if (cancelled)
          return
        setDataset(detail)
        setExperiments(runs)
        setError('')
      })
      .catch(caught => { if (!cancelled) setError(errorText(caught)) })
    return () => { cancelled = true }
  }, [activeName, refreshKey, version])

  // Deep links (?experiment=...) may point at another dataset: select it once the experiment loads.
  useEffect(() => {
    if (!initialExperimentId)
      return
    getExperiment(initialExperimentId).then(detail => { if (detail.dataset_name) setSelected(detail.dataset_name) }).catch(() => undefined)
  }, [initialExperimentId])

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col gap-4">
        <Panel title="Datasets" icon={<Database className="size-4" />}>
          {datasets.length === 0
            ? <EmptyState icon={<Database className="size-5" />} title="No datasets yet" detail="Create one below, click Add to dataset on any trace, or run: agentmesh datasets import my-set items.jsonl" />
            : (
                <DataTable
                  rows={datasets}
                  minWidth={240}
                  onRow={row => { setSelected(row.name); setView({ kind: 'experiments' }) }}
                  selectedRow={row => row.name === activeName}
                  columns={[
                    { label: 'Dataset', render: row => <div><div className="font-semibold break-all text-white">{row.name}</div><div className="text-xs/5 text-white/50">{row.last_experiment_at ? `last run ${formatTime(row.last_experiment_at)}` : 'no runs yet'}</div></div>, sortValue: row => row.name },
                    { label: 'Items', render: row => row.item_count, sortValue: row => row.item_count },
                    { label: 'Runs', render: row => row.experiment_count, sortValue: row => row.experiment_count },
                  ]}
                />
              )}
        </Panel>
        <NewDatasetForm onCreated={name => { setSelected(name); setView({ kind: 'items' }); reload() }} />
      </div>

      <Panel
        title={dataset ? dataset.name : 'Dataset'}
        icon={<FlaskConical className="size-4" />}
        actions={dataset && (
          <div className="flex flex-wrap gap-1.5">
            {(['experiments', 'items'] as const).map(kind => (
              <button key={kind} className={`vision-pill px-3 py-1.5 text-xs/5 ${view.kind === kind || (kind === 'experiments' && (view.kind === 'experiment' || view.kind === 'compare')) ? 'vision-pill-active' : ''}`} onClick={() => setView({ kind })}>
                {kind === 'experiments' ? `Experiments (${experiments.length})` : `Items (${dataset.item_count})`}
              </button>
            ))}
          </div>
        )}
      >
        {error && <EmptyState title="Could not load datasets" detail={error} />}
        {!error && !dataset && <EmptyState title="Select or create a dataset" />}
        {dataset && (
          <div className="flex flex-col gap-4">
            {dataset.description && <p className="text-sm/6 text-white/68">{dataset.description}</p>}
            {view.kind === 'experiments' && <ExperimentsView key={dataset.dataset_id} dataset={dataset.name} experiments={experiments} onOpen={id => setView({ kind: 'experiment', id })} onCompare={(base, candidate) => setView({ kind: 'compare', base, candidate })} />}
            {view.kind === 'items' && <ItemsView dataset={dataset} onChanged={reload} onTraceSelect={onTraceSelect} />}
            {view.kind === 'experiment' && <ExperimentView id={view.id} onBack={() => setView({ kind: 'experiments' })} onTraceSelect={onTraceSelect} />}
            {view.kind === 'compare' && <CompareView base={view.base} candidate={view.candidate} onBack={() => setView({ kind: 'experiments' })} onTraceSelect={onTraceSelect} />}
          </div>
        )}
      </Panel>
    </div>
  )
}

function ExperimentsView({ dataset, experiments, onOpen, onCompare }: { dataset: string; experiments: ExperimentSummary[]; onOpen: (id: string) => void; onCompare: (base: string, candidate: string) => void }) {
  const [base, setBase] = useState('')
  const [candidate, setCandidate] = useState('')
  const evaluators = useMemo(() => [...new Set(experiments.flatMap(experiment => Object.keys(experiment.summary.scores ?? {})))], [experiments])
  if (experiments.length === 0) {
    return (
      <div className="flex flex-col gap-3">
        <EmptyState icon={<FlaskConical className="size-5" />} title="No experiments on this dataset yet" detail="Run your agent over its items and score every answer:" />
        <RunSnippet dataset={dataset} />
      </div>
    )
  }
  // Only use a selection that belongs to this dataset's experiments.
  const listed = (id: string) => experiments.some(experiment => experiment.experiment_id === id)
  const baseId = listed(base) ? base : experiments[1]?.experiment_id ?? experiments[0].experiment_id
  const candidateId = listed(candidate) ? candidate : experiments[0].experiment_id
  return (
    <div className="flex flex-col gap-3">
      {experiments.length > 1 && (
        <div className="flex flex-wrap items-end gap-2 rounded-2xl border border-white/12 bg-slate-950/22 p-3">
          <ExperimentSelect label="Baseline" value={baseId} experiments={experiments} onChange={setBase} />
          <ExperimentSelect label="Candidate" value={candidateId} experiments={experiments} onChange={setCandidate} />
          <button className="trace-action" disabled={baseId === candidateId} onClick={() => onCompare(baseId, candidateId)}><GitCompare className="size-4" />Compare</button>
        </div>
      )}
      <DataTable
        rows={experiments}
        minWidth={760}
        onRow={row => onOpen(row.experiment_id)}
        columns={[
          { label: 'Experiment', render: row => <div><div className="font-semibold text-white">{row.name}</div><div className="text-xs/5 text-white/50">{formatTime(row.started_at)}{row.metadata?.sdk ? ` / ${String(row.metadata.sdk)}` : ''}</div></div>, sortValue: row => Date.parse(row.started_at) },
          { label: 'Status', render: row => <StatusBadge status={row.status === 'completed' ? 'succeeded' : row.status} />, sortValue: row => row.status },
          { label: 'Items', render: row => <span>{row.summary.items}{row.summary.errors ? <span className="ml-1"><Badge tone="danger">{row.summary.errors} {row.summary.errors === 1 ? 'error' : 'errors'}</Badge></span> : null}</span>, sortValue: row => row.summary.items },
          ...evaluators.map(name => ({
            label: name,
            render: (row: ExperimentSummary) => <ScoreCell stats={row.summary.scores?.[name]} />,
            sortValue: (row: ExperimentSummary) => row.summary.scores?.[name]?.mean ?? -1,
          })),
          { label: 'Latency', render: row => formatMs(row.summary.avg_latency_ms), sortValue: row => row.summary.avg_latency_ms ?? 0 },
          { label: 'Cost', render: row => formatCost(row.total_cost), sortValue: row => row.total_cost },
        ]}
      />
      <p className="text-xs/5 text-white/50">Gate a release in CI: agentmesh experiments run --dataset {dataset} --task app.py:answer --evaluator exact_match --fail-under exact_match=0.9</p>
    </div>
  )
}

function RunSnippet({ dataset }: { dataset: string }) {
  return (
    <pre className="vision-scroll overflow-auto rounded-2xl bg-slate-950/60 p-3 text-xs/5 text-sky-50"><code>{`# Python
result = agentmesh.run_experiment(
    "${dataset}",
    task=my_agent,
    evaluators=[ExactMatch(), LLMJudge("correctness", judge=call_llm)],
    name="prompt-v2",
)

// TypeScript
await runExperiment({ dataset: "${dataset}", task: myAgent, evaluators: [exactMatch(), llmJudge({ judge })] })`}</code></pre>
  )
}

function ExperimentSelect({ label, value, experiments, onChange }: { label: string; value: string; experiments: ExperimentSummary[]; onChange: (id: string) => void }) {
  return (
    <label className="block min-w-48 flex-1">
      <span className="text-xs/5 font-medium text-white/56">{label}</span>
      <select className="mt-1 h-9 w-full rounded-2xl border border-white/14 bg-slate-950/36 px-3 text-sm/6 font-medium text-white" value={value} onChange={event => onChange(event.target.value)}>
        {experiments.map(experiment => <option key={experiment.experiment_id} value={experiment.experiment_id}>{experiment.name} ({formatTime(experiment.started_at)})</option>)}
      </select>
    </label>
  )
}

function ScoreCell({ stats }: { stats?: { mean: number | null; pass_rate: number | null } }) {
  if (!stats || stats.mean === null)
    return <span className="text-white/40">-</span>
  const tone = stats.mean >= 0.8 ? 'good' : stats.mean >= 0.5 ? 'warn' : 'danger'
  return (
    <span className="inline-flex flex-col">
      <Badge tone={tone}>{stats.mean.toFixed(2)}</Badge>
      {stats.pass_rate !== null && <span className="text-xs/5 text-white/50">{Math.round(stats.pass_rate * 100)}% pass</span>}
    </span>
  )
}

function ExperimentView({ id, onBack, onTraceSelect }: { id: string; onBack: () => void; onTraceSelect: (traceId: string) => void }) {
  const [detail, setDetail] = useState<ExperimentDetail | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    getExperiment(id).then(setDetail).catch(caught => setError(errorText(caught)))
  }, [id])
  if (error)
    return <EmptyState title="Could not load experiment" detail={error} />
  if (!detail)
    return <EmptyState title="Loading experiment" />
  return (
    <div className="flex flex-col gap-3">
      <BackBar onBack={onBack} title={`Experiment ${detail.name}`} extra={<CopyableId value={detail.experiment_id} />} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <AnswerCard label="Items" value={detail.summary.items} />
        <AnswerCard label="Errors" value={detail.summary.errors} tone={detail.summary.errors ? 'danger' : 'good'} />
        <AnswerCard label="Avg latency" value={formatMs(detail.summary.avg_latency_ms)} />
        <AnswerCard label="Cost" value={formatCost(detail.total_cost)} />
        <AnswerCard label="Evaluators" value={detail.evaluators.join(', ') || '-'} />
      </div>
      <DataTable
        rows={detail.results}
        minWidth={820}
        columns={[
          { label: 'Input', render: row => <Preview value={row.input} />, sortValue: row => jsonPreview(row.input) },
          { label: 'Expected', render: row => <Preview value={row.expected} />, sortValue: row => jsonPreview(row.expected) },
          { label: 'Output', render: row => row.error ? <span className="text-rose-100">{row.error}</span> : <Preview value={row.output} />, sortValue: row => jsonPreview(row.output) },
          { label: 'Scores', render: row => <Scores scores={row.scores} />, sortValue: row => averageScore(row.scores) },
          { label: 'Latency', render: row => formatMs(row.duration_ms), sortValue: row => row.duration_ms ?? 0 },
          { label: '', render: row => row.trace_id ? <InlineAction icon={<ArrowUpRight className="size-3" />} label="Trace" onClick={() => onTraceSelect(row.trace_id!)} /> : null },
        ]}
      />
    </div>
  )
}

function CompareView({ base, candidate, onBack, onTraceSelect }: { base: string; candidate: string; onBack: () => void; onTraceSelect: (traceId: string) => void }) {
  const [comparison, setComparison] = useState<ExperimentComparison | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    compareExperiments(base, candidate).then(setComparison).catch(caught => setError(errorText(caught)))
  }, [base, candidate])
  if (error)
    return <EmptyState title="Could not compare experiments" detail={error} />
  if (!comparison)
    return <EmptyState title="Comparing experiments" />
  const { counts } = comparison
  return (
    <div className="flex flex-col gap-3">
      <BackBar onBack={onBack} title={`${comparison.base.name} vs ${comparison.candidate.name}`} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <AnswerCard label="Regressed" value={counts.regressed} tone={counts.regressed ? 'danger' : 'good'} />
        <AnswerCard label="Improved" value={counts.improved} tone={counts.improved ? 'good' : 'neutral'} />
        <AnswerCard label="Unchanged" value={counts.unchanged} />
        <AnswerCard label="Cost change" value={`${comparison.cost_delta >= 0 ? '+' : '-'}${formatCost(Math.abs(comparison.cost_delta))}`} tone={comparison.cost_delta > 0 ? 'warn' : 'neutral'} />
      </div>
      <div className="flex flex-wrap gap-2">
        {Object.entries(comparison.score_deltas).map(([name, delta]) => (
          <div key={name} className="rounded-2xl border border-white/12 bg-slate-950/22 px-3 py-2 text-sm/6">
            <span className="font-semibold text-white">{name}</span>{' '}
            <span className="text-white/60">{delta.base?.toFixed(2) ?? '-'} {'->'} {delta.candidate?.toFixed(2) ?? '-'}</span>{' '}
            {delta.delta !== null && <DeltaBadge value={delta.delta} />}
          </div>
        ))}
      </div>
      <DataTable
        rows={comparison.items}
        minWidth={860}
        columns={[
          { label: 'Change', render: row => <ChangeBadge change={row.change} />, sortValue: row => ['regressed', 'improved', 'added', 'removed', 'unchanged'].indexOf(row.change) },
          { label: 'Input', render: row => <Preview value={row.input} />, sortValue: row => jsonPreview(row.input) },
          { label: 'Expected', render: row => <Preview value={row.expected} /> },
          { label: 'Baseline', render: row => <ComparedCell result={row.base} onTraceSelect={onTraceSelect} /> },
          { label: 'Candidate', render: row => <ComparedCell result={row.candidate} onTraceSelect={onTraceSelect} /> },
        ]}
      />
    </div>
  )
}

function ComparedCell({ result, onTraceSelect }: { result: ComparedResult | null; onTraceSelect: (traceId: string) => void }) {
  if (!result)
    return <span className="text-white/40">not run</span>
  return (
    <div className="flex max-w-60 flex-col gap-1">
      {result.error ? <span className="text-sm/5 text-rose-100">{result.error}</span> : <Preview value={result.output} />}
      <div className="flex flex-wrap items-center gap-1">
        <Scores scores={result.scores} />
        {result.trace_id && <InlineAction icon={<ArrowUpRight className="size-3" />} label="Trace" onClick={() => onTraceSelect(result.trace_id!)} />}
      </div>
    </div>
  )
}

function ItemsView({ dataset, onChanged, onTraceSelect }: { dataset: DatasetDetail; onChanged: () => void; onTraceSelect: (traceId: string) => void }) {
  const [input, setInput] = useState('')
  const [expected, setExpected] = useState('')
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      await addDatasetItems(dataset.name, [{ input: parseLoose(input), expected: expected.trim() ? parseLoose(expected) : undefined }])
      setInput('')
      setExpected('')
      setError('')
      onChanged()
    }
    catch (caught) {
      setError(errorText(caught))
    }
  }
  return (
    <div className="flex flex-col gap-3">
      <form className="grid grid-cols-1 gap-2 rounded-2xl border border-white/12 bg-slate-950/22 p-3 md:grid-cols-[1fr_1fr_auto]" onSubmit={event => void submit(event)}>
        <TextField label="Input (JSON or text)" value={input} onChange={setInput} placeholder='{"question": "How do refunds work?"}' />
        <TextField label="Expected output (optional)" value={expected} onChange={setExpected} placeholder="Refunds take 5 business days" />
        <button type="submit" className="trace-action self-end" disabled={!input.trim()}><Plus className="size-4" />Add item</button>
        {error && <p className="text-xs/5 text-rose-100 md:col-span-3">{error}</p>}
      </form>
      <DataTable
        rows={dataset.items}
        minWidth={760}
        columns={[
          { label: 'Input', render: row => <Preview value={row.input} />, sortValue: row => jsonPreview(row.input) },
          { label: 'Expected', render: row => <Preview value={row.expected} />, sortValue: row => jsonPreview(row.expected) },
          { label: 'Source', render: row => row.source_trace_id ? <InlineAction icon={<ArrowUpRight className="size-3" />} label="From trace" onClick={() => onTraceSelect(row.source_trace_id!)} /> : <Badge outline>manual</Badge> },
          { label: 'Added', render: row => formatTime(row.created_at), sortValue: row => Date.parse(row.created_at) },
          { label: '', render: row => <InlineAction icon={<Trash2 className="size-3" />} label="Remove" tone="danger" onClick={() => void deleteDatasetItem(dataset.name, row.item_id).then(onChanged)} /> },
        ]}
      />
    </div>
  )
}

function NewDatasetForm({ onCreated }: { onCreated: (name: string) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      const created = await createDataset({ name: name.trim(), description: description.trim() || undefined })
      setName('')
      setDescription('')
      setError('')
      onCreated(created.name)
    }
    catch (caught) {
      setError(errorText(caught))
    }
  }
  return (
    <Panel title="New dataset" icon={<Plus className="size-4" />}>
      <form className="flex flex-col gap-2" onSubmit={event => void submit(event)}>
        <TextField label="Name" value={name} onChange={setName} placeholder="refund-questions" />
        <TextField label="Description" value={description} onChange={setDescription} placeholder="Real support questions with approved answers" />
        <button type="submit" className="trace-action self-start" disabled={!name.trim()}><Plus className="size-4" />Create dataset</button>
        {error && <p className="text-xs/5 text-rose-100">{error}</p>}
      </form>
    </Panel>
  )
}


function BackBar({ onBack, title, extra }: { onBack: () => void; title: string; extra?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button className="trace-action" onClick={onBack}>Back</button>
      <span className="text-sm/6 font-semibold text-white">{title}</span>
      {extra}
    </div>
  )
}

function Scores({ scores }: { scores: EvaluatorScore[] }) {
  if (!scores?.length)
    return <span className="text-white/40">-</span>
  return (
    <span className="flex flex-wrap gap-1">
      {scores.map(score => (
        <span key={score.name} title={score.comment ?? undefined}>
          <Badge tone={score.passed === false || score.score === 0 ? 'danger' : score.passed === true || (score.score ?? 0) >= 0.8 ? 'good' : score.label === 'error' ? 'danger' : 'warn'}>
            {score.name}: {score.score !== null && score.score !== undefined ? score.score.toFixed(2) : score.label ?? String(score.passed)}
          </Badge>
        </span>
      ))}
    </span>
  )
}

function ChangeBadge({ change }: { change: string }) {
  if (change === 'regressed')
    return <Badge tone="danger"><ArrowDownRight className="size-3" />regressed</Badge>
  if (change === 'improved')
    return <Badge tone="good"><ArrowUpRight className="size-3" />improved</Badge>
  return <Badge outline>{change}</Badge>
}

function DeltaBadge({ value }: { value: number }) {
  if (Math.abs(value) < 1e-9)
    return <Badge outline>0.00</Badge>
  return <Badge tone={value > 0 ? 'good' : 'danger'}>{value > 0 ? '+' : ''}{value.toFixed(2)}</Badge>
}

function Preview({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '')
    return <span className="text-white/40">-</span>
  const text = typeof value === 'string' ? value : jsonPreview(value)
  return <span className="line-clamp-3 max-w-60 whitespace-pre-wrap break-words text-sm/5 text-white/84" title={text}>{text}</span>
}

function averageScore(scores: EvaluatorScore[]): number {
  const values = scores.map(score => score.score).filter((score): score is number => typeof score === 'number')
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : -1
}

function parseLoose(text: string): unknown {
  try {
    return JSON.parse(text)
  }
  catch {
    return text
  }
}
