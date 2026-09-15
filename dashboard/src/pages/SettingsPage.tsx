import { KeyRound, Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { getApiKey } from '../api'
import type { ThemeSetting } from '../components/layout/Topbar'
import { Badge, StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, KeyValue, PageHeader } from '../components/ui/Card'
import { CopyableId } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Input } from '../components/ui/Field'
import { Segmented } from '../components/ui/Tabs'
import type { CostCenterSummary, IntegrationInfo, JsonRecord, ProviderHealth } from '../types'
import { formatDateTime, formatMoney, formatNumber, formatRelative, stringValue } from '../utils/format'

export function SettingsPage({ auditLogs, providers, costs, integrations, theme, onTheme, onApiKey }: { auditLogs: JsonRecord[]; providers: ProviderHealth[]; costs: CostCenterSummary | null; integrations: IntegrationInfo | null; theme: ThemeSetting; onTheme: (theme: ThemeSetting) => void; onApiKey: (key: string) => void }) {
  const [key, setKey] = useState('')
  const hasKey = Boolean(getApiKey())
  const budget = costs?.budget_settings ?? {}
  const money = (value: unknown) => value === null || value === undefined ? <span className="text-fg-subtle">not set</span> : formatMoney(value)

  return (
    <>
      <PageHeader title="Settings" description="Appearance, access, budgets, providers, and the audit log." />
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <Card title="Appearance">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-[13px] font-medium text-fg">Theme</div>
              <div className="text-xs text-fg-subtle">Saved in this browser.</div>
            </div>
            <Segmented
              value={theme}
              onChange={onTheme}
              options={[
                { value: 'light', label: <><Sun />Light</> },
                { value: 'dark', label: <><Moon />Dark</> },
                { value: 'system', label: <><Monitor />System</> },
              ]}
            />
          </div>
        </Card>

        <Card title="API access">
          <div className="flex flex-col gap-3">
            <KeyValue rows={[
              ['Server version', integrations?.version],
              ['Auth mode', integrations?.auth_mode === 'api_key' ? <Badge tone="success">API key</Badge> : <Badge outline>none (local)</Badge>],
              ['This browser', hasKey ? <Badge tone="accent">key saved</Badge> : <span className="text-fg-subtle">no key saved</span>],
            ]} />
            <form
              className="flex gap-2"
              onSubmit={event => {
                event.preventDefault()
                onApiKey(key.trim())
                setKey('')
              }}
            >
              <Input type="password" aria-label="API key" placeholder="AGENTMESH_API_KEY" value={key} onChange={event => setKey(event.target.value)} />
              <Button type="submit" icon={<KeyRound />} disabled={!key.trim()}>Save key</Button>
              {hasKey && <Button variant="ghost" onClick={() => onApiKey('')}>Forget</Button>}
            </form>
          </div>
        </Card>

        <Card title="Budgets" description={`Scope: ${stringValue(budget.scope) || 'workspace'}`}>
          <KeyValue rows={[
            ['Daily budget', money(budget.daily_budget)],
            ['Monthly budget', money(budget.monthly_budget)],
            ['Max cost per run', money(budget.max_cost_per_run)],
            ['Max tokens per run', budget.max_tokens_per_run == null ? <span className="text-fg-subtle">not set</span> : formatNumber(budget.max_tokens_per_run)],
            ['Workflow budget', money(budget.workflow_budget)],
            ['Agent budget', money(budget.agent_budget)],
            ['Updated', budget.updated_at ? formatRelative(stringValue(budget.updated_at)) : null],
          ]} />
        </Card>

        <Card flush title="Providers">
          <DataTable
            rows={providers}
            rowKey={row => row.provider}
            minWidth={420}
            columns={[
              { label: 'Provider', sortValue: row => row.display_name, render: row => <span className="flex flex-col"><span className="font-medium text-fg">{row.display_name}</span><span className="font-mono text-[11px] text-fg-subtle">{row.provider}</span></span> },
              { label: 'Status', sortValue: row => row.status, render: row => <StatusBadge status={row.status} /> },
              { label: 'Calls', align: 'right', sortValue: row => row.calls, render: row => formatNumber(row.calls) },
            ]}
          />
        </Card>
      </div>

      <Card flush title="Audit log" description="Exports, replays, approvals, and configuration changes">
        <DataTable
          rows={auditLogs}
          minWidth={720}
          empty={<EmptyState title="No audit events" />}
          columns={[
            { label: 'Action', sortValue: row => stringValue(row.action), render: row => <span className="font-mono text-xs text-fg">{stringValue(row.action)}</span> },
            { label: 'Actor', sortValue: row => stringValue(row.actor), render: row => <span className="text-fg-muted">{stringValue(row.actor)}</span> },
            { label: 'Resource', render: row => <span className="text-fg-muted">{stringValue(row.resource) || '-'}</span> },
            { label: 'Trace', render: row => row.trace_id ? <CopyableId value={stringValue(row.trace_id)} /> : <span className="text-fg-subtle">-</span> },
            { label: 'When', align: 'right', sortValue: row => Date.parse(stringValue(row.timestamp)), render: row => <span className="text-fg-muted" title={formatDateTime(stringValue(row.timestamp))}>{formatRelative(stringValue(row.timestamp))}</span> },
          ]}
        />
      </Card>
    </>
  )
}
