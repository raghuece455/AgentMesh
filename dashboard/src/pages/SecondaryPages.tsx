import { AlertTriangle, Brain, CheckCircle2, CircleDollarSign, ClipboardCheck, Code2, Database, FileJson, KeyRound, Play, RotateCcw, ShieldCheck, UserCheck, WalletCards, Wrench, XCircle, Zap } from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { AgentSummary, ApprovalRecord, Checkpoint, CostCenterSummary, EvaluationRecord, EvaluationSummary, JsonRecord, MemoryOperation, MemoryRecord, ModelCallRecord, ModelUsage, PromptSummary, ProviderHealth, RagRetrieval, ReplayRun, SpanRecord, ToolCallRecord, TraceDetail, TraceSummary } from '../types'
import { ActionButton } from '../components/common/Actions'
import { Badge, CostStatusBadge, StatusBadge } from '../components/common/Badges'
import { AnswerCard, ChartFrame, EmptyState, MetricCard, Panel, PanelInset } from '../components/common/Cards'
import { JsonViewer } from '../components/common/JsonViewer'
import { DataTable } from '../components/tables/DataTable'
import { ProviderHealthPanel } from '../components/provider/ProviderHealthPanel'
import { KeyValueGrid } from '../components/trace/TraceInspector'
import { formatCost, formatDecimal, formatMoney, formatMs, formatNumber, formatPercent, formatTime, shortId, stringValue } from '../utils/format'

const chartColors = ['#38bdf8', '#2f8cff', '#5eead4', '#a3e635', '#fbbf24', '#fb7185', '#c084fc']

export function AgentsPage({ agents, traces, modelCalls, toolCalls, memoryOperations }: { agents: AgentSummary[]; traces: TraceSummary[]; modelCalls: ModelCallRecord[]; toolCalls: ToolCallRecord[]; memoryOperations: MemoryOperation[] }) {
  const current = agents[0]
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[420px_1fr]">
      <Panel title="Agents" icon={<Brain className="size-4" />}>
        <DataTable rows={agents} minWidth={520} columns={[{ label: 'Agent', render: row => row.agent_name }, { label: 'Status', render: row => <StatusBadge status={row.status} /> }, { label: 'Cost', render: row => formatCost(row.total_cost, row.total_cost ? 'estimated' : 'unknown') }]} />
      </Panel>
      <Panel title={current ? `${current.agent_name} Detail` : 'Agent Detail'} icon={<Brain className="size-4" />}>
        {current ? (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <AnswerCard label="Role" value={current.role ?? 'not set'} />
              <AnswerCard label="Model" value={`${current.provider ?? 'unknown'} / ${current.model ?? 'auto'}`} />
              <AnswerCard label="Success rate" value={formatPercent(current.success_rate)} />
              <AnswerCard label="Total cost" value={formatCost(current.total_cost, current.total_cost ? 'estimated' : 'unknown')} />
            </div>
            <PanelInset title="Recent traces">
              <div className="flex flex-col gap-2">{traces.slice(0, 8).map(trace => <div key={trace.trace_id} className="rounded-2xl bg-slate-950/20 p-3"><div className="text-sm/6 font-semibold text-white">{trace.workflow_name ?? trace.name}</div><div className="text-xs/5 text-white/52">{shortId(trace.trace_id)} / {trace.status}</div></div>)}</div>
            </PanelInset>
          </div>
        ) : <EmptyState title="No agents" />}
      </Panel>
    </div>
  )
}

export function ModelsPage({ providers, models, modelCalls }: { providers: ProviderHealth[]; models: ModelUsage[]; modelCalls: ModelCallRecord[] }) {
  return (
    <div className="flex flex-col gap-4">
      <Panel title="Provider Health" icon={<ShieldCheck className="size-4" />}>
        <ProviderHealthPanel providers={providers} />
      </Panel>
      <Panel title="Model Usage" icon={<Zap className="size-4" />}>
        <DataTable rows={models} columns={[{ label: 'Provider', render: row => row.provider }, { label: 'Model', render: row => row.model }, { label: 'Calls', render: row => row.calls }, { label: 'Tokens', render: row => formatNumber(row.total_tokens) }, { label: 'Cost', render: row => formatCost(row.estimated_cost, row.estimated_cost ? 'estimated' : row.provider === 'ollama' || row.provider === 'mock' ? 'local/free' : 'unknown') }, { label: 'Avg / P95', render: row => `${formatMs(row.avg_latency_ms)} / ${formatMs(row.p95_latency_ms)}` }, { label: 'Success', render: row => formatPercent(row.success_rate) }, { label: 'Settings', render: row => `t=${formatDecimal(row.temperature)} top_p=${formatDecimal(row.top_p)} max=${row.max_tokens ?? '-'}` }]} />
      </Panel>
      <Panel title="Recent Model Calls" icon={<FileJson className="size-4" />}>
        <DataTable rows={modelCalls.slice(0, 80)} columns={[{ label: 'Call', render: row => shortId(row.model_call_id) }, { label: 'Trace', render: row => shortId(row.trace_id) }, { label: 'Agent', render: row => row.agent_name ?? '-' }, { label: 'Provider / Model', render: row => `${row.provider ?? '-'} / ${row.model ?? '-'}` }, { label: 'Cost', render: row => formatCost(row.estimated_cost, row.cost_status) }, { label: 'Cost Status', render: row => <CostStatusBadge status={row.cost_status} /> }, { label: 'Latency', render: row => formatMs(row.duration_ms) }]} />
      </Panel>
    </div>
  )
}

