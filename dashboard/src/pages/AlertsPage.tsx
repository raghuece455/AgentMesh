import { BellOff, BellRing, CheckCircle2, MoreHorizontal, Plus, Power, Send, ShieldAlert, Timer, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { checkAlerts, createAlertRule, deleteAlertRule, getAlertKinds, listAlertEvents, listAlertRules, testAlertRule, updateAlertRule } from '../api'
import { Badge, StatusDot } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, PageHeader } from '../components/ui/Card'
import { DataTable } from '../components/ui/DataTable'
import { SelectField, TextField } from '../components/ui/Field'
import { Drawer, Menu, Toast } from '../components/ui/Overlay'
import { StatCard } from '../components/ui/Stat'
import { Segmented } from '../components/ui/Tabs'
import type { AlertEvent, AlertRule } from '../types'
import { errorText, formatDateTime, formatRelative } from '../utils/format'

const KIND_LABELS: Record<string, string> = {
  failure_rate: 'Failure rate',
  failure_count: 'Failed runs',
  cost: 'Spend',
  trace_cost: 'Expensive trace',
  latency_p95: 'p95 latency',
  loop_detected: 'Tool loop',
  new_destination: 'New destination',
  swarm_agents: 'Swarm size',
  swarm_spawn_rate: 'Swarm spawn rate',
  swarm_cost: 'Swarm spend',
  swarm_errors: 'Swarm failures',
  swarm_loop: 'Agent loop',
}
const SWARM_SCOPED = new Set(['new_destination', 'swarm_agents', 'swarm_spawn_rate', 'swarm_cost', 'swarm_errors', 'swarm_loop'])

