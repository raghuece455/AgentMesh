import { ArrowDownRight, ArrowLeft, ArrowUpRight, Database, FlaskConical, GitCompare, Plus, Trash2 } from 'lucide-react'
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
import { Badge, StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, PageHeader, Skeleton } from '../components/ui/Card'
import { CodeTabs, CopyableId } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Field, Select, Textarea, TextField } from '../components/ui/Field'
import { Drawer } from '../components/ui/Overlay'
import { StatStrip } from '../components/ui/Stat'
import { Tabs } from '../components/ui/Tabs'
import { cn } from '../lib/utils'
import type { ComparedResult, DatasetDetail, DatasetSummary, EvaluatorScore, ExperimentComparison, ExperimentDetail, ExperimentSummary, ScoreStats } from '../types'
import { errorText, formatMoney, formatMs, formatRelative, jsonPreview, numeric } from '../utils/format'

type View = { kind: 'experiments' } | { kind: 'items' } | { kind: 'experiment'; id: string } | { kind: 'compare'; base: string; candidate: string }

export function DatasetsPage({ refreshKey, initialExperimentId, onTraceSelect }: { refreshKey: string | null; initialExperimentId?: string; onTraceSelect: (traceId: string) => void }) {
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null)
  const [selected, setSelected] = useState('')
  const [dataset, setDataset] = useState<DatasetDetail | null>(null)
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([])
  const [view, setView] = useState<View>(initialExperimentId ? { kind: 'experiment', id: initialExperimentId } : { kind: 'experiments' })
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [version, setVersion] = useState(0)
  const reload = useCallback(() => setVersion(value => value + 1), [])

  useEffect(() => {
    listDatasets().then(setDatasets).catch(caught => setError(errorText(caught)))
  }, [refreshKey, version])

  const activeName = selected || datasets?.[0]?.name || ''
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

  const newDataset = (
    <Button variant="primary" icon={<Plus />} onClick={() => setCreating(true)}>New dataset</Button>
  )

  return (
    <>
      <PageHeader title="Datasets & experiments" description="Collect test cases, run your agent over them, and see what a change improved or broke." actions={newDataset} />
      <NewDatasetDrawer open={creating} onClose={() => setCreating(false)} onCreated={name => { setCreating(false); setSelected(name); setView({ kind: 'items' }); reload() }} />

      {datasets === null && !error && <div className="grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)]"><Skeleton className="h-80 rounded-xl" /><Skeleton className="h-80 rounded-xl" /></div>}
      {datasets?.length === 0 && (
        <Card>
          <EmptyState
            icon={<Database />}
            title="No datasets yet"
            detail="Create a dataset here, click Add to dataset on any trace, or import JSONL: agentmesh datasets import my-set items.jsonl"
            action={newDataset}
          />
        </Card>
      )}
      {error && !dataset && <Card><EmptyState title="Could not load datasets" detail={error} /></Card>}

      {datasets && datasets.length > 0 && (
        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
          <Card flush title="Datasets" description={`${datasets.length} total`} className="xl:sticky xl:top-20">
            <ul className="max-h-[70vh] divide-y divide-line overflow-y-auto">
              {datasets.map(item => {
                const active = item.name === activeName
                return (
                  <li key={item.dataset_id}>
                    <button className={cn('flex w-full flex-col gap-0.5 px-4 py-2.5 text-left transition-colors', active ? 'bg-accent-soft/60 shadow-[inset_2px_0_0_var(--accent)]' : 'hover:bg-surface-2/60')} onClick={() => { setSelected(item.name); setView({ kind: 'experiments' }) }}>
                      <span className="truncate text-[13px] font-medium text-fg">{item.name}</span>
                      <span className="text-xs text-fg-subtle">{item.item_count} items · {item.experiment_count} runs{item.last_experiment_at ? ` · ${formatRelative(item.last_experiment_at)}` : ''}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </Card>

          {dataset
            ? (
                <div className="flex min-w-0 flex-col gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <FlaskConical className="size-4 text-accent" />
                      <h2 className="text-base font-semibold text-fg">{dataset.name}</h2>
                    </div>
                    {dataset.description && <p className="mt-0.5 text-[13px] text-fg-muted">{dataset.description}</p>}
                  </div>
                  <Tabs
                    value={view.kind === 'items' ? 'items' : 'experiments'}
                    onChange={kind => setView({ kind })}
                    items={[
                      { value: 'experiments', label: 'Experiments', count: experiments.length },
                      { value: 'items', label: 'Items', count: dataset.item_count },
                    ]}
                  />
                  {view.kind === 'experiments' && <ExperimentsView key={dataset.dataset_id} dataset={dataset.name} experiments={experiments} onOpen={id => setView({ kind: 'experiment', id })} onCompare={(base, candidate) => setView({ kind: 'compare', base, candidate })} />}
                  {view.kind === 'items' && <ItemsView dataset={dataset} onChanged={reload} onTraceSelect={onTraceSelect} />}
                  {view.kind === 'experiment' && <ExperimentView id={view.id} onBack={() => setView({ kind: 'experiments' })} onTraceSelect={onTraceSelect} />}
                  {view.kind === 'compare' && <CompareView base={view.base} candidate={view.candidate} onBack={() => setView({ kind: 'experiments' })} onTraceSelect={onTraceSelect} />}
                </div>
              )
            : <Skeleton className="h-80 rounded-xl" />}
        </div>
      )}
    </>
  )
}

function ExperimentsView({ dataset, experiments, onOpen, onCompare }: { dataset: string; experiments: ExperimentSummary[]; onOpen: (id: string) => void; onCompare: (base: string, candidate: string) => void }) {
  const [base, setBase] = useState('')
  const [candidate, setCandidate] = useState('')
  const evaluators = useMemo(() => [...new Set(experiments.flatMap(experiment => Object.keys(experiment.summary.scores ?? {})))], [experiments])
  if (experiments.length === 0) {
    return (
      <Card>
        <EmptyState icon={<FlaskConical />} title="No experiments on this dataset yet" detail="Run your agent over its items and score every answer:" />
        <RunSnippet dataset={dataset} />
      </Card>
    )
  }
  // Only use a selection that belongs to this dataset's experiments.
  const listed = (id: string) => experiments.some(experiment => experiment.experiment_id === id)
  const baseId = listed(base) ? base : experiments[1]?.experiment_id ?? experiments[0].experiment_id
  const candidateId = listed(candidate) ? candidate : experiments[0].experiment_id
  return (
    <Card flush>
      {experiments.length > 1 && (
        <div className="flex flex-wrap items-end gap-2 border-b border-line p-3">
          <Field label="Baseline" className="min-w-52 flex-1">
            <ExperimentSelect value={baseId} experiments={experiments} onChange={setBase} />
          </Field>
          <Field label="Candidate" className="min-w-52 flex-1">
            <ExperimentSelect value={candidateId} experiments={experiments} onChange={setCandidate} />
          </Field>
          <Button variant="primary" icon={<GitCompare />} disabled={baseId === candidateId} onClick={() => onCompare(baseId, candidateId)}>Compare</Button>
        </div>
      )}
      <DataTable
        rows={experiments}
        rowKey={row => row.experiment_id}
        minWidth={760}
        onRow={row => onOpen(row.experiment_id)}
        columns={[
          { label: 'Experiment', sortValue: row => Date.parse(row.started_at), render: row => <span className="flex flex-col"><span className="font-medium text-fg">{row.name}</span><span className="text-xs text-fg-subtle">{formatRelative(row.started_at)}{row.metadata?.sdk ? ` · ${String(row.metadata.sdk)}` : ''}</span></span> },
          { label: 'Status', sortValue: row => row.status, render: row => <StatusBadge status={row.status === 'completed' ? 'succeeded' : row.status} label={row.status === 'completed' ? 'Completed' : undefined} /> },
          { label: 'Items', align: 'right', sortValue: row => row.summary.items, render: row => <span className="inline-flex items-center gap-1.5">{row.summary.items}{row.summary.errors ? <Badge tone="danger">{row.summary.errors} err</Badge> : null}</span> },
          ...evaluators.map(name => ({
            label: name,
            width: '150px',
            render: (row: ExperimentSummary) => <ScoreCell stats={row.summary.scores?.[name]} />,
            sortValue: (row: ExperimentSummary) => row.summary.scores?.[name]?.mean ?? -1,
          })),
          { label: 'Latency', align: 'right', sortValue: row => row.summary.avg_latency_ms ?? 0, render: row => formatMs(row.summary.avg_latency_ms) },
          { label: 'Cost', align: 'right', sortValue: row => row.total_cost, render: row => numeric(row.total_cost) ? formatMoney(row.total_cost) : <span className="text-fg-subtle">-</span> },
        ]}
      />
      <div className="border-t border-line px-4 py-2.5 font-mono text-[11.5px] text-fg-subtle">
        Gate a release in CI: agentmesh experiments run --dataset {dataset} --task app.py:answer --evaluator exact_match --fail-under exact_match=0.9
      </div>
    </Card>
  )
}

function RunSnippet({ dataset }: { dataset: string }) {
  return (
    <div className="mx-auto w-full max-w-2xl">
      <CodeTabs samples={[
        { label: 'Python', language: 'python', code: `result = agentmesh.run_experiment(\n    "${dataset}",\n    task=my_agent,\n    evaluators=[ExactMatch(), LLMJudge("correctness", judge=call_llm)],\n    name="prompt-v2",\n)` },
        { label: 'TypeScript', language: 'typescript', code: `await runExperiment({\n  dataset: "${dataset}",\n  task: myAgent,\n  evaluators: [exactMatch(), llmJudge({ judge })],\n})` },
        { label: 'CLI', language: 'shell', code: `agentmesh experiments run --dataset ${dataset} --task app.py:answer --evaluator exact_match` },
      ]} />
    </div>
  )
}

function ExperimentSelect({ value, experiments, onChange }: { value: string; experiments: ExperimentSummary[]; onChange: (id: string) => void }) {
  return (
    <Select className="w-full" value={value} onChange={event => onChange(event.target.value)}>
      {experiments.map(experiment => <option key={experiment.experiment_id} value={experiment.experiment_id}>{experiment.name} ({formatRelative(experiment.started_at)})</option>)}
    </Select>
  )
}

function scoreTone(value: number): 'success' | 'warning' | 'danger' {
  return value >= 0.8 ? 'success' : value >= 0.5 ? 'warning' : 'danger'
}

function ScoreCell({ stats }: { stats?: ScoreStats }) {
  if (!stats || stats.mean === null)
    return <span className="text-fg-subtle">-</span>
  const tone = scoreTone(stats.mean)
  return (
    <span className="flex flex-col gap-1">
      <span className="flex items-center justify-between gap-2 text-[13px]">
        <span className="tabular font-semibold text-fg">{stats.mean.toFixed(2)}</span>
        {stats.pass_rate !== null && <span className="text-[11px] text-fg-subtle">{Math.round(stats.pass_rate * 100)}% pass</span>}
      </span>
      <span className="h-1 w-full overflow-hidden rounded-full bg-surface-3">
        <span className={cn('block h-full rounded-full', tone === 'success' ? 'bg-success' : tone === 'warning' ? 'bg-warning' : 'bg-danger')} style={{ width: `${Math.max(Math.min(stats.mean, 1), 0) * 100}%` }} />
      </span>
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
    return <Card><EmptyState title="Could not load experiment" detail={error} /></Card>
  if (!detail)
    return <Skeleton className="h-72 rounded-xl" />
  return (
    <>
      <BackBar onBack={onBack} title={detail.name} extra={<CopyableId value={detail.experiment_id} />} />
      <StatStrip items={[
        { label: 'Items', value: detail.summary.items },
        { label: 'Errors', value: detail.summary.errors, tone: detail.summary.errors ? 'danger' : undefined },
        ...Object.entries(detail.summary.scores ?? {}).map(([name, stats]) => ({ label: name, value: stats.mean === null ? '-' : stats.mean.toFixed(2), tone: stats.mean === null ? undefined : scoreTone(stats.mean) === 'danger' ? 'danger' as const : undefined })),
        { label: 'Avg latency', value: formatMs(detail.summary.avg_latency_ms) },
        { label: 'Cost', value: numeric(detail.total_cost) ? formatMoney(detail.total_cost) : '-' },
      ]} />
      <Card flush>
        <DataTable
          rows={detail.results}
          rowKey={row => row.result_id}
          minWidth={860}
          rowClassName={row => cn(row.error && 'shadow-[inset_2px_0_0_var(--danger)]')}
          columns={[
            { label: 'Input', sortValue: row => jsonPreview(row.input), render: row => <Preview value={row.input} /> },
            { label: 'Expected', sortValue: row => jsonPreview(row.expected), render: row => <Preview value={row.expected} muted /> },
            { label: 'Output', sortValue: row => jsonPreview(row.output), render: row => row.error ? <span className="text-[13px] text-danger-text">{row.error}</span> : <Preview value={row.output} /> },
            { label: 'Scores', sortValue: row => averageScore(row.scores), render: row => <Scores scores={row.scores} /> },
            { label: 'Latency', align: 'right', sortValue: row => row.duration_ms ?? 0, render: row => formatMs(row.duration_ms) },
            { label: '', align: 'right', render: row => row.trace_id ? <Button size="xs" variant="ghost" onClick={() => onTraceSelect(row.trace_id!)}>Trace<ArrowUpRight /></Button> : null },
          ]}
        />
      </Card>
    </>
  )
}

function CompareView({ base, candidate, onBack, onTraceSelect }: { base: string; candidate: string; onBack: () => void; onTraceSelect: (traceId: string) => void }) {
  const [comparison, setComparison] = useState<ExperimentComparison | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    compareExperiments(base, candidate).then(setComparison).catch(caught => setError(errorText(caught)))
  }, [base, candidate])
  if (error)
    return <Card><EmptyState title="Could not compare experiments" detail={error} /></Card>
  if (!comparison)
    return <Skeleton className="h-72 rounded-xl" />
  const { counts } = comparison
  return (
    <>
      <BackBar onBack={onBack} title={<><span className="text-fg-muted">{comparison.base.name}</span> <span className="text-fg-subtle">vs</span> {comparison.candidate.name}</>} />
      <StatStrip items={[
        { label: 'Regressed', value: counts.regressed, tone: counts.regressed ? 'danger' : undefined },
        { label: 'Improved', value: counts.improved, tone: counts.improved ? 'success' : undefined },
        { label: 'Unchanged', value: counts.unchanged },
        { label: 'Added / removed', value: `${counts.added} / ${counts.removed}` },
        { label: 'Cost change', value: signed(comparison.cost_delta, formatMoney, 0.00005), tone: comparison.cost_delta > 0.00005 ? 'warning' : undefined },
        { label: 'Latency change', value: comparison.latency_delta_ms === null ? '-' : signed(comparison.latency_delta_ms, formatMs, 0.5) },
      ]} />
      {Object.keys(comparison.score_deltas).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(comparison.score_deltas).map(([name, delta]) => (
            <div key={name} className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-[13px] shadow-card">
              <span className="font-medium text-fg">{name}</span>
              <span className="tabular text-fg-muted">{delta.base?.toFixed(2) ?? '-'} → {delta.candidate?.toFixed(2) ?? '-'}</span>
              {delta.delta !== null && <DeltaBadge value={delta.delta} />}
            </div>
          ))}
        </div>
      )}
      <Card flush>
        <DataTable
          rows={comparison.items}
          rowKey={row => row.item_id}
          minWidth={900}
          initialSort={{ column: 0, desc: false }}
          rowClassName={row => cn(row.change === 'regressed' && 'bg-danger-soft/40 shadow-[inset_2px_0_0_var(--danger)]', row.change === 'improved' && 'bg-success-soft/40 shadow-[inset_2px_0_0_var(--success)]')}
          columns={[
            { label: 'Change', width: '120px', sortValue: row => ['regressed', 'improved', 'added', 'removed', 'unchanged'].indexOf(row.change), render: row => <ChangeBadge change={row.change} /> },
            { label: 'Input', sortValue: row => jsonPreview(row.input), render: row => <Preview value={row.input} /> },
            { label: 'Expected', render: row => <Preview value={row.expected} muted /> },
            { label: 'Baseline', render: row => <ComparedCell result={row.base} onTraceSelect={onTraceSelect} /> },
            { label: 'Candidate', render: row => <ComparedCell result={row.candidate} onTraceSelect={onTraceSelect} /> },
          ]}
        />
      </Card>
    </>
  )
}