export function CostsPage({ summary, byWorkflow, byAgent, byModel, byProvider, byFailedRun }: { summary: CostCenterSummary | null; byWorkflow: JsonRecord[]; byAgent: JsonRecord[]; byModel: JsonRecord[]; byProvider: JsonRecord[]; byFailedRun: JsonRecord[] }) {
  const tokenData = Object.entries(summary?.token_split ?? {}).map(([name, value]) => ({ name, value }))
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <MetricCard icon={<CircleDollarSign className="size-4" />} label="Spend today" value={formatMoney(summary?.total_spend_today)} tone="money" />
        <MetricCard icon={<WalletCards className="size-4" />} label="Projected month" value={formatMoney(summary?.projected_monthly_spend)} tone="money" />
        <MetricCard icon={<AlertTriangle className="size-4" />} label="Failed-run waste" value={formatMoney(summary?.cost_wasted_on_failed_runs)} tone="warn" />
        <MetricCard icon={<ShieldCheck className="size-4" />} label="Budget used" value={formatPercent(summary?.budget_used)} tone="money" />
      </div>
      <Panel title="Cost Confidence" icon={<ShieldCheck className="size-4" />}>
        <div className="flex flex-wrap gap-2">{Object.entries(summary?.cost_status_counts ?? {}).map(([status, count]) => <div key={status} className="inline-flex items-center gap-2 rounded-2xl border border-white/12 bg-slate-950/22 px-3 py-2"><CostStatusBadge status={status} /><span className="text-sm font-semibold text-white">{count}</span></div>)}</div>
      </Panel>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Panel title="Token Split" icon={<CircleDollarSign className="size-4" />} className="xl:col-span-4"><ChartFrame dense><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={tokenData} dataKey="value" nameKey="name" innerRadius={54} outerRadius={86} paddingAngle={4}>{tokenData.map((_, index) => <Cell key={index} fill={chartColors[index % chartColors.length]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer></ChartFrame></Panel>
        <Panel title="Cost By Workflow" icon={<CircleDollarSign className="size-4" />} className="xl:col-span-8"><CostBreakdown rows={byWorkflow} /></Panel>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Cost By Agent" icon={<Brain className="size-4" />}><CostBreakdown rows={byAgent} /></Panel>
        <Panel title="Cost By Model" icon={<Zap className="size-4" />}><CostBreakdown rows={byModel} /></Panel>
        <Panel title="Cost By Provider" icon={<ShieldCheck className="size-4" />}><CostBreakdown rows={byProvider} /></Panel>
        <Panel title="Cost By Failed Run" icon={<AlertTriangle className="size-4" />}><CostBreakdown rows={byFailedRun} /></Panel>
      </div>
    </div>
  )
}

function CostBreakdown({ rows }: { rows: JsonRecord[] }) {
  return <DataTable rows={rows} columns={[{ label: 'Name', render: row => stringValue(row.name ?? row.workflow_name ?? row.trace_id) }, { label: 'Calls', render: row => stringValue(row.calls ?? '-') }, { label: 'Tokens', render: row => formatNumber(row.total_tokens) }, { label: 'Cost', render: row => formatCost(row.estimated_cost, row.cost_status ? stringValue(row.cost_status) : numericOrUnknown(row.estimated_cost)) }, { label: 'Latency', render: row => formatMs(row.avg_latency_ms) }]} />
}

function numericOrUnknown(value: unknown) {
  return Number(value ?? 0) > 0 ? 'estimated' : 'unknown'
}

export function ToolsPage({ toolCalls }: { toolCalls: ToolCallRecord[] }) {
  const selected = toolCalls[0]
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_420px]">
      <Panel title="Tool Inspector" icon={<Wrench className="size-4" />}><DataTable rows={toolCalls} columns={[{ label: 'Tool call ID', render: row => shortId(row.tool_call_id) }, { label: 'Trace', render: row => shortId(row.trace_id) }, { label: 'Agent', render: row => row.agent_name ?? '-' }, { label: 'Tool', render: row => row.tool_name }, { label: 'Type', render: row => row.tool_type }, { label: 'Status', render: row => <StatusBadge status={row.status} /> }, { label: 'Risk', render: row => row.risk_level ?? '-' }, { label: 'Duration', render: row => formatMs(row.duration_ms) }]} /></Panel>
      <Panel title="Tool Detail" icon={<FileJson className="size-4" />}>{selected ? <JsonViewer value={selected} /> : <EmptyState title="Select a tool call" />}</Panel>
    </div>
  )
}

