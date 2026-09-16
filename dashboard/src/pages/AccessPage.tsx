import { AlertTriangle, ArrowUpRight, Database, Globe, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { getAccessSummary, listAccess } from '../api'
import { KindBadge, KindIcon } from '../components/access/KindBadge'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Callout, Card, EmptyState, PageHeader, Skeleton } from '../components/ui/Card'
import { CodeBlock } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { SearchInput } from '../components/ui/Field'
import { StatCard } from '../components/ui/Stat'
import { Segmented } from '../components/ui/Tabs'
import { cn } from '../lib/utils'
import type { AccessDestination, AccessRecord } from '../types'
import { errorText, formatDateTime, formatNumber, formatRelative } from '../utils/format'

const RANGE_HOURS: Record<string, number | undefined> = { '1h': 1, '24h': 24, '7d': 24 * 7, '30d': 24 * 30, all: undefined }

const SETUP = `# Recorded for you: HTTP spans (url.full / server.address), URLs in tool
# arguments, retrievals, memory operations, db.system / file.path attributes.

agentmesh.record_access("customers.invoices", kind="db", operation="read", detail="200 rows")

# Block anything off the allowlist, before the call is made:
#   rules:
#     - name: approved-domains-only
#       match: {kind: tool, host: "*"}
#       except: {host: ["*.mycompany.com", "api.openai.com"]}
#       action: deny`