export function AlertsPage({ refreshKey, onChanged }: { refreshKey: string | null; onChanged: () => void }) {
  const [rules, setRules] = useState<AlertRule[]>([])
  const [events, setEvents] = useState<AlertEvent[]>([])
  const [kinds, setKinds] = useState<Record<string, string>>({})
  const [kindGroups, setKindGroups] = useState<Record<string, string>>({})
  const [checkInterval, setCheckInterval] = useState<number | null>(null)
  const [notice, setNotice] = useState<{ message: string; tone?: 'neutral' | 'danger' | 'success' }>({ message: '' })
  const [creating, setCreating] = useState(false)
  const [stateFilter, setStateFilter] = useState<'all' | 'firing' | 'ok' | 'disabled'>('all')
  const [version, setVersion] = useState(0)
  const clearNotice = useCallback(() => setNotice({ message: '' }), [])
  const reload = () => {
    setVersion(value => value + 1)
    onChanged()
  }

  useEffect(() => {
    Promise.all([listAlertRules(), listAlertEvents(50), getAlertKinds()])
      .then(([nextRules, nextEvents, meta]) => {
        setRules(nextRules)
        setEvents(nextEvents)
        setKinds(meta.kinds)
        setKindGroups(meta.groups ?? {})
        setCheckInterval(meta.check_interval_seconds)
      })
      .catch(caught => setNotice({ message: errorText(caught), tone: 'danger' }))
  }, [refreshKey, version])

  const firing = rules.filter(rule => rule.enabled && rule.state === 'firing').length
  const disabled = rules.filter(rule => !rule.enabled).length
  const dayAgo = Date.now() - 24 * 3600 * 1000
  const recent = events.filter(event => Date.parse(event.created_at) >= dayAgo && event.status === 'firing').length
  const visibleRules = rules.filter(rule => stateFilter === 'all' || (stateFilter === 'disabled' ? !rule.enabled : rule.enabled && (stateFilter === 'firing' ? rule.state === 'firing' : rule.state !== 'firing')))

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

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Get notified in Slack, Discord, or any webhook when failures spike, spend jumps, a swarm grows out of control, or an agent reaches somewhere new."
        actions={(
          <>
            <Button icon={<CheckCircle2 />} onClick={() => void act(() => checkAlerts(), 'Checked all rules.')}>Check now</Button>
            <Button variant="primary" icon={<Plus />} onClick={() => setCreating(true)}>New alert rule</Button>
          </>
        )}
      />
      <Toast message={notice.message} tone={notice.tone} onDone={clearNotice} />
      <NewRuleDrawer open={creating} kinds={kinds} groups={kindGroups} onClose={() => setCreating(false)} onCreated={name => { setCreating(false); setNotice({ message: `Created ${name}.`, tone: 'success' }); reload() }} />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Firing now" icon={<ShieldAlert />} value={firing} tone={firing ? 'danger' : 'neutral'} sub={firing ? 'Needs attention' : 'All clear'} />
        <StatCard label="Alert rules" icon={<BellRing />} value={rules.length} sub={`${rules.length - disabled} enabled · ${disabled} disabled`} />
        <StatCard label="Notifications, 24h" icon={<Send />} value={recent} tone={recent ? 'warning' : 'neutral'} sub={`${events.length} in history`} />
        <StatCard label="Checked every" icon={<Timer />} value={checkInterval === null ? '-' : checkInterval > 0 ? `${checkInterval}s` : 'Off'} sub={checkInterval === 0 ? 'Run agentmesh alerts check' : 'By the server scheduler'} />
      </div>

      <Card
        flush
        title="Rules"
        actions={(
          <Segmented
            size="sm"
            value={stateFilter}
            onChange={setStateFilter}
            options={[
              { value: 'all', label: `All ${rules.length}` },
              { value: 'firing', label: `Firing ${firing}` },
              { value: 'ok', label: 'OK' },
              { value: 'disabled', label: 'Disabled' },
            ]}
          />
        )}
      >
        {rules.length === 0
          ? <EmptyState icon={<BellRing />} title="No alert rules" detail="Create a rule for failed runs, spend, latency, tool loops, new destinations, or swarms that grow too fast." action={<Button variant="primary" icon={<Plus />} onClick={() => setCreating(true)}>New alert rule</Button>} />
          : (
              <DataTable
                rows={visibleRules}
                rowKey={row => row.rule_id}
                minWidth={900}
                rowClassName={row => row.enabled && row.state === 'firing' ? 'shadow-[inset_2px_0_0_var(--danger)]' : ''}
                empty={<EmptyState title="No rules in this state" />}
                columns={[
                  {
                    label: 'Status',
                    width: '110px',
                    sortValue: row => `${row.enabled ? (row.state === 'firing' ? 0 : 1) : 2}`,
                    render: row => !row.enabled
                      ? <Badge outline><BellOff />Disabled</Badge>
                      : row.state === 'firing' ? <Badge tone="danger" dot>Firing</Badge> : <Badge tone="success" dot>OK</Badge>,
                  },
                  { label: 'Rule', sortValue: row => row.name, render: row => <span className="flex flex-col"><span className="font-medium text-fg">{row.name}</span><span className="font-mono text-[11.5px] text-fg-subtle">{condition(row)}</span></span> },
                  { label: 'Scope', render: row => <Filters filters={row.filters} kind={row.kind} /> },
                  { label: 'Last value', align: 'right', sortValue: row => row.last_value ?? -1, render: row => <span className={row.enabled && row.state === 'firing' ? 'font-semibold text-danger-text' : 'text-fg'}>{formatValue(row.kind, row.last_value)}</span> },
                  { label: 'Notify', render: row => row.channel.url ? <Badge tone="accent">{row.channel.format}</Badge> : <Badge outline>dashboard only</Badge> },
                  { label: 'Last fired', align: 'right', sortValue: row => Date.parse(row.last_triggered_at ?? '') || 0, render: row => <span className="whitespace-nowrap text-fg-muted" title={formatDateTime(row.last_triggered_at)}>{row.last_triggered_at ? formatRelative(row.last_triggered_at) : 'never'}</span> },
                  {
                    label: '',
                    align: 'right',
                    width: '48px',
                    render: row => (
                      <Menu
                        trigger={({ toggle }) => <Button size="icon-sm" variant="ghost" aria-label={`Actions for ${row.name}`} onClick={toggle}><MoreHorizontal /></Button>}
                        items={[
                          { label: row.enabled ? 'Disable' : 'Enable', icon: <Power />, onSelect: () => void act(() => updateAlertRule(row.rule_id, { enabled: !row.enabled })) },
                          ...(row.channel.url
                            ? [{
                                label: 'Send test notification',
                                icon: <Send />,
                                onSelect: () => void act(async () => {
                                  const result = await testAlertRule(row.rule_id)
                                  if (!result.delivered)
                                    throw new Error(`Test notification failed: ${result.error ?? 'unknown error'}`)
                                }, `Test notification sent for ${row.name}.`),
                              }]
                            : []),
                          { label: 'Delete', icon: <Trash2 />, danger: true, onSelect: () => void act(() => deleteAlertRule(row.rule_id), `Deleted ${row.name}.`) },
                        ]}
                      />
                    ),
                  },
                ]}
              />
            )}
      </Card>

      <Card flush title="Recent notifications" description="Firing and resolved events, newest first">
        {events.length === 0
          ? <EmptyState icon={<Send />} title="Nothing has fired yet" />
          : (
              <ol className="divide-y divide-line">
                {events.map(event => (
                  <li key={event.alert_id} className="flex items-start gap-3 px-4 py-3">
                    <StatusDot status={event.status === 'firing' ? 'failed' : event.status === 'resolved' ? 'succeeded' : 'running'} className="mt-1.5" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-medium text-fg">{event.rule_name}</span>
                        <Badge tone={event.status === 'firing' ? 'danger' : event.status === 'resolved' ? 'success' : 'info'}>{event.status}</Badge>
                        {event.delivery_error ? <Badge tone="warning" title={event.delivery_error}>delivery failed</Badge> : event.delivered ? <Badge outline>delivered</Badge> : null}
                      </div>
                      <p className="mt-0.5 text-[13px] text-fg-muted">{event.message}</p>
                    </div>
                    <span className="shrink-0 text-xs whitespace-nowrap text-fg-subtle" title={formatDateTime(event.created_at)}>{formatRelative(event.created_at)}</span>
                  </li>
                ))}
              </ol>
            )}
      </Card>
    </>
  )
}