export function MemoryRagPage({ memoryRecords, operations, retrievals }: { memoryRecords: MemoryRecord[]; operations: MemoryOperation[]; retrievals: RagRetrieval[] }) {
  return (
    <div className="flex flex-col gap-4">
      <Panel title="Memory Operations" icon={<Database className="size-4" />}><DataTable rows={operations} columns={[{ label: 'Operation', render: row => row.operation }, { label: 'Trace', render: row => shortId(row.trace_id) }, { label: 'Agent', render: row => row.agent_name ?? '-' }, { label: 'Type', render: row => row.memory_type }, { label: 'Key', render: row => row.key ?? '-' }, { label: 'Version', render: row => row.version ?? '-' }, { label: 'Redacted', render: row => row.redacted ? 'yes' : 'no' }, { label: 'Time', render: row => formatTime(row.timestamp) }]} /></Panel>
      <Panel title="RAG Retrievals" icon={<Database className="size-4" />}><DataTable rows={retrievals} columns={[{ label: 'Retrieval', render: row => shortId(row.retrieval_id) }, { label: 'Trace', render: row => shortId(row.trace_id) }, { label: 'Agent', render: row => row.agent_name ?? '-' }, { label: 'Query', render: row => row.query ?? '-' }, { label: 'Store', render: row => row.vector_store ?? '-' }, { label: 'Chunks', render: row => row.chunk_ids.length }, { label: 'Used', render: row => row.used_in_answer ? 'yes' : 'no' }]} /></Panel>
      <Panel title="Memory Records" icon={<Database className="size-4" />}><DataTable rows={memoryRecords} columns={[{ label: 'Agent', render: row => row.agent }, { label: 'Namespace', render: row => row.namespace }, { label: 'Key', render: row => row.key }, { label: 'Version', render: row => row.version }, { label: 'Trace', render: row => row.trace_id ? shortId(row.trace_id) : '-' }, { label: 'Updated', render: row => formatTime(row.updated_at) }]} /></Panel>
    </div>
  )
}

export function PromptsPage({ prompts, detail }: { prompts: PromptSummary[]; detail: TraceDetail | null }) {
  const version = detail?.prompt_versions[0]
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_420px]">
      <Panel title="Prompt Registry" icon={<Code2 className="size-4" />}><DataTable rows={prompts} columns={[{ label: 'Prompt', render: row => row.prompt_name }, { label: 'Latest', render: row => shortId(row.latest_version) }, { label: 'Owner', render: row => row.owner }, { label: 'Usage', render: row => row.usage_count }, { label: 'Avg cost', render: row => formatCost(row.avg_cost, row.avg_cost ? 'estimated' : 'unknown') }, { label: 'Quality', render: row => row.avg_quality_score === null ? '-' : formatPercent(row.avg_quality_score) }, { label: 'Updated', render: row => formatTime(row.last_updated) }]} /></Panel>
      <Panel title="Prompt Version Detail" icon={<FileJson className="size-4" />}>{version ? <JsonViewer value={version} /> : <EmptyState title="Select a trace with prompts" />}</Panel>
    </div>
  )
}

export function EvaluationsPage({ summary, evaluations, onRun }: { summary: EvaluationSummary | null; evaluations: EvaluationRecord[]; onRun: () => void }) {
  return <div className="flex flex-col gap-4"><div className="grid grid-cols-1 gap-4 md:grid-cols-4"><MetricCard icon={<ClipboardCheck className="size-4" />} label="Task success" value={formatPercent(summary?.task_success_score)} tone="good" /><MetricCard icon={<ShieldCheck className="size-4" />} label="Schema pass rate" value={formatPercent(summary?.schema_validation_pass_rate)} /><MetricCard icon={<Database className="size-4" />} label="RAG faithfulness" value={summary?.rag_faithfulness_score == null ? 'planned' : formatPercent(summary.rag_faithfulness_score)} /><MetricCard icon={<AlertTriangle className="size-4" />} label="Hallucination risk" value={summary?.hallucination_risk == null ? 'planned' : formatPercent(summary.hallucination_risk)} /></div><Panel title="Evaluations" icon={<ClipboardCheck className="size-4" />} actions={<ActionButton icon={<Play className="size-4" />} label="Run mock eval" onClick={onRun} />}><DataTable rows={evaluations} columns={[{ label: 'Evaluation', render: row => shortId(row.evaluation_id) }, { label: 'Trace', render: row => row.trace_id ? shortId(row.trace_id) : '-' }, { label: 'Evaluator', render: row => row.evaluator }, { label: 'Type', render: row => row.evaluator_type }, { label: 'Score', render: row => row.score == null ? '-' : formatPercent(row.score) }, { label: 'Passed', render: row => row.passed == null ? '-' : row.passed ? 'yes' : 'no' }, { label: 'Created', render: row => formatTime(row.created_at) }]} /></Panel></div>
}