export function AccessPage({ refreshKey, range, onTrace }: { refreshKey: string | null; range: string; onTrace: (traceId: string, spanId?: string) => void }) {
  const [destinations, setDestinations] = useState<AccessDestination[] | null>(null)
  const [selected, setSelected] = useState<AccessDestination | null>(null)
  const [records, setRecords] = useState<AccessRecord[]>([])
  const [filter, setFilter] = useState<'all' | 'network' | 'data'>('all')
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const hours = RANGE_HOURS[range]

  useEffect(() => {
    let cancelled = false
    getAccessSummary({ hours, limit: 300 })
      .then((result) => { if (!cancelled) { setDestinations(result); setError('') } })
      .catch((caught) => { if (!cancelled) setError(errorText(caught)) })
    return () => { cancelled = true }
  }, [refreshKey, hours])

  useEffect(() => {
    if (!selected) {
      setRecords([])
      return
    }
    let cancelled = false
    listAccess({ kind: selected.kind, target: selected.target, exact: true, hours, limit: 100 })
      .then((result) => { if (!cancelled) setRecords(result) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [selected, hours, refreshKey])

  const rows = useMemo(() => {
    const term = query.trim().toLowerCase()
    return (destinations ?? [])
      .filter(item => filter === 'all' || (filter === 'network' ? item.kind === 'network' : item.kind !== 'network'))
      .filter(item => !term || item.target.toLowerCase().includes(term))
  }, [destinations, filter, query])

  const totals = useMemo(() => (destinations ?? []).reduce((sum, item) => ({
    hosts: sum.hosts + (item.kind === 'network' ? 1 : 0),
    resources: sum.resources + (item.kind === 'network' ? 0 : 1),
    fresh: sum.fresh + (item.is_new ? 1 : 0),
    errors: sum.errors + item.errors,
  }), { hosts: 0, resources: 0, fresh: 0, errors: 0 }), [destinations])

  return (
    <>
      <PageHeader
        title="Access"
        description="Every host your agents reached and every store they read or wrote — from HTTP spans, URLs in tool calls, retrievals, memory, and databases."
      />
      {error && <Callout tone="danger" title="Could not load access records">{error}</Callout>}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Hosts reached" icon={<Globe />} value={formatNumber(totals.hosts)} sub="Outbound destinations" onClick={() => setFilter('network')} />
        <StatCard label="Data resources" icon={<Database />} value={formatNumber(totals.resources)} sub="Indexes, memory, tables, files" onClick={() => setFilter('data')} />
        <StatCard label="New in range" icon={<Sparkles />} value={hours ? formatNumber(totals.fresh) : '-'} tone={totals.fresh ? 'warning' : 'neutral'} sub={hours ? 'First seen in this range' : 'Pick a time range'} />
        <StatCard label="Failed accesses" icon={<AlertTriangle />} value={formatNumber(totals.errors)} tone={totals.errors ? 'danger' : 'neutral'} sub="Calls that ended in error" />
      </div>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        <Card
          flush
          title="Destinations and resources"
          actions={(
            <div className="flex items-center gap-2">
              <SearchInput value={query} onChange={setQuery} placeholder="Host or resource" className="w-48" />
              <Segmented
                size="sm"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'network', label: 'Network' },
                  { value: 'data', label: 'Data' },
                ]}
              />
            </div>
          )}
        >
          {destinations === null && !error
            ? <div className="flex flex-col gap-2 p-4">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-9" />)}</div>
            : destinations?.length === 0
              ? (
                  <div className="flex flex-col gap-4 p-4">
                    <EmptyState icon={<Globe />} title="Nothing recorded yet" detail="Access records come from your traces: HTTP spans, URLs in tool arguments, retrievals, memory operations, and anything an agent records itself." />
                    <CodeBlock code={SETUP} language="python" />
                  </div>
                )
              : (
                  <DataTable
                    rows={rows}
                    rowKey={row => `${row.kind}:${row.target}`}
                    minWidth={820}
                    maxHeight="max-h-[70vh]"
                    onRow={row => setSelected(current => current?.target === row.target && current?.kind === row.kind ? null : row)}
                    selectedRow={row => selected?.target === row.target && selected?.kind === row.kind}
                    rowClassName={row => row.errors ? 'shadow-[inset_2px_0_0_var(--danger)]' : ''}
                    empty={<EmptyState title="No matching destinations" />}
                    initialSort={{ column: 2, desc: true }}
                    columns={[
                      { label: 'Kind', width: '110px', sortValue: row => row.kind, render: row => <KindBadge kind={row.kind} /> },
                      {
                        label: 'Target',
                        sortValue: row => row.target,
                        render: row => (
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate font-mono text-[12.5px] text-fg" title={row.target}>{row.target}</span>
                            {row.is_new && <Badge tone="warning">new</Badge>}
                          </span>
                        ),
                      },
                      { label: 'Accesses', align: 'right', sortValue: row => row.calls, render: row => <span className="tabular text-fg">{formatNumber(row.calls)}</span> },
                      { label: 'Agents', align: 'right', sortValue: row => row.agents, render: row => <span className="tabular text-fg-muted">{formatNumber(row.agents)}</span> },
                      { label: 'Traces', align: 'right', sortValue: row => row.traces, render: row => <span className="tabular text-fg-muted">{formatNumber(row.traces)}</span> },
                      { label: 'Errors', align: 'right', sortValue: row => row.errors, render: row => <span className={cn('tabular', row.errors ? 'font-medium text-danger-text' : 'text-fg-subtle')}>{formatNumber(row.errors)}</span> },
                      { label: 'Last used', align: 'right', sortValue: row => Date.parse(row.last_seen) || 0, render: row => <span className="whitespace-nowrap text-fg-muted" title={formatDateTime(row.last_seen)}>{formatRelative(row.last_seen)}</span> },
                    ]}
                  />
                )}
        </Card>

        <div className="xl:sticky xl:top-20">
          {selected
            ? (
                <Card
                  flush
                  icon={<KindIcon kind={selected.kind} />}
                  title={<span className="font-mono text-[13px]">{selected.target}</span>}
                  description={`${formatNumber(selected.calls)} ${selected.calls === 1 ? 'access' : 'accesses'} by ${formatNumber(selected.agents)} ${selected.agents === 1 ? 'agent' : 'agents'} · first seen ${formatRelative(selected.first_seen)}`}
                >
                  {records.length === 0
                    ? <EmptyState title="No recent accesses" />
                    : (
                        <ol className="max-h-[60vh] divide-y divide-line overflow-y-auto">
                          {records.map(record => (
                            <li key={record.access_id} className="flex items-start gap-2 px-4 py-2.5">
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
                                  <span className="font-medium text-fg">{record.agent ?? 'unknown agent'}</span>
                                  <Badge outline>{record.operation}</Badge>
                                  {record.status === 'failed' && <Badge tone="danger">failed</Badge>}
                                </div>
                                {record.detail && <p className="mt-0.5 truncate font-mono text-[11px] text-fg-subtle" title={record.detail}>{record.detail}</p>}
                                <p className="mt-0.5 text-xs text-fg-subtle" title={formatDateTime(record.created_at)}>{formatRelative(record.created_at)}{record.service ? ` · ${record.service}` : ''}</p>
                              </div>
                              <Button size="icon-sm" variant="ghost" aria-label="Open trace" title="Open trace" onClick={() => onTrace(record.trace_id, record.span_id ?? undefined)}><ArrowUpRight /></Button>
                            </li>
                          ))}
                        </ol>
                      )}
                </Card>
              )
            : (
                <Card title="Select a destination" icon={<Globe />}>
                  <p className="text-[13px] text-fg-muted">Pick a host or resource to see which agents reached it, when, and from which run.</p>
                  <p className="mt-2 text-[13px] text-fg-muted">A policy rule with <span className="font-mono text-xs">host</span> blocks calls to anything off your allowlist before they are made — see Guardrails.</p>
                </Card>
              )}
        </div>
      </div>
    </>
  )
}
