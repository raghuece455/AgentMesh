import { BellRing, CheckCircle2, Plus, Send, ShieldAlert, Trash2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { checkAlerts, createAlertRule, deleteAlertRule, getAlertKinds, listAlertEvents, listAlertRules, testAlertRule, updateAlertRule } from '../api'
import { InlineAction } from '../components/common/Actions'
import { Badge } from '../components/common/Badges'
import { EmptyState, MetricCard, Panel } from '../components/common/Cards'
import { FilterSelect, TextField } from '../components/common/Inputs'
import { DataTable } from '../components/tables/DataTable'
import type { AlertEvent, AlertRule } from '../types'
import { errorText, formatTime } from '../utils/format'

const KIND_LABELS: Record<string, string> = {
  failure_rate: 'Failure rate',
  failure_count: 'Failed runs',
  cost: 'Spend',
  trace_cost: 'Expensive trace',
  latency_p95: 'p95 latency',
  loop_detected: 'Tool loop',
}

export function AlertsPage({ refreshKey }: { refreshKey: string | null }) {
  const [rules, setRules] = useState<AlertRule[]>([])
  const [events, setEvents] = useState<AlertEvent[]>([])
  const [kinds, setKinds] = useState<Record<string, string>>({})
  const [checkInterval, setCheckInterval] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const [version, setVersion] = useState(0)
  const reload = () => setVersion(value => value + 1)

  useEffect(() => {
    Promise.all([listAlertRules(), listAlertEvents(50), getAlertKinds()])
      .then(([nextRules, nextEvents, meta]) => {
        setRules(nextRules)
        setEvents(nextEvents)
        setKinds(meta.kinds)
        setCheckInterval(meta.check_interval_seconds)
      })
      .catch(caught => setNotice(errorText(caught)))
  }, [refreshKey, version])

  const firing = rules.filter(rule => rule.enabled && rule.state === 'firing').length
  const dayAgo = Date.now() - 24 * 3600 * 1000
  const recent = events.filter(event => Date.parse(event.created_at) >= dayAgo && event.status === 'firing').length

  async function act(action: () => Promise<unknown>, success?: string) {
    try {
      const result = await action()
      setNotice(success ?? '')
      reload()
      return result
    }
    catch (caught) {
      setNotice(errorText(caught))
      return undefined
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard icon={<BellRing className="size-4" />} label="Alert rules" value={rules.length} compact />
        <MetricCard icon={<ShieldAlert className="size-4" />} label="Firing now" value={firing} tone={firing ? 'danger' : 'good'} compact />
        <MetricCard icon={<Send className="size-4" />} label="Notifications (24h)" value={recent} tone={recent ? 'warn' : 'neutral'} compact />
        <MetricCard icon={<CheckCircle2 className="size-4" />} label="Checked every" value={checkInterval === null ? '-' : checkInterval > 0 ? `${checkInterval}s` : 'off (use agentmesh alerts check)'} compact />
      </div>
      {notice && <div className="rounded-2xl border border-sky-200/24 bg-sky-400/12 px-3 py-2 text-sm/6 text-sky-50">{notice}</div>}

      <Panel
        title="Alert rules"
        icon={<BellRing className="size-4" />}
        actions={<button className="trace-action" onClick={() => void act(async () => {
          const { fired } = await checkAlerts()
          return fired
        }, 'Checked all rules now.')}>Check now</button>}
      >
        {rules.length === 0
          ? <EmptyState icon={<BellRing className="size-5" />} title="No alert rules" detail="Get a Slack, Discord, or webhook notification when failures spike, spend jumps, a trace gets expensive, or an agent loops." />
          : (
              <DataTable
                rows={rules}
                minWidth={900}
                columns={[
                  { label: 'Rule', render: row => <div><div className="font-semibold text-white">{row.name}</div><div className="text-xs/5 text-white/50">{condition(row)}</div></div>, sortValue: row => row.name },
                  { label: 'Scope', render: row => <Filters filters={row.filters} />, sortValue: row => JSON.stringify(row.filters) },
                  { label: 'State', render: row => !row.enabled ? <Badge outline>disabled</Badge> : row.state === 'firing' ? <Badge tone="danger">firing</Badge> : <Badge tone="good">ok</Badge>, sortValue: row => `${row.enabled}${row.state}` },
                  { label: 'Last value', render: row => formatValue(row.kind, row.last_value), sortValue: row => row.last_value ?? -1 },
                  { label: 'Notify', render: row => <span className="whitespace-nowrap">{row.channel.url ? <Badge tone="info">{row.channel.format}</Badge> : <Badge outline>dashboard</Badge>}</span>, sortValue: row => row.channel.format },
                  { label: 'Last fired', render: row => <span className="whitespace-nowrap">{formatTime(row.last_triggered_at)}</span>, sortValue: row => Date.parse(row.last_triggered_at ?? '') || 0 },
                  {
                    label: '',
                    render: row => (
                      <div className="flex flex-wrap gap-1">
                        <InlineAction icon={<CheckCircle2 className="size-3" />} label={row.enabled ? 'Disable' : 'Enable'} onClick={() => void act(() => updateAlertRule(row.rule_id, { enabled: !row.enabled }))} />
                        {row.channel.url && <InlineAction icon={<Send className="size-3" />} label="Test" onClick={() => void act(async () => {
                          const result = await testAlertRule(row.rule_id)
                          if (!result.delivered)
                            throw new Error(`Test notification failed: ${result.error ?? 'unknown error'}`)
                        }, `Test notification sent for ${row.name}.`)} />}
                        <InlineAction icon={<Trash2 className="size-3" />} label="Delete" tone="danger" onClick={() => void act(() => deleteAlertRule(row.rule_id))} />
                      </div>
                    ),
                  },
                ]}
              />
            )}
      </Panel>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[400px_minmax(0,1fr)]">
        <NewRuleForm kinds={kinds} onCreated={name => { setNotice(`Created ${name}.`); reload() }} />
        <Panel title="Recent notifications" icon={<Send className="size-4" />}>
          {events.length === 0
            ? <EmptyState title="Nothing has fired yet" />
            : (
                <DataTable
                  rows={events}
                  minWidth={620}
                  columns={[
                    { label: 'Time', render: row => <span className="whitespace-nowrap">{formatTime(row.created_at)}</span>, sortValue: row => Date.parse(row.created_at) },
                    { label: 'Rule', render: row => <span className="font-semibold text-white">{row.rule_name}</span>, sortValue: row => row.rule_name },
                    { label: 'Status', render: row => <Badge tone={row.status === 'firing' ? 'danger' : row.status === 'resolved' ? 'good' : 'info'}>{row.status}</Badge>, sortValue: row => row.status },
                    { label: 'Message', render: row => <span className="text-sm/5 text-white/84">{row.message}</span>, sortValue: row => row.message },
                    { label: 'Delivery', render: row => row.delivery_error ? <Badge tone="warn">{row.delivery_error}</Badge> : row.delivered ? <Badge tone="good">delivered</Badge> : <Badge outline>recorded</Badge>, sortValue: row => String(row.delivered) },
                  ]}
                />
              )}
        </Panel>
      </div>
    </div>
  )
}

function NewRuleForm({ kinds, onCreated }: { kinds: Record<string, string>; onCreated: (name: string) => void }) {
  const [form, setForm] = useState({ name: '', kind: 'failure_rate', threshold: '0.2', window: '15m', cooldown: '30m', url: '', format: '', secret: '', workflow: '', environment: '' })
  const [error, setError] = useState('')
  const set = (key: keyof typeof form) => (value: string) => setForm(current => ({ ...current, [key]: value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    const filters: Record<string, string> = {}
    if (form.workflow.trim())
      filters.workflow = form.workflow.trim()
    if (form.environment.trim())
      filters.environment = form.environment.trim()
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
    <Panel title="New alert rule" icon={<Plus className="size-4" />}>
      <form className="flex flex-col gap-2" onSubmit={event => void submit(event)}>
        <TextField label="Name" value={form.name} onChange={set('name')} placeholder="checkout failures" />
        <FilterSelect label="When" value={form.kind} onChange={kind => setForm(current => ({ ...current, kind, threshold: defaultThreshold(kind) }))} options={Object.keys(kinds).map(kind => [kind, KIND_LABELS[kind] ?? kind])} />
        <p className="text-xs/5 text-white/55">{kinds[form.kind]}</p>
        <div className="grid grid-cols-3 gap-2">
          <TextField label={thresholdLabel(form.kind)} value={form.threshold} onChange={set('threshold')} />
          <TextField label="Window" value={form.window} onChange={set('window')} placeholder="15m" />
          <TextField label="Cooldown" value={form.cooldown} onChange={set('cooldown')} placeholder="30m" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <TextField label="Workflow (optional)" value={form.workflow} onChange={set('workflow')} />
          <TextField label="Environment (optional)" value={form.environment} onChange={set('environment')} placeholder="production" />
        </div>
        <TextField label="Webhook URL (Slack, Discord, or any HTTPS endpoint)" value={form.url} onChange={set('url')} placeholder="https://hooks.slack.com/services/..." />
        <div className="grid grid-cols-2 gap-2">
          <FilterSelect label="Format" value={form.format} onChange={set('format')} options={[['', 'Detect from URL'], ['slack', 'Slack'], ['discord', 'Discord'], ['json', 'JSON']]} />
          <TextField label="Signing secret (optional)" type="password" value={form.secret} onChange={set('secret')} />
        </div>
        <button type="submit" className="trace-action self-start" disabled={!form.name.trim()}><Plus className="size-4" />Create rule</button>
        {error && <p className="text-xs/5 text-rose-100">{error}</p>}
      </form>
    </Panel>
  )
}

function Filters({ filters }: { filters: Record<string, unknown> }) {
  const entries = Object.entries(filters).filter(([key]) => key !== 'min_runs')
  if (!entries.length)
    return <span className="whitespace-nowrap text-white/40">all traces</span>
  return <span className="flex flex-wrap gap-1">{entries.map(([key, value]) => <Badge key={key} outline>{key}={String(value)}</Badge>)}</span>
}

function condition(rule: AlertRule): string {
  const window = rule.window_minutes % 60 === 0 ? `${rule.window_minutes / 60}h` : `${rule.window_minutes}m`
  const threshold = formatValue(rule.kind, rule.threshold)
  if (rule.kind === 'trace_cost')
    return `a trace costs >= ${threshold} (last ${window})`
  if (rule.kind === 'loop_detected')
    return `a tool repeats >= ${threshold} times with the same input (last ${window})`
  return `${KIND_LABELS[rule.kind] ?? rule.kind} >= ${threshold} over ${window}`
}

function formatValue(kind: string, value: number | null | undefined): string {
  if (value === null || value === undefined)
    return '-'
  if (kind === 'failure_rate')
    return `${Math.round(value * 100)}%`
  if (kind === 'cost' || kind === 'trace_cost')
    return `$${value.toFixed(value < 1 ? 4 : 2)}`
  if (kind === 'latency_p95')
    return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`
  return String(Math.round(value))
}

function thresholdLabel(kind: string): string {
  return { failure_rate: 'Rate (0-1)', cost: 'USD', trace_cost: 'USD', latency_p95: 'ms', loop_detected: 'Repeats' }[kind] ?? 'Threshold'
}

function defaultThreshold(kind: string): string {
  return { failure_rate: '0.2', failure_count: '5', cost: '10', trace_cost: '1', latency_p95: '30000', loop_detected: '3' }[kind] ?? '1'
}