function NewRuleDrawer({ open, kinds, groups, onClose, onCreated }: { open: boolean; kinds: Record<string, string>; groups: Record<string, string>; onClose: () => void; onCreated: (name: string) => void }) {
  const [form, setForm] = useState({ name: '', kind: 'failure_rate', threshold: '0.2', window: '15m', cooldown: '30m', url: '', format: '', secret: '', workflow: '', environment: '', swarm: '', accessKind: '' })
  const swarmScoped = SWARM_SCOPED.has(form.kind)
  const [error, setError] = useState('')
  const set = (key: keyof typeof form) => (value: string) => setForm(current => ({ ...current, [key]: value }))

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    const filters: Record<string, string> = {}
    if (form.environment.trim())
      filters.environment = form.environment.trim()
    if (swarmScoped) {
      if (form.swarm.trim())
        filters.swarm = form.swarm.trim()
      if (form.accessKind && form.kind === 'new_destination')
        filters.access_kind = form.accessKind
    }
    else if (form.workflow.trim()) {
      filters.workflow = form.workflow.trim()
    }
    const channel: Record<string, string> = {}
    if (form.url.trim()) {
      channel.url = form.url.trim()
      if (form.format)
        channel.format = form.format
      if (form.secret)
        channel.secret = form.secret
    }
    try {
      const rule = await createAlertRule({ name: form.name.trim(), kind: form.kind, threshold: Number(form.threshold), window: form.window, cooldown: form.cooldown, filters, channel })
      setForm(current => ({ ...current, name: '', url: '', secret: '' }))
      setError('')
      onCreated(rule.name)
    }
    catch (caught) {
      setError(errorText(caught))
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="New alert rule"
      description="Rules are checked on a schedule by the server."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" icon={<Plus />} disabled={!form.name.trim()} onClick={() => void submit()}>Create rule</Button></>}
    >
      <form className="flex flex-col gap-5" onSubmit={event => void submit(event)}>
        <TextField label="Name" value={form.name} onChange={set('name')} placeholder="checkout failures" />
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 text-[13px] font-semibold text-fg">Condition</legend>
          <SelectField label="Alert when" value={form.kind} onChange={kind => setForm(current => ({ ...current, kind, threshold: defaultThreshold(kind) }))} options={Object.keys(kinds).map(kind => [kind, KIND_LABELS[kind] ?? kind])} groups={groups} hint={kinds[form.kind]} />
          <div className="grid grid-cols-3 gap-2">
            <TextField label={thresholdLabel(form.kind)} value={form.threshold} onChange={set('threshold')} />
            <TextField label="Window" value={form.window} onChange={set('window')} placeholder="15m" />
            <TextField label="Cooldown" value={form.cooldown} onChange={set('cooldown')} placeholder="30m" />
          </div>
        </fieldset>
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 text-[13px] font-semibold text-fg">Scope</legend>
          <div className="grid grid-cols-2 gap-2">
            {swarmScoped
              ? <TextField label="Swarm" value={form.swarm} onChange={set('swarm')} placeholder="any" hint="Swarm id or name; * allowed" />
              : <TextField label="Workflow" value={form.workflow} onChange={set('workflow')} placeholder="any" />}
            <TextField label="Environment" value={form.environment} onChange={set('environment')} placeholder="production" />
          </div>
          {form.kind === 'new_destination' && (
            <SelectField
              label="Destination kind"
              value={form.accessKind}
              onChange={set('accessKind')}
              options={[['', 'Any'], ['network', 'Network hosts'], ['retrieval', 'Retrieval'], ['memory', 'Memory'], ['db', 'Databases'], ['file', 'Files'], ['api', 'APIs'], ['other', 'Other']]}
            />
          )}
        </fieldset>
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 text-[13px] font-semibold text-fg">Notification</legend>
          <TextField label="Webhook URL" value={form.url} onChange={set('url')} placeholder="https://hooks.slack.com/services/..." hint="Slack, Discord, or any HTTPS endpoint. Leave empty to record alerts in the dashboard only." />
          <div className="grid grid-cols-2 gap-2">
            <SelectField label="Format" value={form.format} onChange={set('format')} options={[['', 'Detect from URL'], ['slack', 'Slack'], ['discord', 'Discord'], ['json', 'JSON']]} />
            <TextField label="Signing secret" type="password" value={form.secret} onChange={set('secret')} placeholder="optional" />
          </div>
        </fieldset>
        {error && <p className="text-[13px] text-danger-text">{error}</p>}
      </form>
    </Drawer>
  )
}

