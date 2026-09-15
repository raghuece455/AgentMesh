import { Code2 } from 'lucide-react'
import { Card, EmptyState, Meter, PageHeader } from '../components/ui/Card'
import { CopyableId } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { StatCard } from '../components/ui/Stat'
import type { PromptSummary } from '../types'
import { formatMoney, formatNumber, formatPercent, formatRelative, numeric } from '../utils/format'

export function PromptsPage({ prompts }: { prompts: PromptSummary[] }) {
  const uses = prompts.reduce((sum, prompt) => sum + prompt.usage_count, 0)
  const scored = prompts.filter(prompt => prompt.avg_quality_score !== null)
  const maxUses = Math.max(...prompts.map(prompt => prompt.usage_count), 0)
  return (
    <>
      <PageHeader title="Prompts" description="Every distinct prompt version your agents sent, with usage, cost, and quality." />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Prompt versions" icon={<Code2 />} value={formatNumber(prompts.length)} sub={`${new Set(prompts.map(prompt => prompt.prompt_name)).size} prompt names`} />
        <StatCard label="Uses" value={formatNumber(uses)} />
        <StatCard label="Owners" value={formatNumber(new Set(prompts.map(prompt => prompt.owner)).size)} />
        <StatCard label="Avg quality" value={scored.length ? formatPercent(scored.reduce((sum, prompt) => sum + numeric(prompt.avg_quality_score), 0) / scored.length) : '-'} sub={`${scored.length} versions scored`} />
      </div>
      <Card flush title="Prompt versions">
        <DataTable
          rows={prompts}
          rowKey={(row, index) => `${row.prompt_hash}-${index}`}
          minWidth={820}
          initialSort={{ column: 2 }}
          empty={<EmptyState icon={<Code2 />} title="No prompts recorded" detail="Prompt versions are captured when agents send system and user prompts through the runtime or SDK." />}
          columns={[
            { label: 'Prompt', sortValue: row => row.prompt_name, render: row => <span className="flex flex-col"><span className="font-medium text-fg">{row.prompt_name}</span><CopyableId value={row.prompt_hash} /></span> },
            { label: 'Owner', sortValue: row => row.owner, render: row => <span className="text-fg-muted">{row.owner}</span> },
            { label: 'Uses', width: '170px', sortValue: row => row.usage_count, render: row => <span className="flex items-center gap-2"><Meter value={row.usage_count} max={maxUses} /><span className="tabular w-8 text-right">{row.usage_count}</span></span> },
            { label: 'Avg cost', align: 'right', sortValue: row => row.avg_cost, render: row => numeric(row.avg_cost) ? formatMoney(row.avg_cost) : <span className="text-fg-subtle">-</span> },
            { label: 'Quality', align: 'right', sortValue: row => row.avg_quality_score ?? -1, render: row => row.avg_quality_score === null ? <span className="text-fg-subtle">-</span> : formatPercent(row.avg_quality_score) },
            { label: 'Version', render: row => <CopyableId value={row.latest_version} /> },
            { label: 'Updated', align: 'right', sortValue: row => Date.parse(row.last_updated), render: row => <span className="text-fg-muted">{formatRelative(row.last_updated)}</span> },
          ]}
        />
      </Card>
    </>
  )
}
