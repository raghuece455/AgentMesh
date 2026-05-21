# Roadmap

AgentMesh is built around one core thesis: production agent systems need orchestration and observability as one runtime, not bolted on separately.

This roadmap reflects the current plan. Community feedback shapes priorities — open a [GitHub Discussion](https://github.com/raghuece455/AgentMesh/discussions) to influence what we build next.

---

## Released: v0.3.0-alpha (current)

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

## v0.4 — Integration & Extensibility

Focus: make AgentMesh easier to drop into existing stacks.

- **MCP client transports** — stdio and streamable HTTP client for Model Context Protocol servers.
- **Plugin discovery** — Python entry points (`agentmesh.plugins`) for community-installable providers, tools, and evaluators.
- **Prompt regression snapshots** — diff prompt versions across runs; alert on regression.
- **Dashboard run diff** — side-by-side trace comparison UI.
- **More provider adapters** — AWS Bedrock, Groq, Mistral, Cohere.

---

## v0.5 — Scale & Reliability

Focus: make AgentMesh viable for teams and higher-throughput workflows.

- **Distributed workers** — Redis or NATS coordination for multi-process agent execution.
- **PostgreSQL background job queue** — persistent task scheduling backed by PostgreSQL.
- **Evaluator result dashboards** — built-in UI for eval suites and metric trends.
- **Visual workflow editor** — drag-and-drop workflow builder in the dashboard.
- **Cost alerting** — notifications when spend exceeds budget thresholds.

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
- Multi-language SDK (TypeScript first).

---

## Contributing to the Roadmap

If you're hitting a limitation not listed here, open a [feature request](https://github.com/raghuece455/AgentMesh/issues/new?template=feature_request.md) or start a [discussion](https://github.com/raghuece455/AgentMesh/discussions). Roadmap items with strong community demand get prioritized.