export function ApprovalsPage({ approvals, onApprove, onReject }: { approvals: ApprovalRecord[]; onApprove: (id: string) => void; onReject: (id: string) => void }) {
  return <Panel title="Approvals & Governance" icon={<UserCheck className="size-4" />}>{approvals.length === 0 && <EmptyState title="No approvals" />}{approvals.map(approval => <div key={approval.approval_id} className="mb-3 rounded-2xl border border-white/12 bg-slate-950/22 p-3"><div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between"><div><div className="flex flex-wrap items-center gap-2"><div className="text-sm/6 font-semibold text-white">{approval.tool}</div><StatusBadge status={approval.status} /><Badge tone={approval.risk_level === 'high' ? 'danger' : 'warn'}>{approval.risk_level ?? 'medium'}</Badge></div><div className="mt-1 text-xs/5 text-white/55">{approval.workflow ?? 'workflow'} / {approval.agent} / {approval.trace_id ? shortId(approval.trace_id) : '-'}</div><div className="mt-2 text-sm/6 text-white/72">{approval.reason}</div></div><div className="flex gap-2"><ActionButton icon={<CheckCircle2 className="size-4" />} label="Approve" onClick={() => onApprove(approval.approval_id)} /><ActionButton icon={<XCircle className="size-4" />} label="Reject" tone="danger" onClick={() => onReject(approval.approval_id)} /></div></div><JsonViewer value={approval.input_args ?? approval.arguments} compact /></div>)}</Panel>
}

export function ReplayPage({ checkpoints, replay, trace, selectedSpan, onReplay }: { checkpoints: Checkpoint[]; replay: ReplayRun | null; trace: TraceSummary | null; selectedSpan: SpanRecord | null; onReplay: (traceId: string, spanId?: string) => void }) {
  return <div className="grid grid-cols-1 gap-4 xl:grid-cols-[380px_1fr]"><Panel title="Replay Controls" icon={<RotateCcw className="size-4" />}><KeyValueGrid rows={[['Source trace', trace?.trace_id ? shortId(trace.trace_id) : '-'], ['Checkpoint', checkpoints[0]?.checkpoint_id ? shortId(checkpoints[0].checkpoint_id) : '-'], ['Selected span', selectedSpan?.span_id ? shortId(selectedSpan.span_id) : '-'], ['Mode', selectedSpan ? 'deterministic-from-span' : 'deterministic'], ['Semantics', 'recorded model/tool outputs'], ['Side effects', 'disabled']]} /><div className="mt-4 flex flex-col gap-2">{trace && <ActionButton icon={<Play className="size-4" />} label="Replay full trace" tone="purple" onClick={() => onReplay(trace.trace_id)} />}{trace && selectedSpan && <ActionButton icon={<RotateCcw className="size-4" />} label="Replay from selected span" tone="purple" onClick={() => onReplay(trace.trace_id, selectedSpan.span_id)} />}</div></Panel><Panel title="Replay Comparison" icon={<FileJson className="size-4" />}>{replay ? <JsonViewer value={replay} /> : <EmptyState title="Run a replay" />}</Panel></div>
}

export function SettingsPage({ auditLogs, providers, costs }: { auditLogs: JsonRecord[]; providers: ProviderHealth[]; costs: CostCenterSummary | null }) {
  return <div className="grid grid-cols-1 gap-4 xl:grid-cols-2"><Panel title="Budget Settings" icon={<WalletCards className="size-4" />}><JsonViewer value={costs?.budget_settings ?? {}} /></Panel><Panel title="Provider Configuration" icon={<KeyRound className="size-4" />}><ProviderHealthPanel providers={providers} /></Panel><Panel title="Audit Logs" icon={<ShieldCheck className="size-4" />} className="xl:col-span-2"><DataTable rows={auditLogs} columns={[{ label: 'Time', render: row => formatTime(stringValue(row.timestamp)) }, { label: 'Actor', render: row => stringValue(row.actor) }, { label: 'Action', render: row => stringValue(row.action) }, { label: 'Trace', render: row => row.trace_id ? shortId(String(row.trace_id)) : '-' }, { label: 'Resource', render: row => stringValue(row.resource) }]} /></Panel></div>
}