function ComparedCell({ result, onTraceSelect }: { result: ComparedResult | null; onTraceSelect: (traceId: string) => void }) {
  if (!result)
    return <span className="text-fg-subtle">not run</span>
  return (
    <div className="flex max-w-64 flex-col gap-1.5">
      {result.error ? <span className="text-[13px] text-danger-text">{result.error}</span> : <Preview value={result.output} />}
      <div className="flex flex-wrap items-center gap-1">
        {result.scores?.length > 0 && <Scores scores={result.scores} />}
        {result.trace_id && <Button size="xs" variant="ghost" onClick={() => onTraceSelect(result.trace_id!)}>Trace<ArrowUpRight /></Button>}
      </div>
    </div>
  )
}

function ItemsView({ dataset, onChanged, onTraceSelect }: { dataset: DatasetDetail; onChanged: () => void; onTraceSelect: (traceId: string) => void }) {
  const [adding, setAdding] = useState(false)
  const [input, setInput] = useState('')
  const [expected, setExpected] = useState('')
  const [error, setError] = useState('')
  async function submit(event?: FormEvent) {
    event?.preventDefault()
    try {
      await addDatasetItems(dataset.name, [{ input: parseLoose(input), expected: expected.trim() ? parseLoose(expected) : undefined }])
      setInput('')
      setExpected('')
      setError('')
      setAdding(false)
      onChanged()
    }
    catch (caught) {
      setError(errorText(caught))
    }
  }
  return (
    <Card flush title={`${dataset.item_count} items`} actions={<Button size="sm" icon={<Plus />} onClick={() => setAdding(true)}>Add item</Button>}>
      <Drawer
        open={adding}
        onClose={() => setAdding(false)}
        title="Add item"
        description={`Add a test case to ${dataset.name}.`}
        footer={<><Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button><Button variant="primary" icon={<Plus />} disabled={!input.trim()} onClick={() => void submit()}>Add item</Button></>}
      >
        <form className="flex flex-col gap-4" onSubmit={event => void submit(event)}>
          <Field label="Input" hint="JSON or plain text.">
            <Textarea rows={6} value={input} onChange={event => setInput(event.target.value)} placeholder='{"question": "How do refunds work?"}' autoFocus />
          </Field>
          <Field label="Expected output" hint="Optional. Evaluators compare the agent's answer with this.">
            <Textarea rows={4} value={expected} onChange={event => setExpected(event.target.value)} placeholder="Refunds take 5 business days." />
          </Field>
          {error && <p className="text-[13px] text-danger-text">{error}</p>}
        </form>
      </Drawer>
      <DataTable
        rows={dataset.items}
        rowKey={row => row.item_id}
        minWidth={760}
        empty={<EmptyState title="No items" detail="Add items here or from any trace with Add to dataset." />}
        columns={[
          { label: 'Input', sortValue: row => jsonPreview(row.input), render: row => <Preview value={row.input} /> },
          { label: 'Expected', sortValue: row => jsonPreview(row.expected), render: row => <Preview value={row.expected} muted /> },
          { label: 'Source', render: row => row.source_trace_id ? <Button size="xs" variant="ghost" onClick={() => onTraceSelect(row.source_trace_id!)}>From trace<ArrowUpRight /></Button> : <Badge outline>manual</Badge> },
          { label: 'Added', align: 'right', sortValue: row => Date.parse(row.created_at), render: row => <span className="text-fg-muted">{formatRelative(row.created_at)}</span> },
          { label: '', align: 'right', render: row => <Button size="icon-sm" variant="ghost" aria-label="Remove item" className="opacity-0 group-hover:opacity-100 focus:opacity-100" onClick={() => void deleteDatasetItem(dataset.name, row.item_id).then(onChanged)}><Trash2 /></Button> },
        ]}
      />
    </Card>
  )
}

