import { CheckCircle2, CircleSlash, Eye, FlaskConical, History, MoreHorizontal, OctagonX, Pencil, Play, Plus, Power, ShieldAlert, ShieldCheck, ShieldHalf, Trash2, UserCheck } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { createHalt, createPolicy, deletePolicy, getGuardrailsSummary, listHalts, listPolicies, listPolicyDecisions, releaseHalt, simulatePolicy, updatePolicy, validatePolicy } from '../api'
import { SpanKindIcon } from '../components/trace/SpanKindIcon'
import { Badge, type Tone } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Callout, Card, EmptyState, PageHeader } from '../components/ui/Card'
import { CopyableId } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Switch, TextField, Textarea } from '../components/ui/Field'
import { Drawer, Menu, Toast } from '../components/ui/Overlay'
import { StatCard } from '../components/ui/Stat'
import { Segmented, Tabs } from '../components/ui/Tabs'
import type { GuardrailsSummary, HaltRecord, PolicyDecision, PolicyRecord, PolicySimulation, PolicyValidation } from '../types'
import { errorText, formatDateTime, formatNumber, formatRelative } from '../utils/format'
import type { SpanKind } from '../utils/traces'

type DecisionFilter = '' | 'blocked' | 'would_block' | 'require_approval' | 'warn'

const TEMPLATES: Array<{ id: string; label: string; text: string }> = [
  {
    id: 'runaway',
    label: 'Stop loops and runaway spend',
    text: `name: runaway-agents
description: Stop agents that loop, fan out, or overspend.
mode: monitor            # watch first; switch to enforce when the simulation looks right
limits:                  # per trace
  max_repeated_calls: 3  # the same tool with the same arguments
  max_tool_calls: 100
  max_cost_usd: 5
  max_agent_depth: 4     # agents calling agents calling agents
  max_child_agents: 10   # agents one agent may start
`,
  },
  {
    id: 'production',
    label: 'Protect production',
    text: `name: production-safety
description: Destructive and money-moving tools need a person.
mode: enforce
rules:
  - name: no-production-deletes
    match: {tool: ["delete_*", "drop_*", "truncate_*"], environment: production}
    action: deny
    reason: Deleting production data needs a person.
  - name: payments-need-approval
    match: {tool: ["issue_refund", "transfer_*", "charge_*"]}
    action: require_approval
  - name: secrets-in-tool-input
    match: {kind: tool, input_regex: "(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"}
    action: deny
    reason: A tool call contained what looks like an API key.
approval:
  timeout_seconds: 300   # unanswered approvals are denied
`,
  },
  {
    id: 'swarm',
    label: 'Cap a swarm',
    text: `name: swarm-safety
description: Limits for a whole swarm, counted across every process in it.
mode: monitor              # watch first, then enforce
swarm:
  max_agents: 500          # agents started in one swarm
  max_concurrent_agents: 200
  max_spawn_rate_per_minute: 120
  max_cost_usd: 50
  max_duration_minutes: 30
  # match: {service: research-*}   # only swarms from these services
`,
  },
  {
    id: 'models',
    label: 'Approved models only',
    text: `name: approved-models
mode: enforce
rules:
  - name: approved-models-only
    match: {kind: llm}
    except: {model: ["gpt-4.1*", "gpt-5*", "claude-*"]}
    action: deny
    reason: This model is not on the approved list.
`,
  },
]

const SWARM_LIMIT_LABELS: Record<string, (value: number) => string> = {
  max_agents: value => `${formatNumber(value)} agents`,
  max_concurrent_agents: value => `${formatNumber(value)} at once`,
  max_spawn_rate_per_minute: value => `${formatNumber(value)}/min`,
  max_cost_usd: value => `$${value}`,
  max_tokens: value => `${formatNumber(value)} tokens`,
  max_duration_minutes: value => `${value} min`,
}

const LIMIT_LABELS: Record<string, (value: number) => string> = {
  max_steps: value => `${value} steps`,
  max_llm_calls: value => `${value} LLM calls`,
  max_tool_calls: value => `${value} tool calls`,
  max_calls_per_tool: value => `${value} calls per tool`,
  max_repeated_calls: value => `loops at ${value}`,
  max_cost_usd: value => `$${value}`,
  max_tokens: value => `${formatNumber(value)} tokens`,
  max_duration_seconds: value => `${value}s`,
  max_agent_depth: value => `depth ${value}`,
  max_child_agents: value => `${value} sub-agents`,
}

