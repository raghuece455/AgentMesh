# Roadmap

AgentMesh is built around one core thesis: production agent systems need orchestration and observability as one runtime, not bolted on separately.

This roadmap reflects the current plan. Community feedback shapes priorities — open a [GitHub Discussion](https://github.com/raghuece455/AgentMesh/discussions) to influence what we build next.

---

## Released: v0.4 — Observe any agent

- OTLP/HTTP trace receiver with OpenTelemetry GenAI semantic-convention, OpenInference, OpenLLMetry and Vercel AI SDK mapping.
- Python tracing SDK (`@observe`, `trace`, `span`, `score`) and OpenAI/Anthropic client auto-instrumentation.
- Sessions, users, tags, scores and dashboard feedback.
- Automatic trace insights: root cause, loops, repeated prompts, context growth, cache usage, hotspots.
- MCP server so coding agents can query and diagnose traces.
- Per-million-token pricing with cache rates, current model prices, and community price sync.
- Retention pruning and content-capture controls.
- TypeScript SDK (`agentmesh-sdk`) with OpenAI/Anthropic auto-instrumentation and experiments.
- Datasets (from traces, JSONL, or by hand), experiments, item-by-item comparison, and CI gating.
- Built-in evaluators and LLM-as-judge; online evaluation of recorded traces.
- Alerts for failure rate/count, spend, expensive traces, p95 latency, and tool loops, with Slack, Discord, and signed webhooks.
- PostgreSQL storage for every feature.

## Released: v0.5.0 — Stop agents, not just watch them

- **Guardrails, approvals, and the kill switch** — policies that deny, pause for approval, or limit tool calls, LLM calls, and agents before they run; loop, spend, depth, and fan-out limits; monitor mode and simulation on recorded traces; a kill switch. Python SDK, OpenAI/Anthropic instrumentation, and the runtime first; TypeScript SDK enforcement next.
- **Agent swarms** — swarm runs across traces and processes (SDK and OpenTelemetry), the swarm graph with roles, messages and handoffs, activity and insights, swarm halts, and swarm-wide limits counted across processes (agents, concurrency, spawn rate, spend, tokens, runtime). Anomaly alerts fire on swarm size, spawn rate, spend, failures, agents looping between each other, and new destinations.
- **Egress and data access** — hosts agents reached and data they read, recorded from spans; `host` rules that block a call to an unapproved domain before it is made; the Access page, CLI, API, and MCP tool, and `new_destination` alerts for anything reached for the first time.

---

## Next: v0.6 — Scale and reach

- **Guardrails in the TypeScript SDK** — the same policy format and enforcement points as Python, so a Node agent is stopped by the same rules.
- **OTLP logs** — ingest GenAI content events sent as OTel log records (e.g. Claude Code telemetry).
- **gRPC OTLP receiver** — accept the Collector's default protocol without a relay.
- **ClickHouse backend** — for very high span volumes and long retention.
- **Scheduled online evaluation** — run evaluators on new traces from the server, with sampling.
- **More auto-instrumentation** — Gemini, Bedrock, Mistral, and LiteLLM clients in both SDKs.
- **Prompt management** — versioned prompts linked to the experiments that tested them.
- **Login and RBAC** — per-user accounts and project-level access control.

---

## Released: v0.3.0-alpha

- Trace-first execution with SQLite and PostgreSQL persistence.
- Full React dashboard: trace explorer, workflow graph, cost center, tool inspector, memory & RAG, replay studio, failure inbox, provider health.
- 7 model providers: Mock, OpenAI-compatible, Anthropic, Gemini, Ollama, vLLM, Router.
- Deterministic replay from checkpoints; time-travel debugging.
- Human approval gates for sensitive tools.
- Cost governance: token/cost budgets, circuit breaker, retry policy.
- OpenTelemetry-compatible JSON export.
- Docker Compose one-command demo.
- 20 runnable examples.
- CLI: traces, replay, costs, validate, diagnose, demo seed.

---

## Later — Integration & Extensibility

Focus: make AgentMesh easier to drop into existing stacks.

- **MCP client transports** — stdio and streamable HTTP client for Model Context Protocol servers.
- **Plugin discovery** — Python entry points (`agentmesh.plugins`) for community-installable providers, tools, and evaluators.
- **Prompt regression snapshots** — diff prompt versions across runs.
- **Dashboard run diff** — side-by-side trace comparison UI.
- **More provider adapters** — AWS Bedrock, Groq, Mistral, Cohere.

---

## Later — Scale & Reliability

Focus: make AgentMesh viable for teams and higher-throughput workflows.

- **Distributed workers** — Redis or NATS coordination for multi-process agent execution.
- **PostgreSQL background job queue** — persistent task scheduling backed by PostgreSQL.
- **Evaluator trend dashboards** — score trends per evaluator over time.
- **Visual workflow editor** — drag-and-drop workflow builder in the dashboard.

---

## v1.0 — Stable SDK

Focus: stable contracts developers can depend on.

- **Stable public SDK contracts** — no breaking changes after v1.0.
- **Enterprise deployment guide** — Kubernetes/Helm, multi-tenant, secrets management.
- **Policy-as-code** — YAML-based tool governance policies instead of code.
- **RBAC and workspace isolation** — team-level access control.
- **Full OTLP exporter** — push spans to any OTEL collector (Jaeger, Grafana Tempo, Honeycomb, Datadog).

---

## Backlog / Ideas

These are tracked but not yet scheduled:

- Agent marketplace — reusable agents, tools, workflow templates, and plugins.
- Cloud-hosted option for teams who prefer not to self-host.
- LangChain / LlamaIndex / AutoGen adapter layers.
- Streaming trace updates via WebSocket for long-running workflows.
- Prompt playground with A/B testing.
- More language SDKs (Go, Java).

---

## Contributing to the Roadmap

If you're hitting a limitation not listed here, open a [feature request](https://github.com/raghuece455/AgentMesh/issues/new?template=feature_request.md) or start a [discussion](https://github.com/raghuece455/AgentMesh/discussions). Roadmap items with strong community demand get prioritized.