function NewDatasetDrawer({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (name: string) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  async function submit(event?: FormEvent) {
    event?.preventDefault()
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
    <Drawer
      open={open}
      onClose={onClose}
      title="New dataset"
      description="A named set of inputs, with optional expected outputs."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" icon={<Plus />} disabled={!name.trim()} onClick={() => void submit()}>Create dataset</Button></>}
    >
      <form className="flex flex-col gap-4" onSubmit={event => void submit(event)}>
        <TextField label="Name" value={name} onChange={setName} placeholder="refund-questions" hint="Letters, numbers, dashes. No slashes." />
        <TextField label="Description" value={description} onChange={setDescription} placeholder="Real support questions with approved answers" />
        {error && <p className="text-[13px] text-danger-text">{error}</p>}
      </form>
    </Drawer>
  )
}

function BackBar({ onBack, title, extra }: { onBack: () => void; title: ReactNode; extra?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="ghost" icon={<ArrowLeft />} onClick={onBack}>Experiments</Button>
      <span className="text-[14px] font-semibold text-fg">{title}</span>
      {extra}
    </div>
  )
}

function Scores({ scores }: { scores: EvaluatorScore[] }) {
  if (!scores?.length)
    return <span className="text-fg-subtle">-</span>
  return (
    <span className="flex flex-wrap gap-1">
      {scores.map(score => (
        <Badge key={score.name} title={score.comment ?? undefined} tone={score.passed === false || score.score === 0 || score.label === 'error' ? 'danger' : score.passed === true || (score.score ?? 0) >= 0.8 ? 'success' : 'warning'}>
          {score.name} {score.score !== null && score.score !== undefined ? score.score.toFixed(2) : score.label ?? String(score.passed)}
        </Badge>
      ))}
    </span>
  )
}

function ChangeBadge({ change }: { change: string }) {
  if (change === 'regressed')
    return <Badge tone="danger"><ArrowDownRight />regressed</Badge>
  if (change === 'improved')
    return <Badge tone="success"><ArrowUpRight />improved</Badge>
  return <Badge outline>{change}</Badge>
}

function DeltaBadge({ value }: { value: number }) {
  if (Math.abs(value) < 1e-9)
    return <Badge outline>±0.00</Badge>
  return <Badge tone={value > 0 ? 'success' : 'danger'}>{value > 0 ? '+' : ''}{value.toFixed(2)}</Badge>
}

function Preview({ value, muted = false }: { value: unknown; muted?: boolean }) {
  if (value === null || value === undefined || value === '')
    return <span className="text-fg-subtle">-</span>
  const text = typeof value === 'string' ? value : jsonPreview(value)
  return <span className={cn('line-clamp-3 max-w-72 text-[13px] leading-5 whitespace-pre-wrap break-words', muted ? 'text-fg-muted' : 'text-fg')} title={text}>{text}</span>
}

/** "+$0.12", "-40ms", or "no change" when the difference rounds to nothing. */
function signed(value: number, format: (value: number) => string, epsilon: number): string {
  if (Math.abs(value) < epsilon)
    return 'no change'
  return `${value > 0 ? '+' : '-'}${format(Math.abs(value))}`
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
