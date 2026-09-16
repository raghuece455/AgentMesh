# AgentMesh Documentation

| Document | What it covers |
|---|---|
| [integrations.md](integrations.md) | **Trace any framework** — OTLP endpoint, OpenAI Agents SDK, Pydantic AI, LangGraph, CrewAI, Vercel AI SDK, attribute mapping, privacy |
| [sdk.md](sdk.md) | **Python tracing SDK** — `@observe`, `trace()`, `span()`, scores, OpenAI/Anthropic auto-instrumentation |
| [typescript-sdk.md](typescript-sdk.md) | **TypeScript SDK** — `agentmesh-sdk` for Node.js: tracing, OpenAI/Anthropic instrumentation, experiments |
| [datasets-and-experiments.md](datasets-and-experiments.md) | **Evaluate changes** — datasets from traces, experiments, evaluators, LLM-as-judge, comparisons, CI gating |
| [swarms.md](swarms.md) | **Agent swarms**: many agents across traces and processes as one run, swarm graph, messages, stopping a swarm |
| [access.md](access.md) | **Egress and data access**: hosts agents reached, data they read, and allowlists that block a call before it is made |
| [guardrails.md](guardrails.md) | **Guardrails**: policies that block, pause, or limit tool calls, LLM calls, and agents; simulation; kill switch |
| [alerts.md](alerts.md) | **Alerts** — failure, cost, latency, loop, swarm, and new-destination rules with Slack, Discord, and signed webhooks |
| [mcp.md](mcp.md) | **MCP server** — let Claude Code, Cursor, or any MCP client query and diagnose traces |
| [concepts.md](concepts.md) | Core vocabulary — Agent, Workflow, Task, Trace, Tool, Memory, Replay, Budget, Provider, RAG |
| [agents.md](agents.md) | Building and configuring agents, permission levels, MockModelProvider, trace events |
| [workflows.md](workflows.md) | Sequential, parallel, hierarchical, and event-driven workflows; budget, retry, checkpoints |
| [tools.md](tools.md) | Typed tools, permission levels, tool context, human approval gates, tool trace events |
| [approvals.md](approvals.md) | Human-in-the-loop approval flow — dashboard, API, audit records |
| [memory-and-rag.md](memory-and-rag.md) | Short-term workflow memory, long-term SQLite memory, RAG ingest and retrieval |
| [cost-tracking.md](cost-tracking.md) | Token budgets, cost estimates, pricing overrides, spend analytics |
| [model-providers.md](model-providers.md) | OpenAI, Anthropic, Gemini, Ollama, vLLM, Mock, custom providers — code for each |
| [tracing.md](tracing.md) | Trace ID, all event types, queryable tables, CLI and API commands |
| [replay.md](replay.md) | Deterministic, simulated, and live replay; time-travel debugging with patch-memory |
| [dashboard.md](dashboard.md) | All dashboard pages explained — Overview, Trace Explorer, Costs, Replay Studio, etc. |
| [api_reference.md](api_reference.md) | All REST endpoints with descriptions, query parameters, and auth format |
| [configuration.md](configuration.md) | All environment variables — core, providers, cost, observability, Docker |
| [examples.md](examples.md) | All runnable examples with descriptions |
| [security.md](security.md) | Auth setup, secret redaction, permission enforcement, audit events, planned RBAC |
| [docker.md](docker.md) | Docker Compose setup, environment variables, PostgreSQL override, health checks |
| [opentelemetry.md](opentelemetry.md) | OpenTelemetry in and out — OTLP ingestion, OTLP JSON export, live runtime mirroring |
| [production_stack.md](production_stack.md) | PostgreSQL, Redis, NATS, FAISS, OTEL collector — extras and configuration |
| [governance.md](governance.md) | Permission levels, approval queue, audit events, planned RBAC |
| [evaluations.md](evaluations.md) | Scores and evaluation records from SDKs, API, dashboard feedback, OTel events, and experiments |
| [prompts.md](prompts.md) | Prompt versioning, registry, hash tracking, planned diff and testing |
| [cli.md](cli.md) | CLI reference — all commands, flags, and examples |
| [troubleshooting.md](troubleshooting.md) | Common problems and fixes |

---

**New to AgentMesh?** Start here:

1. `README.md` (project root) — what AgentMesh is and a 2-minute quickstart
2. `HOW_IT_WORKS.md` (project root) — full walkthrough with architecture diagrams
3. `Setup.md` (project root) — detailed setup for every provider and environment

Then explore:

- **Observe an existing agent** → [integrations.md](integrations.md) → [sdk.md](sdk.md) or [typescript-sdk.md](typescript-sdk.md) → [mcp.md](mcp.md)
- **Ship changes safely** → [datasets-and-experiments.md](datasets-and-experiments.md) → [alerts.md](alerts.md)
- **Control what agents do** → [guardrails.md](guardrails.md) → [access.md](access.md) → [approvals.md](approvals.md)
- **Run agent swarms** → [swarms.md](swarms.md) → [guardrails.md](guardrails.md)
- **Build something** → [concepts.md](concepts.md) → [agents.md](agents.md) → [workflows.md](workflows.md)
- **Add tools** → [tools.md](tools.md) → [approvals.md](approvals.md)
- **Connect a real model** → [model-providers.md](model-providers.md)
- **Understand traces** → [tracing.md](tracing.md) → [replay.md](replay.md)
- **Control cost** → [cost-tracking.md](cost-tracking.md)
- **Use the dashboard** → [dashboard.md](dashboard.md) → [api_reference.md](api_reference.md)
