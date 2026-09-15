import { BookOpen, CheckCircle2, Circle, KeyRound, Radio, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '../components/ui/Badge'
import { Card, PageHeader } from '../components/ui/Card'
import { CodeTabs, CopyableId } from '../components/ui/Code'
import type { IntegrationInfo } from '../types'

export function ConnectPage({ integrations, hasTraces }: { integrations: IntegrationInfo | null; hasTraces: boolean }) {
  const base = integrations?.otlp_base_endpoint ?? window.location.origin
  const endpoint = integrations?.otlp_traces_endpoint ?? `${base}/v1/traces`
  const auth = integrations?.auth_mode === 'api_key'
  const header = auth ? '\nexport OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20$AGENTMESH_API_KEY"' : ''

  const sdks = [
    {
      label: 'Python',
      language: 'python',
      code: `# pip install agentmesh-ai
import agentmesh

agentmesh.init(endpoint="${base}", service_name="my-agent")
agentmesh.instrument_openai()      # or instrument_anthropic()

@agentmesh.observe(kind="tool")
def search(query: str) -> list[str]: ...

with agentmesh.trace("support", session_id="chat-42", user_id="u-7"):
    answer = run_agent("Where is my order?")
    agentmesh.score("resolved", True)`,
    },
    {
      label: 'TypeScript',
      language: 'typescript',
      code: `// npm install agentmesh-sdk
import OpenAI from "openai"
import { init, instrumentOpenAI, observe, trace } from "agentmesh-sdk"

init({ endpoint: "${base}", serviceName: "my-agent"${auth ? ', apiKey: process.env.AGENTMESH_API_KEY' : ''} })
const openai = instrumentOpenAI(new OpenAI())

const search = observe(async (query: string) => [], { name: "search", kind: "tool" })

await trace("support", { sessionId: "chat-42" }, async () => {
  await search("Where is my order?")
})`,
    },
    {
      label: 'OpenTelemetry',
      language: 'shell',
      code: `# Any app that emits OpenTelemetry GenAI spans: OpenAI Agents SDK, Pydantic AI,
# LangGraph, CrewAI, Google ADK, Strands, Vercel AI SDK, ...
export OTEL_EXPORTER_OTLP_ENDPOINT="${base}"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"${header}`,
    },
  ]

  const frameworks = [
    {
      label: 'OpenAI Agents SDK',
      language: 'python',
      code: `# pip install openinference-instrumentation-openai-agents opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="${endpoint}")))
OpenAIAgentsInstrumentor().instrument(tracer_provider=provider)`,
    },
    {
      label: 'Pydantic AI',
      language: 'python',
      code: `from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import set_tracer_provider
from pydantic_ai import Agent

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="${endpoint}")))
set_tracer_provider(provider)
Agent.instrument_all()`,
    },
    {
      label: 'Coding agents (MCP)',
      language: 'shell',
      code: `# Let Claude Code, Cursor, or any MCP client query and diagnose your traces
claude mcp add agentmesh -- agentmesh mcp --db /absolute/path/.agentmesh/agentmesh.db`,
    },
  ]

  return (
    <>
      <PageHeader title="Connect your agents" description="Send traces from any framework, SDK, or OpenTelemetry exporter. Nothing to configure on the server." />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <InfoTile icon={<Radio />} label="OTLP traces endpoint" value={<CopyableId value={endpoint} full className="text-[13px] text-fg" />} />
        <InfoTile icon={<ShieldCheck />} label="Protobuf ingest" value={integrations?.protobuf_supported ? <Badge tone="success">enabled</Badge> : <span className="text-[13px] text-fg-muted">JSON only · pip install "agentmesh-ai[otlp]"</span>} />
        <InfoTile icon={<KeyRound />} label="Authentication" value={auth ? <Badge tone="success">API key required</Badge> : <Badge outline>off (local)</Badge>} />
        <InfoTile icon={<BookOpen />} label="Prompt and response capture" value={integrations?.capture_content === 'false' ? <Badge outline>off</Badge> : <Badge tone="accent">on</Badge>} />
      </div>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="1. Instrument your code" description="Pick the SDK for your language, or export from any OpenTelemetry setup.">
            <CodeTabs samples={sdks} />
          </Card>
          <Card title="2. Or use your framework's instrumentation" description="Frameworks with OpenTelemetry support work without the AgentMesh SDK.">
            <CodeTabs samples={frameworks} />
          </Card>
        </div>
        <Card title="Checklist" className="xl:sticky xl:top-20">
          <ol className="flex flex-col gap-3 text-[13px]">
            <Step done={Boolean(integrations)} title="Server is running" detail={`Version ${integrations?.version ?? '...'}`} />
            <Step done title={auth ? 'API key configured' : 'Authentication'} detail={auth ? 'Send Authorization: Bearer <key> with every request.' : 'Open for local use. Set AGENTMESH_AUTH_MODE=api_key before exposing it.'} />
            <Step done={hasTraces} title="First trace received" detail={hasTraces ? 'Traces are arriving. Open the Traces page to explore them.' : 'Run your instrumented code; traces appear within seconds.'} />
          </ol>
        </Card>
      </div>
    </>
  )
}

function InfoTile({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-xl border border-line bg-surface p-4 shadow-card">
      <span className="flex items-center gap-2 text-xs text-fg-muted [&_svg]:size-3.5 [&_svg]:text-fg-subtle">{icon}{label}</span>
      <div className="min-w-0">{value}</div>
    </div>
  )
}

function Step({ done, title, detail }: { done: boolean; title: string; detail: string }) {
  return (
    <li className="flex gap-2.5">
      {done ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <Circle className="mt-0.5 size-4 shrink-0 text-fg-subtle" />}
      <div>
        <div className="font-medium text-fg">{title}</div>
        <div className="text-fg-muted">{detail}</div>
      </div>
    </li>
  )
}