function Filters({ filters, kind }: { filters: Record<string, unknown>; kind: string }) {
  const entries = Object.entries(filters).filter(([key]) => key !== 'min_runs')
  if (!entries.length)
    return <span className="whitespace-nowrap text-fg-subtle">{kind === 'new_destination' ? 'all destinations' : SWARM_SCOPED.has(kind) ? 'all swarms' : 'all traces'}</span>
  return <span className="flex flex-wrap gap-1">{entries.map(([key, value]) => <Badge key={key} outline>{key}: {String(value)}</Badge>)}</span>
}

function condition(rule: AlertRule): string {
  const window = rule.window_minutes % 60 === 0 ? `${rule.window_minutes / 60}h` : `${rule.window_minutes}m`
  const threshold = formatValue(rule.kind, rule.threshold)
  if (rule.kind === 'trace_cost')
    return `trace cost >= ${threshold} · last ${window}`
  if (rule.kind === 'new_destination')
    return `a destination reached >= ${threshold}x for the first time · last ${window}`
  if (rule.kind === 'swarm_loop')
    return `two agents exchanged >= ${threshold} messages · last ${window}`
  if (rule.kind === 'loop_detected')
    return `same tool call repeated >= ${threshold}x · last ${window}`
  return `${(KIND_LABELS[rule.kind] ?? rule.kind).toLowerCase()} >= ${threshold} · last ${window}`
}

function formatValue(kind: string, value: number | null | undefined): string {
  if (value === null || value === undefined)
    return '-'
  if (kind === 'failure_rate')
    return `${Math.round(value * 100)}%`
  if (kind === 'cost' || kind === 'trace_cost' || kind === 'swarm_cost')
    return `$${value.toFixed(value < 1 ? 4 : 2)}`
  if (kind === 'latency_p95')
    return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`
  return String(Math.round(value))
}

function thresholdLabel(kind: string): string {
  return {
    failure_rate: 'Rate (0-1)', cost: 'USD', trace_cost: 'USD', latency_p95: 'ms', loop_detected: 'Repeats',
    new_destination: 'Accesses', swarm_agents: 'Agents', swarm_spawn_rate: 'Agents / min', swarm_cost: 'USD', swarm_errors: 'Failed traces', swarm_loop: 'Messages',
  }[kind] ?? 'Threshold'
}

function defaultThreshold(kind: string): string {
  return {
    failure_rate: '0.2', failure_count: '5', cost: '10', trace_cost: '1', latency_p95: '30000', loop_detected: '3',
    new_destination: '1', swarm_agents: '100', swarm_spawn_rate: '60', swarm_cost: '25', swarm_errors: '5', swarm_loop: '10',
  }[kind] ?? '1'
}
