# AgentMesh

[![CI](https://github.com/raghuece455/AgentMesh/actions/workflows/ci.yml/badge.svg)](https://github.com/raghuece455/AgentMesh/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.3.0--alpha-orange.svg)](CHANGELOG.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**AgentMesh is an open-source observability, traceability, replay, and cost intelligence platform for production multi-agent AI systems.**

Agent workflows are hard to debug once prompts, tools, memory, retrieval, retries, and human approvals start influencing each other. AgentMesh treats every run as an inspectable, replayable trace — so you can answer *what happened*, *which step caused it*, *how much it cost*, and *where latency was spent*.

> **Works with any LLM.** OpenAI, Anthropic, Gemini, Ollama, vLLM, Azure OpenAI — or bring your own provider.

![Overview / Trace Launchpad](https://raw.githubusercontent.com/raghuece455/AgentMesh/main/dashboard/screenshots/overview-trace-launchpad.png)

---

## Why AgentMesh?

Most observability tools stop at logging LLM calls. AgentMesh goes further:

- **Trace-first execution** — every workflow, agent action, model call, tool call, retry, error, memory write, and RAG retrieval is attached to a trace ID.
- **Devtools-style replay** — prompts, outputs, tool calls, memory state, and agent interactions are replayable from SQLite or PostgreSQL.
- **Time-travel checkpoints** — inspect or fork workflow memory state at any point in a run.
- **Cost governance** — token budgets, cost budgets, rate controls, circuit breakers, and cost analytics are native.
- **Human approval hooks** — sensitive tools pause for approval before executing; decisions are persisted and audited.
- **Local-first** — no cloud account, no data leaving your machine. `pip install -e .`, run examples, inspect traces.
- **Typed extension points** — model providers, tools, memory stores, vector stores, and evaluators are plain Python interfaces.

---

## AgentMesh vs Alternatives

| Feature | AgentMesh | LangSmith | LangFuse | Phoenix/Arize |
|---|---|---|---|---|
| **Orchestration + Observability** | ✅ both in one | ❌ observability only | ❌ observability only | ❌ observability only |
| **Framework-agnostic** | ✅ | ❌ LangChain-first | ✅ | ✅ |
| **Local-first (no cloud)** | ✅ | ❌ cloud-required | ⚠️ self-host option | ⚠️ self-host option |
| **Deterministic replay** | ✅ | ❌ | ❌ | ❌ |
| **Time-travel debugging** | ✅ | ❌ | ❌ | ❌ |
| **Human approval gates** | ✅ | ❌ | ❌ | ❌ |
| **Cost budgets + circuit breaker** | ✅ | ❌ | ❌ | ❌ |
| **Multi-provider routing** | ✅ | ❌ | ❌ | ❌ |
| **Open source** | ✅ MIT | ❌ proprietary | ✅ MIT | ✅ Apache 2 |
| **Zero-config SQLite default** | ✅ | ❌ | ❌ | ❌ |

---

## Quickstart (under 2 minutes)

### Windows PowerShell

```powershell
git clone https://github.com/raghuece455/AgentMesh.git
cd AgentMesh
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m agentmesh.cli demo seed --reset
python -m agentmesh.cli dashboard --host 127.0.0.1 --port 8790
```

### macOS/Linux

```bash
git clone https://github.com/raghuece455/AgentMesh.git
cd AgentMesh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m agentmesh.cli demo seed --reset
python -m agentmesh.cli dashboard --host 127.0.0.1 --port 8790
```

Open [http://127.0.0.1:8790](http://127.0.0.1:8790) — you'll see the full dashboard with seeded demo traces.

In a second terminal, run real examples against the live dashboard:

```bash
python examples/hello_agent.py
python examples/researcher_writer_reviewer.py
python examples/tool_calling_agent.py
python examples/rag_document_qa.py
python examples/failed_run_debugging.py
```

See [Setup.md](Setup.md) for the full setup guide including provider configuration, Docker, and PostgreSQL.

---

## Docker (one command)

```bash
docker compose up --build
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Demo data is seeded automatically.

---

## Minimal Example

```python
import asyncio

from agentmesh import Agent, MockModelProvider, Workflow, WorkflowMode


async def main() -> None:
    provider = MockModelProvider(["Draft plan", "Final answer"])
    workflow = Workflow("hello-team", mode=WorkflowMode.SEQUENTIAL)
    workflow.add_agent(Agent("planner", "Planner", "Create a short plan.", provider))
    workflow.add_agent(Agent("writer", "Writer", "Write the final answer.", provider))
    workflow.add_step("planner", "Plan a launch checklist")
    workflow.add_step("writer", "Turn the plan into a concise response")

    result = await workflow.run({"goal": "ship a demo"})
    print(result.trace_id)
    print(result.output)


asyncio.run(main())
```

Replace `MockModelProvider` with `OpenAICompatibleProvider`, `AnthropicProvider`, `OllamaProvider`, or any other provider — traces look identical regardless of which model you use.

---

## Dashboard

The local dashboard is built around production debugging workflows:

| Page | What you get |
|---|---|
| **Overview** | Runs, success/failure rate, latency, tokens, cost, provider health, budget usage, recent failures |
| **Trace Explorer** | Searchable traces, nested span tree, waterfall timeline, event table, span detail, raw JSON, export, replay |
| **Workflows** | Node graph with agent/task/model/tool/memory/approval nodes, status, retries, cost, latency |
| **Agents** | Role, model/provider, cost/token trends, tool calls, memory operations, errors |
| **Models** | Provider health, calls, token split, cost, latency, p95, error rate, rate limits |
| **Costs** | Spend today/week/month, budget used/remaining, failed-run waste, cache savings |
| **Tools** | Tool call inspector with permissions, approval status, side effects, sandbox logs |
| **Memory & RAG** | Memory operations, versioned records, retrieved chunks, similarity scores, source metadata |
| **Replay Studio** | Deterministic, simulated, or live replay from any checkpoint |

![Trace Detail Cockpit](https://raw.githubusercontent.com/raghuece455/AgentMesh/main/dashboard/screenshots/trace-detail-cockpit.png)
![Workflow Graph](https://raw.githubusercontent.com/raghuece455/AgentMesh/main/dashboard/screenshots/workflow-graph.png)
![Cost Center](https://raw.githubusercontent.com/raghuece455/AgentMesh/main/dashboard/screenshots/cost-center.png)
![Replay Studio](https://raw.githubusercontent.com/raghuece455/AgentMesh/main/dashboard/screenshots/replay-studio.png)

---

## Architecture

```
AgentMesh
├── Core Runtime      Agents, Tasks, Workflows, Scheduler, Event Bus
├── Observability     Tracing, Metrics, Logs, Replay, Cost Tracking, OpenTelemetry
├── Tool Layer        MCP Proxy, Sandboxed Commands, Permissions, Human Approval
├── Memory Layer      Workflow Memory, Long-term Memory, Vector Store, Checkpoints
├── Model Providers   OpenAI-compatible, Ollama, Anthropic, Gemini, vLLM, Router
├── Dashboard         Workflow Graph, Trace Explorer, Cost Analytics, Replay Studio
└── SDK + CLI
```

Key components:

- `Workflow` — schedules steps and owns the run context.
- `WorkflowScheduler` — executes sequential, parallel, dependency-aware, hierarchical, and event-driven workflows.
- `Agent` — receives typed `AgentMessage` objects, executes tools, calls a model provider, returns an `AgentResult`.
- `TraceRecorder` — writes every event to `SQLiteStore` or `PostgreSQLStore`.
- `ReplayEngine` — reconstructs prompts, outputs, tools, agent interactions, memory state, and checkpoints.
- `TimeTravelDebugger` — inspects and forks workflow memory from checkpoints.
- `FailedRunDiagnosis` — classifies failed runs from retries, errors, and budget events.
- `ToolRegistry` — enforces permissions and optional human approval before execution.
- `PluginManager` — registers custom tools, model providers, agents, planners, and evaluators.

---

## Technology Stack

| Layer | Implementation |
|---|---|
| Core | Python 3.11+ |
| API | FastAPI |
| Dashboard frontend | React 19 + TypeScript + TailwindCSS + Recharts + React Flow |
| Workflow engine | AsyncIO |
| Messaging | In-memory event bus; optional Redis and NATS adapters |
| Database | SQLite default; optional PostgreSQL adapter |
| Vector DB | FAISS adapter; SQLite vector fallback |
| Tracing | OpenTelemetry-compatible trace model; OTEL JSON export |
| Packaging | `pyproject.toml` with uv-compatible dependency groups and extras |
| Testing | pytest |
| Containerization | Dockerfile + Docker Compose |

---

## Provider Support

| Provider | Status |
|---|---|
| Mock (deterministic tests/CI) | ✅ included |
| OpenAI-compatible (`/chat/completions`) | ✅ included |
| Azure OpenAI | ✅ via `OpenAICompatibleProvider` |
| Anthropic Messages API | ✅ included |
| Google Gemini | ✅ included |
| Ollama (local models) | ✅ included |
| vLLM (OpenAI-compatible) | ✅ included |
| Custom provider | ✅ implement `ModelProvider` |
| Model router (cheap/local/coding routes) | ✅ included |

```bash
pip install -e ".[production]"   # all production adapters
pip install -e ".[postgres]"     # PostgreSQL only
pip install -e ".[redis]"        # Redis event bus
pip install -e ".[nats]"         # NATS event bus
pip install -e ".[faiss]"        # FAISS vector store
pip install -e ".[otel]"         # OpenTelemetry export
```

---

## Examples

20 runnable examples covering all major features:

```
examples/
├── hello_agent.py                  # Single-agent workflow
├── researcher_writer_reviewer.py   # 3-agent sequential pipeline
├── parallel_multi_agent.py         # Parallel execution
├── tool_calling_agent.py           # Agent with typed tools
├── rag_document_qa.py              # RAG with tracing
├── human_approval_workflow.py      # Approval gates
├── cost_budget_workflow.py         # Budget constraints
├── failed_run_debugging.py         # Failure diagnosis
├── time_travel_debugging.py        # Replay from checkpoint
├── multi_model_routing.py          # Dynamic provider routing
├── ollama_local_model.py           # Local LLM
├── openai_compatible_provider.py   # Generic OpenAI API
└── ...
```

---

## CLI

```bash
agentmesh init
agentmesh run examples/research_team.py
agentmesh dashboard
agentmesh demo seed
agentmesh traces list
agentmesh traces show <trace_id>
agentmesh traces export <trace_id> --out trace.json
agentmesh traces export <trace_id> --format otel-json --out trace.otel.json
agentmesh replay <trace_id> --mode deterministic
agentmesh replay <trace_id> --mode simulated
agentmesh replay <trace_id> --mode live --allow-side-effects
agentmesh diagnose <trace_id>
agentmesh costs summary
agentmesh costs summary --dimension model
agentmesh checkpoints list <trace_id>
agentmesh checkpoints show <checkpoint_id>
agentmesh doctor
agentmesh validate traces
agentmesh version
```

---

## Security Model

- Secrets are read from environment variables; logs and persisted JSON redact common secret keys.
- Tools declare permission levels (`READ`, `WRITE`, `EXECUTE`, `SENSITIVE`).
- Sensitive tools can require human approval before execution.
- Tool execution and memory writes create audit records.
- Optional API key auth for the dashboard server (`AGENTMESH_AUTH_MODE=api_key`).

See [SECURITY.md](SECURITY.md) for the full security policy and reporting instructions.

---

## Project Status

`v0.3.0-alpha` — public alpha. Core runtime and dashboard are stable for local development and evaluation.

**Implemented:** SQLite and PostgreSQL observability persistence, FastAPI dashboard APIs, React trace-first dashboard, trace detail cockpit, failure inbox, provider health, workflow graph, cost center, tool inspector, memory & RAG inspector, prompt registry, replay studio, demo seeding, CLI, Docker, CI, OpenTelemetry JSON export, mock and production provider adapters.

**Partial:** OTLP collector push, live model replay overrides, RBAC/authentication, distributed workers.

**Planned:** Full OTLP exporter, team collaboration, plugin marketplace, cloud deployment, Kubernetes/Helm. See [ROADMAP.md](ROADMAP.md).

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, development workflow, and contribution areas.

Good first issues are labeled [`good first issue`](https://github.com/raghuece455/AgentMesh/issues?q=label%3A%22good+first+issue%22) in the issue tracker.

---

## Documentation

| Document | What it covers |
|---|---|
| [Setup.md](Setup.md) | Full setup guide — providers, Docker, PostgreSQL, troubleshooting |
| [HOW_IT_WORKS.md](HOW_IT_WORKS.md) | Deep dive — architecture, sequence diagrams, data flow, use cases |
| [ROADMAP.md](ROADMAP.md) | Planned milestones — v0.4, v0.5, v1.0 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute — setup, dev principles, adding providers |
| [docs/](docs/) | Reference docs — agents, tools, memory, CLI, dashboard, OTEL |

---

## Community

- [GitHub Discussions](https://github.com/raghuece455/AgentMesh/discussions) — questions, ideas, show and tell
- [GitHub Issues](https://github.com/raghuece455/AgentMesh/issues) — bug reports and feature requests
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to contribute

If AgentMesh is useful to you, a ⭐ on GitHub helps others find it.

---

## License

MIT. See [LICENSE](LICENSE).
