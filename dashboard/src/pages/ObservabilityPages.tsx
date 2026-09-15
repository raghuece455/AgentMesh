import { Bot, Check, Copy, MessagesSquare, Plug, Terminal, User } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { getSession } from '../api'
import type { IntegrationInfo, SessionDetail, SessionSummary } from '../types'
import { Badge, CopyableId, StatusBadge } from '../components/common/Badges'
import { AnswerCard, EmptyState, Panel } from '../components/common/Cards'
import { DataTable } from '../components/tables/DataTable'
import { formatCost, formatMs, formatNumber, formatTime, jsonPreview } from '../utils/format'

export function SessionsPage({ sessions, onTraceSelect }: { sessions: SessionSummary[]; onTraceSelect: (traceId: string) => void }) {
  const [selectedId, setSelectedId] = useState<string>('')
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [error, setError] = useState('')
  const activeId = selectedId || sessions[0]?.session_id || ''

  useEffect(() => {
    if (!activeId) {
      setDetail(null)
      return
    }
    let cancelled = false
    getSession(activeId)
      .then(result => { if (!cancelled) { setDetail(result); setError('') } })
      .catch(caught => { if (!cancelled) setError(caught instanceof Error ? caught.message : 'Could not load session') })
    return () => { cancelled = true }
  }, [activeId])

  if (sessions.length === 0) {
    return (
      <Panel title="Sessions" icon={<MessagesSquare className="size-4" />}>
        <EmptyState
          icon={<MessagesSquare className="size-5" />}
          title="No sessions yet"
          detail="Group multi-turn conversations by setting a session id: agentmesh.trace(..., session_id=...) in the SDK, or the gen_ai.conversation.id / session.id attribute on OpenTelemetry spans."
        />
      </Panel>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[460px_minmax(0,1fr)]">
      <Panel title="Sessions" icon={<MessagesSquare className="size-4" />}>
        <DataTable
          rows={sessions}
          minWidth={420}
          onRow={row => setSelectedId(row.session_id)}
          selectedRow={row => row.session_id === activeId}
          columns={[
            { label: 'Session', render: row => <span className="font-semibold text-white">{row.session_id}</span>, sortValue: row => row.session_id },
            { label: 'Turns', render: row => row.trace_count, sortValue: row => row.trace_count },
            { label: 'Failed', render: row => row.failed_traces ? <Badge tone="danger">{row.failed_traces}</Badge> : '0', sortValue: row => row.failed_traces },
            { label: 'Cost', render: row => formatCost(row.estimated_cost, row.estimated_cost ? 'estimated' : 'unknown'), sortValue: row => row.estimated_cost },
            { label: 'Last activity', render: row => formatTime(row.last_activity_at), sortValue: row => Date.parse(row.last_activity_at) },
          ]}
        />
      </Panel>
      <Panel title={detail ? `Session ${detail.session_id}` : 'Session'} icon={<MessagesSquare className="size-4" />}>
        {error && <EmptyState title="Could not load session" detail={error} />}
        {!error && !detail && <EmptyState title="Select a session" />}
        {detail && (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <AnswerCard label="User" value={detail.user_id ?? 'anonymous'} />
              <AnswerCard label="Turns" value={detail.trace_count} />
              <AnswerCard label="Failed turns" value={detail.failed_traces} tone={detail.failed_traces ? 'danger' : 'good'} />
              <AnswerCard label="Tokens" value={formatNumber(detail.total_tokens)} />
              <AnswerCard label="Cost" value={formatCost(detail.estimated_cost, detail.estimated_cost ? 'estimated' : 'unknown')} />
            </div>
            <div className="vision-scroll flex max-h-[720px] flex-col gap-3 overflow-auto pr-1">
              {detail.traces.map((trace, index) => {
                const scores = detail.scores.filter(score => score.trace_id === trace.trace_id)
                return (
                  <div key={trace.trace_id} className="rounded-2xl border border-white/12 bg-slate-950/22 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone="info">Turn {index + 1}</Badge>
                        <span className="text-sm/6 font-semibold text-white">{trace.workflow_name ?? trace.name}</span>
                        <StatusBadge status={trace.status} />
                        {scores.map(score => <Badge key={score.score_id} tone={score.value === 0 || score.passed === false ? 'danger' : 'good'}>{score.name}: {score.label ?? score.value}</Badge>)}
                      </div>
                      <div className="flex items-center gap-2 text-xs/5 text-white/58">
                        <span>{formatTime(trace.started_at)}</span>
                        <span>{formatMs(trace.duration_ms)}</span>
                        <button className="rounded-xl border border-white/14 px-2 py-1 font-semibold text-white/82 hover:bg-white/12" onClick={() => onTraceSelect(trace.trace_id)}>Open trace</button>
                      </div>
                    </div>
                    <Message icon={<User className="size-3.5" />} label="Input" value={trace.input} />
                    <Message icon={<Bot className="size-3.5" />} label={trace.status === 'failed' ? 'Error' : 'Output'} value={trace.status === 'failed' ? trace.error_message ?? trace.output : trace.output} danger={trace.status === 'failed'} />
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </Panel>
    </div>
  )
}

function Message({ icon, label, value, danger = false }: { icon: ReactNode; label: string; value: unknown; danger?: boolean }) {
  if (value === null || value === undefined || value === '')
    return null
  return (
    <div className={`mt-2 rounded-xl p-2 text-sm/6 ${danger ? 'bg-rose-500/12 text-rose-50' : 'bg-white/6 text-white/84'}`}>
      <div className="mb-1 flex items-center gap-1 text-xs/5 font-semibold text-white/55">{icon}{label}</div>
      <div className="line-clamp-6 whitespace-pre-wrap break-words">{typeof value === 'string' ? value : jsonPreview(value)}</div>
    </div>
  )
}

export function ConnectPage({ integrations }: { integrations: IntegrationInfo | null }) {
  const base = integrations?.otlp_base_endpoint ?? window.location.origin
  const auth = integrations?.auth_mode === 'api_key'
  const header = auth ? '\nexport OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20$AGENTMESH_API_KEY"' : ''
  const snippets: Array<{ title: string; detail: string; code: string }> = [
    {
      title: 'Any OpenTelemetry app',
      detail: 'Every framework that emits OpenTelemetry GenAI spans (OpenAI Agents SDK, Pydantic AI, LangGraph, CrewAI, Google ADK, Strands, Vercel AI SDK, ...) can export straight to AgentMesh.',
      code: `export OTEL_EXPORTER_OTLP_ENDPOINT="${base}"\nexport OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"${header}`,
    },
    {
      title: 'Python SDK (any code)',
      detail: 'Decorate functions; nested calls become a span tree with sessions, users, and scores.',
      code: `import agentmesh\n\nagentmesh.init(endpoint="${base}", service_name="my-agent")\nagentmesh.instrument_openai()      # or instrument_anthropic()\n\n@agentmesh.observe(kind="tool")\ndef search(query: str) -> list[str]: ...\n\nwith agentmesh.trace("support", session_id="chat-42", user_id="u-7"):\n    answer = run_agent("Where is my order?")\n    agentmesh.score("resolved", True)`,
    },
    {
      title: 'TypeScript / JavaScript SDK',
      detail: 'npm install agentmesh-sdk. Works with any Node.js agent code, the OpenAI and Anthropic SDKs, and runs experiments too.',
      code: `import OpenAI from "openai"
import { init, instrumentOpenAI, observe, trace } from "agentmesh-sdk"

init({ endpoint: "${base}", serviceName: "my-agent"${auth ? ', apiKey: process.env.AGENTMESH_API_KEY' : ''} })
const openai = instrumentOpenAI(new OpenAI())

const search = observe(async (query) => [], { name: "search", kind: "tool" })

await trace("support", { sessionId: "chat-42" }, async () => {
  await search("Where is my order?")
})`,
    },
    {
      title: 'OpenAI Agents SDK',
      detail: 'pip install openinference-instrumentation-openai-agents opentelemetry-sdk opentelemetry-exporter-otlp-proto-http',
      code: `from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor\nfrom opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter\nfrom opentelemetry.sdk.trace import TracerProvider\nfrom opentelemetry.sdk.trace.export import BatchSpanProcessor\n\nprovider = TracerProvider()\nprovider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="${base}/v1/traces")))\nOpenAIAgentsInstrumentor().instrument(tracer_provider=provider)`,
    },
    {
      title: 'Pydantic AI',
      detail: 'Pydantic AI emits GenAI semantic-convention spans natively.',
      code: `from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter\nfrom opentelemetry.sdk.trace import TracerProvider\nfrom opentelemetry.sdk.trace.export import BatchSpanProcessor\nfrom opentelemetry.trace import set_tracer_provider\nfrom pydantic_ai import Agent\n\nprovider = TracerProvider()\nprovider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="${base}/v1/traces")))\nset_tracer_provider(provider)\nAgent.instrument_all()`,
    },
    {
      title: 'Coding agents (MCP)',
      detail: 'Let Claude Code, Cursor, or any MCP client query and diagnose your traces.',
      code: 'claude mcp add agentmesh -- agentmesh mcp --db /absolute/path/.agentmesh/agentmesh.db',
    },
  ]
  return (
    <div className="flex flex-col gap-4">
      <Panel title="Connect your agents" icon={<Plug className="size-4" />}>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <AnswerCard label="OTLP traces endpoint" value={<CopyableId value={integrations?.otlp_traces_endpoint ?? `${base}/v1/traces`} label={integrations?.otlp_traces_endpoint ?? `${base}/v1/traces`} />} />
          <AnswerCard label="Protobuf ingest" value={integrations?.protobuf_supported ? 'enabled' : 'JSON only (pip install "agentmesh-ai[otlp]")'} tone={integrations?.protobuf_supported ? 'good' : 'warn'} />
          <AnswerCard label="Auth" value={auth ? 'API key required' : 'disabled (local)'} tone={auth ? 'good' : 'neutral'} />
          <AnswerCard label="Prompt/response capture" value={integrations?.capture_content === 'false' ? 'off' : 'on'} />
        </div>
      </Panel>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {snippets.map(snippet => (
          <Panel key={snippet.title} title={snippet.title} icon={<Terminal className="size-4" />}>
            <p className="mb-3 text-sm/6 text-white/68">{snippet.detail}</p>
            <CodeBlock code={snippet.code} />
          </Panel>
        ))}
      </div>
    </div>
  )
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="overflow-hidden rounded-2xl border border-white/12 bg-slate-950/60">
      <div className="flex justify-end border-b border-white/8 px-2 py-1.5">
        <CopyButton code={code} copied={copied} onCopied={setCopied} />
      </div>
      <pre className="vision-scroll overflow-auto p-3 text-xs/5 text-sky-50"><code>{code}</code></pre>
    </div>
  )
}

function CopyButton({ code, copied, onCopied }: { code: string; copied: boolean; onCopied: (value: boolean) => void }) {
  return (
      <button
        className="inline-flex items-center gap-1 rounded-xl border border-white/14 bg-slate-900/80 px-2 py-1 text-xs/5 font-semibold text-white/80 hover:bg-white/14"
        onClick={() => {
          void navigator.clipboard.writeText(code)
          onCopied(true)
          window.setTimeout(() => onCopied(false), 1500)
        }}
      >
        {copied ? <Check className="size-3" /> : <Copy className="size-3" />}{copied ? 'Copied' : 'Copy'}
      </button>
  )
}
