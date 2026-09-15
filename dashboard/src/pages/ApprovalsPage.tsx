import { ArrowUpRight, Check, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { Badge, StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, PageHeader } from '../components/ui/Card'
import { JsonViewer } from '../components/ui/Code'
import { Tabs } from '../components/ui/Tabs'
import { cn } from '../lib/utils'
import type { ApprovalRecord } from '../types'
import { formatDateTime, formatRelative } from '../utils/format'

export const PENDING_APPROVAL = new Set(['pending', 'waiting_approval', 'requested'])

export function ApprovalsPage({ approvals, onApprove, onReject, onTrace }: { approvals: ApprovalRecord[]; onApprove: (id: string) => void; onReject: (id: string) => void; onTrace: (traceId: string) => void }) {
  const pending = approvals.filter(approval => PENDING_APPROVAL.has(approval.status))
  const resolved = approvals.filter(approval => !PENDING_APPROVAL.has(approval.status))
  const [tab, setTab] = useState<'pending' | 'resolved'>(pending.length ? 'pending' : 'resolved')
  const rows = tab === 'pending' ? pending : resolved

  return (
    <>
      <PageHeader title="Approvals" description="Risky tool calls wait here for a person to approve or reject them." />
      <Card flush>
        <Tabs
          className="px-2"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'pending', label: 'Pending', count: pending.length },
            { value: 'resolved', label: 'Resolved', count: resolved.length },
          ]}
        />
        {rows.length === 0
          ? <EmptyState icon={<ShieldCheck />} title={tab === 'pending' ? 'Nothing waiting for review' : 'No resolved approvals'} detail={tab === 'pending' ? 'Tool calls marked as requiring approval will appear here.' : undefined} />
          : (
              <ul className="divide-y divide-line">
                {rows.map(approval => {
                  const risk = approval.risk_level ?? 'medium'
                  return (
                    <li key={approval.approval_id} className={cn('flex flex-col gap-3 px-4 py-4', PENDING_APPROVAL.has(approval.status) && risk === 'high' && 'shadow-[inset_2px_0_0_var(--danger)]')}>
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-[14px] font-semibold text-fg">{approval.tool}</span>
                            <Badge tone={risk === 'high' ? 'danger' : risk === 'low' ? 'neutral' : 'warning'}>{risk} risk</Badge>
                            <StatusBadge status={approval.status} />
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-fg-muted">
                            <span>requested by <span className="text-fg">{approval.agent}</span></span>
                            {approval.workflow && <span>in {approval.workflow}</span>}
                            <span title={formatDateTime(approval.created_at)}>{formatRelative(approval.created_at)}</span>
                            {approval.resolved_at && <span>resolved {formatRelative(approval.resolved_at)}</span>}
                          </div>
                          {approval.reason && <p className="mt-1.5 text-[13px] text-fg">{approval.reason}</p>}
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2">
                          {approval.trace_id && <Button variant="ghost" size="sm" onClick={() => onTrace(approval.trace_id!)}>Trace<ArrowUpRight /></Button>}
                          {PENDING_APPROVAL.has(approval.status) && (
                            <>
                              <Button variant="danger" icon={<X />} onClick={() => onReject(approval.approval_id)}>Reject</Button>
                              <Button variant="primary" icon={<Check />} onClick={() => onApprove(approval.approval_id)}>Approve</Button>
                            </>
                          )}
                        </div>
                      </div>
                      <JsonViewer value={approval.input_args ?? approval.arguments} label="Arguments" maxHeight="max-h-48" />
                    </li>
                  )
                })}
              </ul>
            )}
      </Card>
    </>
  )
}
