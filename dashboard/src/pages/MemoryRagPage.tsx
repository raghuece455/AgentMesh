import { ArrowUpRight, Database, Search } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, EmptyState, KeyValue, PageHeader } from '../components/ui/Card'
import { CopyableId, JsonViewer } from '../components/ui/Code'
import { DataTable } from '../components/ui/DataTable'
import { Drawer } from '../components/ui/Overlay'
import { StatCard } from '../components/ui/Stat'
import { Tabs } from '../components/ui/Tabs'
import { ContentView } from '../components/trace/ContentView'
import type { MemoryOperation, MemoryRecord, RagRetrieval } from '../types'
import { formatDateTime, formatNumber, formatPercent, formatRelative } from '../utils/format'

type Selected = { kind: 'retrieval'; row: RagRetrieval } | { kind: 'operation'; row: MemoryOperation } | { kind: 'record'; row: MemoryRecord }

export function MemoryRagPage({ memoryRecords, operations, retrievals, onTrace }: { memoryRecords: MemoryRecord[]; operations: MemoryOperation[]; retrievals: RagRetrieval[]; onTrace: (traceId: string) => void }) {
  const [tab, setTab] = useState<'retrievals' | 'operations' | 'records'>('retrievals')
  const [selected, setSelected] = useState<Selected | null>(null)
  const used = retrievals.filter(item => item.used_in_answer).length
  const traceId = selected && 'trace_id' in selected.row ? selected.row.trace_id : null

  return (
    <>
      <PageHeader title="Memory & RAG" description="What agents retrieved, remembered, and actually used in their answers." />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Retrievals" icon={<Search />} value={formatNumber(retrievals.length)} />
        <StatCard label="Used in answer" value={retrievals.length ? formatPercent(used / retrievals.length) : '-'} tone={retrievals.length && used / retrievals.length < 0.5 ? 'warning' : 'neutral'} sub={`${used} of ${retrievals.length} retrievals`} />
        <StatCard label="Memory operations" icon={<Database />} value={formatNumber(operations.length)} />
        <StatCard label="Stored records" value={formatNumber(memoryRecords.length)} sub={`${new Set(memoryRecords.map(record => record.namespace)).size} namespaces`} />
      </div>

      <Card flush>
        <Tabs
          className="px-2"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'retrievals', label: 'Retrievals', count: retrievals.length },
            { value: 'operations', label: 'Memory operations', count: operations.length },
            { value: 'records', label: 'Memory records', count: memoryRecords.length },
          ]}
        />
        {tab === 'retrievals' && (
          <DataTable
            rows={retrievals}
            rowKey={row => row.retrieval_id}
            minWidth={820}
            onRow={row => setSelected({ kind: 'retrieval', row })}
            empty={<EmptyState icon={<Search />} title="No retrievals recorded" />}
            columns={[
              { label: 'Query', sortValue: row => row.query ?? '', render: row => <span className="line-clamp-1 max-w-md font-medium text-fg">{row.query ?? '-'}</span> },
              { label: 'Agent', sortValue: row => row.agent_name ?? '', render: row => <span className="text-fg-muted">{row.agent_name ?? '-'}</span> },
              { label: 'Store', render: row => row.vector_store ? <Badge outline>{row.vector_store}</Badge> : <span className="text-fg-subtle">-</span> },
              { label: 'Chunks', align: 'right', sortValue: row => row.chunk_ids.length, render: row => row.chunk_ids.length },
              { label: 'Used', sortValue: row => Number(row.used_in_answer), render: row => <Badge tone={row.used_in_answer ? 'success' : 'neutral'}>{row.used_in_answer ? 'used' : 'unused'}</Badge> },
              { label: 'When', align: 'right', sortValue: row => Date.parse(row.timestamp), render: row => <span className="text-fg-muted">{formatRelative(row.timestamp)}</span> },
            ]}
          />
        )}
        {tab === 'operations' && (
          <DataTable
            rows={operations}
            rowKey={row => row.operation_id}
            minWidth={820}
            onRow={row => setSelected({ kind: 'operation', row })}
            empty={<EmptyState icon={<Database />} title="No memory operations recorded" />}
            columns={[
              { label: 'Operation', sortValue: row => row.operation, render: row => <Badge tone={row.operation.includes('write') || row.operation.includes('set') ? 'warning' : 'info'}>{row.operation}</Badge> },
              { label: 'Key', sortValue: row => row.key ?? '', render: row => <span className="font-mono text-xs text-fg">{row.key ?? '-'}</span> },
              { label: 'Type', sortValue: row => row.memory_type, render: row => <span className="text-fg-muted">{row.memory_type}</span> },
              { label: 'Agent', sortValue: row => row.agent_name ?? '', render: row => <span className="text-fg-muted">{row.agent_name ?? '-'}</span> },
              { label: 'Preview', render: row => row.redacted ? <Badge outline>redacted</Badge> : <span className="line-clamp-1 max-w-xs text-xs text-fg-muted">{row.value_preview ?? '-'}</span> },
              { label: 'When', align: 'right', sortValue: row => Date.parse(row.timestamp), render: row => <span className="text-fg-muted">{formatRelative(row.timestamp)}</span> },
            ]}
          />
        )}
        {tab === 'records' && (
          <DataTable
            rows={memoryRecords}
            rowKey={row => `${row.agent}:${row.namespace}:${row.key}`}
            minWidth={720}
            onRow={row => setSelected({ kind: 'record', row })}
            empty={<EmptyState icon={<Database />} title="No memory records" />}
            columns={[
              { label: 'Key', sortValue: row => row.key, render: row => <span className="font-mono text-xs font-medium text-fg">{row.key}</span> },
              { label: 'Namespace', sortValue: row => row.namespace, render: row => <Badge outline>{row.namespace}</Badge> },
              { label: 'Agent', sortValue: row => row.agent, render: row => <span className="text-fg-muted">{row.agent}</span> },
              { label: 'Version', align: 'right', sortValue: row => row.version, render: row => `v${row.version}` },
              { label: 'Updated', align: 'right', sortValue: row => Date.parse(row.updated_at), render: row => <span className="text-fg-muted">{formatRelative(row.updated_at)}</span> },
            ]}
          />
        )}
      </Card>

      <Drawer
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        width="max-w-2xl"
        title={selected?.kind === 'retrieval' ? 'Retrieval' : selected?.kind === 'operation' ? 'Memory operation' : 'Memory record'}
        footer={traceId && <Button variant="primary" icon={<ArrowUpRight />} onClick={() => { setSelected(null); onTrace(traceId) }}>Open trace</Button>}
      >
        {selected?.kind === 'retrieval' && (
          <div className="flex flex-col gap-4">
            <ContentView value={selected.row.query} emptyTitle="No query captured" />
            <KeyValue rows={[
              ['Agent', selected.row.agent_name],
              ['Vector store', selected.row.vector_store],
              ['Embedding model', selected.row.embedding_model],
              ['Used in answer', selected.row.used_in_answer ? 'yes' : 'no'],
              ['When', formatDateTime(selected.row.timestamp)],
              ['Trace', <CopyableId value={selected.row.trace_id} />],
            ]} />
            {selected.row.chunk_preview && <ContentView value={selected.row.chunk_preview} />}
            <JsonViewer value={{ documents: selected.row.retrieved_documents, scores: selected.row.scores, citations: selected.row.citation_mapping }} label="Documents" />
          </div>
        )}
        {selected?.kind === 'operation' && <JsonViewer value={selected.row} label="Operation" />}
        {selected?.kind === 'record' && <JsonViewer value={selected.row} label="Record" />}
      </Drawer>
    </>
  )
}