const HALT_SCOPES: Array<{ value: HaltRecord['scope']; label: string; hint: string }> = [
  { value: 'service', label: 'Service', hint: 'Every agent in one service, e.g. support-bot' },
  { value: 'agent', label: 'Agent', hint: 'One agent by name, wherever it runs' },
  { value: 'swarm', label: 'Swarm', hint: 'Every agent in one swarm, in every process (the swarm id from the Swarms page)' },
  { value: 'trace', label: 'Trace', hint: 'One run, by trace ID' },
  { value: 'all', label: 'Everything', hint: 'Every agent connected to this server' },
]

export function GuardrailsPage({ refreshKey, onTrace, onHaltsChanged }: { refreshKey: string | null; onTrace: (traceId: string) => void; onHaltsChanged: (count: number) => void }) {
  const [summary, setSummary] = useState<GuardrailsSummary | null>(null)
  const [policies, setPolicies] = useState<PolicyRecord[]>([])
  const [decisions, setDecisions] = useState<PolicyDecision[]>([])
  const [halts, setHalts] = useState<HaltRecord[]>([])
  const [haltHistory, setHaltHistory] = useState<HaltRecord[]>([])
  const [unsupported, setUnsupported] = useState(false)
  const [tab, setTab] = useState<'policies' | 'decisions' | 'halts'>('policies')
  const [filter, setFilter] = useState<DecisionFilter>('')
  const [editing, setEditing] = useState<{ policy: PolicyRecord | null; simulate?: boolean } | null>(null)
  const [halting, setHalting] = useState(false)
  const [notice, setNotice] = useState<{ message: string; tone?: 'neutral' | 'danger' | 'success' }>({ message: '' })
  const [version, setVersion] = useState(0)
  const clearNotice = useCallback(() => setNotice({ message: '' }), [])
  const reload = () => setVersion(value => value + 1)

  useEffect(() => {
    Promise.all([getGuardrailsSummary(24), listPolicies(), listPolicyDecisions({ limit: 200, action: filter || undefined }), listHalts(true), listHalts(false)])
      .then(([nextSummary, nextPolicies, nextDecisions, active, history]) => {
        setSummary(nextSummary)
        setPolicies(nextPolicies)
        setDecisions(nextDecisions)
        setHalts(active)
        setHaltHistory(history)
        setUnsupported(false)
        onHaltsChanged(active.length)
      })
      .catch((caught) => {
        if (/failed with 404\b/.test(errorText(caught)))
          setUnsupported(true)
        else
          setNotice({ message: errorText(caught), tone: 'danger' })
      })
  }, [refreshKey, version, filter, onHaltsChanged])

  async function act(action: () => Promise<unknown>, success?: string) {
    try {
      await action()
      if (success)
        setNotice({ message: success, tone: 'success' })
      reload()
    }
    catch (caught) {
      setNotice({ message: errorText(caught), tone: 'danger' })
    }
  }

  if (unsupported) {
    return (
      <>
        <PageHeader title="Guardrails" />
        <Callout tone="warning" icon={<ShieldAlert />} title="This AgentMesh server does not support guardrails">Upgrade the server to 0.5 or later to manage policies and halts.</Callout>
      </>
    )
  }

  const counts = summary?.decisions
  const disabled = policies.filter(policy => !policy.enabled).length
  const monitoring = policies.filter(policy => policy.enabled && policy.mode === 'monitor').length

  return (
    <>
      <PageHeader
        title="Guardrails"
        description="Block, pause, or stop what agents do. Policies are checked before every tool call, LLM call, and agent start."
        actions={(
          <>
            <Button variant="danger" icon={<OctagonX />} onClick={() => setHalting(true)}>Stop agents</Button>
            <Button variant="primary" icon={<Plus />} onClick={() => setEditing({ policy: null })}>New policy</Button>
          </>
        )}
      />
      <Toast message={notice.message} tone={notice.tone} onDone={clearNotice} />
      <HaltDrawer open={halting} onClose={() => setHalting(false)} onCreated={(halt) => { setHalting(false); setNotice({ message: `Stopped ${haltLabel(halt)}.`, tone: 'success' }); reload() }} />
      <PolicyEditor
        key={editing ? `${editing.policy?.policy_id ?? 'new'}-${editing.simulate ? 's' : 'e'}` : 'closed'}
        open={Boolean(editing)}
        policy={editing?.policy ?? null}
        simulateOnOpen={Boolean(editing?.simulate)}
        onClose={() => setEditing(null)}
        onTrace={(traceId) => { setEditing(null); onTrace(traceId) }}
        onSaved={(saved, created) => { setEditing(null); setNotice({ message: `${created ? 'Created' : 'Saved'} ${saved.name}.`, tone: 'success' }); reload() }}
      />

      {halts.length > 0 && (
        <section className="overflow-hidden rounded-xl border border-danger/40 bg-danger-soft">
          <header className="flex flex-wrap items-center gap-x-2 gap-y-0.5 px-4 py-2.5 text-danger-text">
            <OctagonX className="size-4" />
            <h2 className="text-[13.5px] font-semibold whitespace-nowrap">{halts.length === 1 ? 'Agents are stopped' : `${halts.length} halts are active`}</h2>
            <span className="basis-full text-xs text-fg-muted sm:basis-auto">Blocked calls raise AgentHalted in the agent. Running SDKs pick up changes within a few seconds.</span>
          </header>
          <ul className="divide-y divide-danger/20 border-t border-danger/20 bg-surface">
            {halts.map(halt => (
              <li key={halt.halt_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
                <Badge tone="danger">{scopeLabel(halt.scope)}</Badge>
                <span className="font-mono text-[13px] text-fg">{halt.scope === 'all' ? 'every agent' : halt.value}</span>
                {halt.reason && <span className="min-w-0 flex-1 truncate text-[13px] text-fg-muted">{halt.reason}</span>}
                <span className="ml-auto text-xs whitespace-nowrap text-fg-subtle" title={formatDateTime(halt.created_at)}>{formatRelative(halt.created_at)}{halt.created_by ? ` by ${halt.created_by}` : ''}</span>
                <Button size="sm" icon={<Play />} onClick={() => void act(() => releaseHalt(halt.halt_id), `Released ${haltLabel(halt)}.`)}>Release</Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Blocked, 24h" icon={<CircleSlash />} value={formatNumber(counts?.blocked ?? 0)} tone={counts?.blocked ? 'danger' : 'neutral'} sub="Calls stopped before they ran" onClick={() => { setTab('decisions'); setFilter('blocked') }} />
        <StatCard label="Sent for approval, 24h" icon={<UserCheck />} value={formatNumber(counts?.approvals ?? 0)} tone={counts?.approvals ? 'warning' : 'neutral'} sub="Paused until a person decides" onClick={() => { setTab('decisions'); setFilter('require_approval') }} />
        <StatCard label="Would block, 24h" icon={<Eye />} value={formatNumber(counts?.would_block ?? 0)} tone={counts?.would_block ? 'warning' : 'neutral'} sub="From policies in monitor mode" onClick={() => { setTab('decisions'); setFilter('would_block') }} />
        <StatCard label="Enforcing policies" icon={<ShieldCheck />} value={summary?.enforcing_policies ?? 0} sub={`${monitoring} monitoring · ${disabled} off`} onClick={() => setTab('policies')} />
      </div>

      <Card flush bodyClassName="flex flex-col">
        <div className="flex flex-wrap items-center justify-between gap-2 pr-3 pl-2">
          <Tabs
            className="flex-1 border-b-0"
            value={tab}
            onChange={setTab}
            items={[
              { value: 'policies', label: 'Policies', icon: <ShieldHalf />, count: policies.length },
              { value: 'decisions', label: 'Decisions', icon: <ShieldAlert />, count: decisions.length },
              { value: 'halts', label: 'Halt history', icon: <History />, count: haltHistory.length },
            ]}
          />
          {tab === 'decisions' && (
            <Segmented
              size="sm"
              value={filter}
              onChange={setFilter}
              options={[
                { value: '', label: 'All' },
                { value: 'blocked', label: 'Blocked' },
                { value: 'require_approval', label: 'Approvals' },
                { value: 'would_block', label: 'Would block' },
                { value: 'warn', label: 'Warnings' },
              ]}
            />
          )}
        </div>
        <div className="border-t border-line">
          {tab === 'policies' && (policies.length === 0
            ? (
                <EmptyState
                  icon={<ShieldHalf />}
                  title="No policies yet"
                  detail="Start from a template in monitor mode, check what it would have blocked on your recorded traces, then enforce it."
                  action={<Button variant="primary" icon={<Plus />} onClick={() => setEditing({ policy: null })}>New policy</Button>}
                />
              )
            : (
                <DataTable
                  rows={policies}
                  rowKey={row => row.policy_id}
                  minWidth={860}
                  onRow={row => setEditing({ policy: row })}
                  columns={[
                    { label: 'Status', width: '130px', sortValue: row => `${row.enabled ? (row.mode === 'enforce' ? 0 : 1) : 2}`, render: row => <PolicyStatus policy={row} /> },
                    { label: 'Policy', sortValue: row => row.name, render: row => <span className="flex min-w-0 flex-col"><span className="font-medium text-fg">{row.name}</span>{row.description && <span className="truncate text-xs text-fg-subtle">{row.description}</span>}</span> },
                    { label: 'Checks', render: row => <PolicyChecks policy={row} /> },
                    { label: 'Updated', align: 'right', sortValue: row => Date.parse(row.updated_at) || 0, render: row => <span className="whitespace-nowrap text-fg-muted" title={formatDateTime(row.updated_at)}>{formatRelative(row.updated_at)}</span> },
                    {
                      label: '',
                      align: 'right',
                      width: '48px',
                      render: row => (
                        <span onClick={event => event.stopPropagation()}>
                          <Menu
                            trigger={({ toggle }) => <Button size="icon-sm" variant="ghost" aria-label={`Actions for ${row.name}`} onClick={toggle}><MoreHorizontal /></Button>}
                            items={[
                              { label: 'Edit', icon: <Pencil />, onSelect: () => setEditing({ policy: row }) },
                              { label: 'Simulate on recent traces', icon: <FlaskConical />, onSelect: () => setEditing({ policy: row, simulate: true }) },
                              row.mode === 'monitor'
                                ? { label: 'Enforce', icon: <ShieldCheck />, onSelect: () => void act(() => updatePolicy(row.policy_id, { mode: 'enforce' }), `${row.name} is now enforced.`) }
                                : { label: 'Switch to monitor', icon: <Eye />, onSelect: () => void act(() => updatePolicy(row.policy_id, { mode: 'monitor' }), `${row.name} now only records what it would block.`) },
                              { label: row.enabled ? 'Turn off' : 'Turn on', icon: <Power />, onSelect: () => void act(() => updatePolicy(row.policy_id, { enabled: !row.enabled })) },
                              { label: 'Delete', icon: <Trash2 />, danger: true, onSelect: () => void act(() => deletePolicy(row.policy_id), `Deleted ${row.name}.`) },
                            ]}
                          />
                        </span>
                      ),
                    },
                  ]}
                />
              ))}
          {tab === 'decisions' && (
            <DataTable
              rows={decisions}
              rowKey={row => row.decision_id}
              minWidth={1000}
              maxHeight="max-h-[70vh]"
              onRow={row => row.trace_id && onTrace(row.trace_id)}
              rowClassName={row => decisionTone(row) === 'danger' ? 'shadow-[inset_2px_0_0_var(--danger)]' : ''}
              empty={<EmptyState icon={<ShieldCheck />} title={filter ? 'No matching decisions' : 'No decisions yet'} detail="Calls that a policy blocks, pauses, flags, or would block in monitor mode appear here." />}
              columns={[
                { label: 'When', width: '100px', sortValue: row => Date.parse(row.created_at) || 0, render: row => <span className="whitespace-nowrap text-fg-muted" title={formatDateTime(row.created_at)}>{formatRelative(row.created_at)}</span> },
                { label: 'Decision', width: '150px', sortValue: row => decisionLabel(row), render: row => <Badge tone={decisionTone(row)} outline={!row.enforced}>{decisionLabel(row)}</Badge> },
                { label: 'Call', sortValue: row => row.target, render: row => <span className="flex min-w-0 items-center gap-2"><SpanKindIcon kind={kindOf(row.kind)} /><span className="truncate font-mono text-xs text-fg">{row.target}</span></span> },
                { label: 'Rule', sortValue: row => row.rule, render: row => <span className="flex min-w-0 flex-col"><span className="font-mono text-xs text-fg">{row.rule}</span><span className="truncate text-xs text-fg-subtle">{row.policy_name ?? (row.rule === 'halt' ? 'kill switch' : '')}</span></span> },
                { label: 'Reason', className: 'max-w-[340px]', render: row => <span className="line-clamp-2 text-[13px] text-fg-muted" title={row.reason}>{row.reason}</span> },
                { label: 'Agent', sortValue: row => row.agent ?? row.service ?? '', render: row => <span className="flex min-w-0 flex-col text-xs"><span className="truncate text-fg">{row.agent ?? '-'}</span><span className="truncate text-fg-subtle">{row.service}</span></span> },
                { label: 'Trace', align: 'right', render: row => row.trace_id ? <CopyableId value={row.trace_id} /> : <span className="text-fg-subtle">-</span> },
              ]}
            />
          )}
          {tab === 'halts' && (haltHistory.length === 0
            ? <EmptyState icon={<History />} title="No halts yet" detail="Use Stop agents to halt a trace, an agent, a service, or everything at once." />
            : (
                <DataTable
                  rows={haltHistory}
                  rowKey={row => row.halt_id}
                  minWidth={760}
                  columns={[
                    { label: 'Status', width: '110px', sortValue: row => (row.active ? 0 : 1), render: row => row.active ? <Badge tone="danger" dot>Active</Badge> : <Badge outline>Released</Badge> },
                    { label: 'Stopped', render: row => <span className="flex items-center gap-2"><Badge outline>{scopeLabel(row.scope)}</Badge><span className="font-mono text-xs text-fg">{row.scope === 'all' ? 'every agent' : row.value}</span></span> },
                    { label: 'Reason', render: row => <span className="text-[13px] text-fg-muted">{row.reason ?? '-'}</span> },
                    { label: 'Started', align: 'right', sortValue: row => Date.parse(row.created_at) || 0, render: row => <span className="whitespace-nowrap text-fg-muted" title={formatDateTime(row.created_at)}>{formatRelative(row.created_at)}{row.created_by ? ` · ${row.created_by}` : ''}</span> },
                    { label: 'Released', align: 'right', sortValue: row => Date.parse(row.released_at ?? '') || 0, render: row => <span className="whitespace-nowrap text-fg-muted" title={formatDateTime(row.released_at)}>{row.released_at ? `${formatRelative(row.released_at)}${row.released_by ? ` · ${row.released_by}` : ''}` : '-'}</span> },
                  ]}
                />
              ))}
        </div>
      </Card>
    </>
  )
}

function PolicyStatus({ policy }: { policy: PolicyRecord }) {
  if (!policy.enabled)
    return <Badge outline><Power />Off</Badge>
  return policy.mode === 'enforce' ? <Badge tone="success" dot>Enforcing</Badge> : <Badge tone="info" dot>Monitoring</Badge>
}

function PolicyChecks({ policy }: { policy: PolicyRecord }) {
  const rules = Array.isArray(policy.spec.rules) ? (policy.spec.rules as Array<{ name?: string; action?: string }>) : []
  const actions = rules.reduce<Record<string, number>>((totals, rule) => ({ ...totals, [rule.action ?? '']: (totals[rule.action ?? ''] ?? 0) + 1 }), {})
  const limits = Object.entries(policy.limits)
  const swarm = policy.spec.swarm && typeof policy.spec.swarm === 'object' ? policy.spec.swarm as Record<string, unknown> : {}
  const swarmLimits = Object.entries(swarm).filter(([key, value]) => key !== 'match' && typeof value === 'number') as Array<[string, number]>
  return (
    <span className="flex flex-wrap gap-1">
      {actions.deny ? <Badge tone="danger">{actions.deny} deny</Badge> : null}
      {actions.require_approval ? <Badge tone="warning">{actions.require_approval} approval</Badge> : null}
      {actions.warn ? <Badge tone="info">{actions.warn} warn</Badge> : null}
      {actions.allow ? <Badge tone="success">{actions.allow} allow</Badge> : null}
      {limits.slice(0, 4).map(([key, value]) => <Badge key={key} outline title={key}>{LIMIT_LABELS[key]?.(value) ?? `${key} ${value}`}</Badge>)}
      {limits.length > 4 && <Badge outline>+{limits.length - 4}</Badge>}
      {swarmLimits.map(([key, value]) => <Badge key={key} tone="violet" title={`swarm: ${key}`}>swarm {SWARM_LIMIT_LABELS[key]?.(value) ?? `${key} ${value}`}</Badge>)}
    </span>
  )
}

function PolicyEditor({ open, policy, simulateOnOpen, onClose, onSaved, onTrace }: {
  open: boolean
  policy: PolicyRecord | null
  simulateOnOpen: boolean
  onClose: () => void
  onSaved: (policy: PolicyRecord, created: boolean) => void
  onTrace: (traceId: string) => void
}) {
  const [text, setText] = useState(() => policy ? policy.source_text || JSON.stringify(policy.spec, null, 2) : TEMPLATES[0].text)
  const [enabled, setEnabled] = useState(policy?.enabled ?? true)
  const [validation, setValidation] = useState<PolicyValidation | null>(null)
  const [simulation, setSimulation] = useState<PolicySimulation | null>(null)
  const [busy, setBusy] = useState<'' | 'validate' | 'simulate' | 'save'>('')
  const [error, setError] = useState('')

  const run = useCallback(async (kind: 'validate' | 'simulate', source: string) => {
    setBusy(kind)
    setError('')
    try {
      const result = await validatePolicy(source)
      setValidation(result)
      if (kind === 'simulate' && result.valid)
        setSimulation(await simulatePolicy({ text: source, limit: 500 }))
      else if (!result.valid)
        setSimulation(null)
    }
    catch (caught) {
      setError(errorText(caught))
    }
    finally {
      setBusy('')
    }
  }, [])

  // "Simulate on recent traces" from the policies menu opens the editor and runs it once.
  const [autoSimulated, setAutoSimulated] = useState(false)
  useEffect(() => {
    if (open && simulateOnOpen && !autoSimulated) {
      setAutoSimulated(true)
      void run('simulate', text)
    }
  }, [open, simulateOnOpen, autoSimulated, run, text])

  async function save() {
    setBusy('save')
    setError('')
    try {
      const saved = policy ? await updatePolicy(policy.policy_id, { text, enabled }) : await createPolicy(text, enabled)
      onSaved(saved, !policy)
    }
    catch (caught) {
      setError(errorText(caught).replace(/^(POST|PATCH) \S+ failed with \d+: /, ''))
    }
    finally {
      setBusy('')
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width="max-w-3xl"
      title={policy ? `Edit ${policy.name}` : 'New policy'}
      description="YAML or JSON. Rules are checked in order and the first match wins; limits apply per trace."
      footer={(
        <>
          <Switch checked={enabled} onChange={setEnabled} label="Turned on" />
          <span className="flex-1" />
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" icon={<CheckCircle2 />} disabled={!text.trim() || busy === 'save'} onClick={() => void save()}>{policy ? 'Save policy' : 'Create policy'}</Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        {!policy && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-medium text-fg-muted">Start from</span>
            {TEMPLATES.map(template => (
              <Button key={template.id} size="xs" variant={text === template.text ? 'subtle' : 'secondary'} onClick={() => { setText(template.text); setValidation(null); setSimulation(null) }}>{template.label}</Button>
            ))}
          </div>
        )}
        <Textarea
          aria-label="Policy"
          spellCheck={false}
          className="min-h-[340px] resize-y"
          value={text}
          onChange={(event) => { setText(event.target.value); setValidation(null) }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button icon={<CheckCircle2 />} disabled={Boolean(busy)} onClick={() => void run('validate', text)}>Validate</Button>
          <Button icon={<FlaskConical />} disabled={Boolean(busy)} onClick={() => void run('simulate', text)}>{busy === 'simulate' ? 'Simulating...' : 'Simulate on recent traces'}</Button>
          {validation?.valid && !simulation && <span className="flex items-center gap-1 text-[13px] text-success-text"><CheckCircle2 className="size-3.5" />Valid</span>}
        </div>
        {error && <Callout tone="danger" title="Could not save">{error}</Callout>}
        {validation && !validation.valid && (
          <Callout tone="danger" title={`${validation.errors.length} problem${validation.errors.length === 1 ? '' : 's'}`}>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-xs">{validation.errors.map(item => <li key={item}>{item}</li>)}</ul>
          </Callout>
        )}
        {simulation && <SimulationReport simulation={simulation} onTrace={onTrace} />}
        <PolicyReference />
      </div>
    </Drawer>
  )
}

function SimulationReport({ simulation, onTrace }: { simulation: PolicySimulation; onTrace: (traceId: string) => void }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-line bg-surface-2/40 p-3">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <h3 className="text-[13px] font-semibold text-fg">If this policy had been enforced</h3>
        <span className="text-xs text-fg-subtle">{formatNumber(simulation.traces_evaluated)} recent traces, {formatNumber(simulation.actions_evaluated)} calls</span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Metric label="Traces affected" value={simulation.traces_affected} tone={simulation.traces_affected ? 'warning' : undefined} />
        <Metric label="Calls blocked" value={simulation.blocked_calls} tone={simulation.blocked_calls ? 'danger' : undefined} />
        <Metric label="Sent for approval" value={simulation.approval_calls} tone={simulation.approval_calls ? 'warning' : undefined} />
      </div>
      {simulation.traces_evaluated === 0 && <p className="text-[13px] text-fg-muted">There are no recorded traces to replay yet.</p>}
      {simulation.traces_evaluated > 0 && simulation.rules.length === 0 && <p className="flex items-center gap-1.5 text-[13px] text-success-text"><CheckCircle2 className="size-3.5" />Nothing in recent traces would have been stopped.</p>}
      {simulation.rules.length > 0 && (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {simulation.rules.map(rule => (
            <li key={`${rule.policy}-${rule.rule}`} className="flex items-center gap-2 px-3 py-2 text-[13px]">
              <Badge tone={rule.action === 'deny' ? 'danger' : rule.action === 'require_approval' ? 'warning' : 'info'}>{actionLabel(rule.action)}</Badge>
              <span className="min-w-0 flex-1 truncate font-mono text-xs text-fg">{rule.rule}</span>
              <span className="tabular text-xs whitespace-nowrap text-fg-muted">{formatNumber(rule.calls)} calls · {formatNumber(rule.traces)} traces</span>
            </li>
          ))}
        </ul>
      )}
      {simulation.traces.length > 0 && (
        <ul className="flex flex-col gap-1">
          {simulation.traces.slice(0, 8).map(trace => (
            <li key={trace.trace_id}>
              <button className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-surface-2" onClick={() => onTrace(trace.trace_id)}>
                <span className="w-40 shrink-0 truncate font-medium text-fg">{trace.name ?? trace.trace_id.slice(0, 12)}</span>
                <span className="min-w-0 flex-1 truncate text-fg-muted" title={trace.first.reason}>{trace.first.reason}</span>
                <span className="text-xs whitespace-nowrap text-fg-subtle">{trace.started_at ? formatRelative(trace.started_at) : ''}</span>
              </button>
            </li>
          ))}
          {simulation.traces.length > 8 && <li className="px-2 text-xs text-fg-subtle">and {simulation.traces.length - 8} more</li>}
        </ul>
      )}
    </section>
  )
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: 'danger' | 'warning' }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2">
      <div className="text-xs text-fg-muted">{label}</div>
      <div className={`tabular text-lg font-semibold ${tone === 'danger' ? 'text-danger-text' : tone === 'warning' ? 'text-warning-text' : 'text-fg'}`}>{formatNumber(value)}</div>
    </div>
  )
}

function PolicyReference() {
  return (
    <details className="group rounded-lg border border-line text-[13px]">
      <summary className="cursor-pointer px-3 py-2 font-medium text-fg-muted select-none hover:text-fg">Reference</summary>
      <div className="grid gap-4 border-t border-line px-3 py-3 sm:grid-cols-2">
        <div>
          <h4 className="mb-1.5 text-xs font-semibold text-fg">Rule actions</h4>
          <dl className="space-y-1 text-xs text-fg-muted">
            <div><dt className="inline font-mono text-fg">deny</dt> stops the call and raises PolicyViolation</div>
            <div><dt className="inline font-mono text-fg">require_approval</dt> pauses until a reviewer answers on Approvals</div>
            <div><dt className="inline font-mono text-fg">warn</dt> records the call and lets it run</div>
            <div><dt className="inline font-mono text-fg">allow</dt> exempts the call from this policy, limits included</div>
          </dl>
          <h4 className="mt-3 mb-1.5 text-xs font-semibold text-fg">Match on</h4>
          <p className="font-mono text-xs leading-5 text-fg-muted">kind (tool, llm, agent, any), tool, model, name, provider, agent, service, environment, arguments (dotted paths), input_regex. Patterns use * wildcards; use except to carve out exceptions.</p>
        </div>
        <div>
          <h4 className="mb-1.5 text-xs font-semibold text-fg">Limits, per trace</h4>
          <ul className="space-y-0.5 font-mono text-xs text-fg-muted">
            {['max_repeated_calls', 'max_tool_calls', 'max_calls_per_tool', 'max_llm_calls', 'max_steps', 'max_cost_usd', 'max_tokens', 'max_duration_seconds', 'max_agent_depth', 'max_child_agents'].map(limit => <li key={limit}>{limit}</li>)}
          </ul>
          <h4 className="mt-3 mb-1.5 text-xs font-semibold text-fg">Swarm limits, across processes</h4>
          <ul className="space-y-0.5 font-mono text-xs text-fg-muted">
            {['max_agents', 'max_concurrent_agents', 'max_spawn_rate_per_minute', 'max_cost_usd', 'max_tokens', 'max_duration_minutes'].map(limit => <li key={limit}>swarm.{limit}</li>)}
          </ul>
          <p className="mt-1 text-xs text-fg-subtle">Checked on the server every few seconds; a swarm that breaks one is halted.</p>
          <h4 className="mt-3 mb-1.5 text-xs font-semibold text-fg">Modes</h4>
          <p className="text-xs text-fg-muted"><span className="font-mono text-fg">monitor</span> records what would be blocked and blocks nothing. <span className="font-mono text-fg">enforce</span> blocks.</p>
        </div>
      </div>
    </details>
  )
}

function HaltDrawer({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (halt: HaltRecord) => void }) {
  const [scope, setScope] = useState<HaltRecord['scope']>('service')
  const [value, setValue] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const needsValue = scope !== 'all'
  const selected = HALT_SCOPES.find(item => item.value === scope)

  async function submit() {
    try {
      const halt = await createHalt({ scope, value: needsValue ? value.trim() : undefined, reason: reason.trim() || undefined })
      setValue('')
      setReason('')
      setError('')
      onCreated(halt)
    }
    catch (caught) {
      setError(errorText(caught).replace(/^POST \S+ failed with \d+: /, ''))
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Stop agents"
      description="The kill switch. Stopped agents fail their next tool call, LLM call, or agent start until you release the halt."
      footer={(
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" icon={<OctagonX />} disabled={needsValue && !value.trim()} onClick={() => void submit()}>{scope === 'all' ? 'Stop every agent' : `Stop ${scope}`}</Button>
        </>
      )}
    >
      <form className="flex flex-col gap-5" onSubmit={(event) => { event.preventDefault(); void submit() }}>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-muted">What to stop</span>
          <Segmented value={scope} onChange={setScope} options={HALT_SCOPES.map(item => ({ value: item.value, label: item.label }))} />
          <span className="text-xs text-fg-subtle">{selected?.hint}</span>
        </div>
        {needsValue && <TextField label={{ trace: 'Trace ID', agent: 'Agent name', swarm: 'Swarm ID', service: 'Service name' }[scope]} value={value} onChange={setValue} placeholder={{ trace: '4bf92f3577b34da6a3ce929d0e0e4736', agent: 'researcher', swarm: 'swarm_8c1f04e2a9b3d756', service: 'support-bot' }[scope]} />}
        <TextField label="Reason" value={reason} onChange={setReason} placeholder="Runaway spend on the refunds agent" hint="Shown to people on this page and in the error the agent receives." />
        {scope === 'all' && <Callout tone="danger" icon={<ShieldAlert />} title="This stops every agent">Every SDK and runtime connected to this server stops at its next call.</Callout>}
        {error && <p className="text-[13px] text-danger-text">{error}</p>}
      </form>
    </Drawer>
  )
}

function actionLabel(action: string): string {
  return { deny: 'Blocks', require_approval: 'Approval', warn: 'Warns', allow: 'Allows' }[action] ?? action
}

function decisionLabel(decision: PolicyDecision): string {
  if (decision.details?.approval)
    return decision.action === 'allow' ? 'Approved' : 'Rejected'
  if (decision.rule === 'halt')
    return 'Halted'
  if (!decision.enforced)
    return decision.action === 'require_approval' ? 'Would need approval' : decision.action === 'warn' ? 'Would warn' : 'Would block'
  return { deny: 'Blocked', require_approval: 'Needs approval', warn: 'Warned', allow: 'Allowed' }[decision.action] ?? decision.action
}

function decisionTone(decision: PolicyDecision): Tone {
  if (decision.details?.approval)
    return decision.action === 'allow' ? 'success' : 'danger'
  if (!decision.enforced)
    return decision.action === 'warn' ? 'info' : 'warning'
  return { deny: 'danger', require_approval: 'warning', warn: 'info', allow: 'success' }[decision.action] as Tone
}

function kindOf(kind: string): SpanKind {
  if (kind === 'swarm')
    return 'workflow'
  return kind === 'llm' || kind === 'tool' || kind === 'agent' ? kind : 'span'
}

function scopeLabel(scope: HaltRecord['scope']): string {
  return { all: 'Everything', swarm: 'Swarm', trace: 'Trace', agent: 'Agent', service: 'Service' }[scope]
}

function haltLabel(halt: HaltRecord): string {
  return halt.scope === 'all' ? 'every agent' : `${halt.scope} ${halt.value}`
}
