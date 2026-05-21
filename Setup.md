# AgentMesh Setup Guide

This guide walks a new user from a fresh clone to a running AgentMesh dashboard, real workflow traces, provider configuration, and custom agent setup.

AgentMesh is currently `v0.3.0-alpha`. It is a public alpha for local development and evaluation, not a production v1.0 control plane.

## 1. What You Get

AgentMesh helps you build and inspect multi-agent AI workflows with:

- Async Python agents and workflows.
- Trace IDs for every workflow run.
- Queryable SQLite observability data by default.
- Model call, tool call, memory, RAG, approval, cost, retry, and error records.
- A FastAPI dashboard API.
- A React trace-first dashboard.
- Deterministic replay basics.
- OpenTelemetry-compatible JSON export.
- Mock, OpenAI-compatible, Ollama, Anthropic, Gemini, and vLLM provider adapters.

## 2. Prerequisites

Required:

- Python `3.11`, `3.12`, or `3.13`.
- `pip`.

Recommended for dashboard development:

- Node.js `22` or newer.
- npm.

Optional:

- Docker Desktop for the one-command Docker demo.
- Ollama for local model examples.

Check versions:

```bash
python --version
pip --version
node --version
npm --version
docker --version
```

On Windows, use PowerShell. On macOS/Linux, use a standard shell.

## 3. Fresh Clone Setup

### Windows PowerShell

```powershell
git clone https://github.com/raghuece455/AgentMesh.git
cd AgentMesh

py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e .
```

If `py -3.13` is not available, use:

```powershell
python -m venv .venv
```

### macOS/Linux

```bash
git clone https://github.com/raghuece455/AgentMesh.git
cd agentmesh

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e .
```

### Install Contributor Extras

Use this if you want to run tests, linting, and local dashboard builds:

```bash
python -m pip install -e ".[dev]"
cd dashboard
npm ci
npm run build
cd ..
```

## 4. First Run: Seed Data And Open The Dashboard

Seed demo data:

```bash
python -m agentmesh.cli demo seed --reset
```

Start the dashboard:

```bash
python -m agentmesh.cli dashboard --host 127.0.0.1 --port 8790
```

Open:

```text
http://127.0.0.1:8790
```

You should see:

- Overview / Trace Launchpad.
- Recent Traces.
- Failure Inbox.
- Provider Health.
- Cost Center.
- Trace Detail cockpit with span tree and waterfall.

## 5. Run Real Example Workflows

Open a second terminal from the repo root while the dashboard is running.

Windows PowerShell:

```powershell
python examples\hello_agent.py
python examples\researcher_writer_reviewer.py
python examples\tool_calling_agent.py
python examples\rag_document_qa.py
python examples\failed_run_debugging.py
```

macOS/Linux:

```bash
python examples/hello_agent.py
python examples/researcher_writer_reviewer.py
python examples/tool_calling_agent.py
python examples/rag_document_qa.py
python examples/failed_run_debugging.py
```

Then refresh the dashboard and switch the environment filter to:

- `All data` to see demo plus real runs.
- `Real runs` to see examples you just executed.
- `Demo only` to inspect seeded demo traces.

## 6. Validate, Export, And Replay Traces

List recent traces:

```bash
python -m agentmesh.cli traces list
```

Validate trace integrity:

```bash
python -m agentmesh.cli validate traces
python -m agentmesh.cli validate traces --json
```

Export normal AgentMesh JSON:

```bash
python -m agentmesh.cli traces export <trace_id> --out trace.json
```

Export OpenTelemetry-compatible JSON:

```bash
python -m agentmesh.cli traces export <trace_id> --format otel-json --out trace.otel.json
```

Replay deterministically from recorded model/tool outputs:

```bash
python -m agentmesh.cli replay <trace_id> --mode deterministic
```

Simulated replay:

```bash
python -m agentmesh.cli replay <trace_id> --mode simulated
```

Live replay is intentionally guarded because it may call real providers/tools:

```bash
python -m agentmesh.cli replay <trace_id> --mode live --allow-side-effects
```

## 7. Environment Configuration

AgentMesh reads configuration from environment variables and CLI flags.

| Variable | Purpose | Default |
| --- | --- | --- |
| `AGENTMESH_DB` | SQLite database path | `.agentmesh/agentmesh.db` |
| `AGENTMESH_DB_URL` | SQLite path or PostgreSQL DSN | unset |
| `AGENTMESH_HOST` | Dashboard host | `127.0.0.1` |
| `AGENTMESH_PORT` | Dashboard port | `8787` |
| `AGENTMESH_AUTH_MODE` | `none` or `api_key` | `none` |
| `AGENTMESH_API_KEY` | Bearer token for API key mode | unset |
| `AGENTMESH_PRICING_JSON` | Custom model pricing rules | unset |
| `OPENAI_API_KEY` | OpenAI-compatible provider key | unset |
| `OPENAI_BASE_URL` | OpenAI-compatible base URL | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | OpenAI-compatible model | `gpt-4.1-mini` |
| `OLLAMA_HOST` | Ollama host | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model | unset |
| `ANTHROPIC_API_KEY` | Anthropic key for examples you create | unset |
| `GEMINI_API_KEY` | Gemini key for examples you create | unset |
| `VLLM_BASE_URL` | vLLM OpenAI-compatible base URL | `http://localhost:8000/v1` |

AgentMesh automatically loads a `.env` file if `python-dotenv` is installed:

```bash
pip install -e ".[dotenv]"
```

Then place your keys in `.env`:

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=...
AGENTMESH_AUTH_MODE=api_key
AGENTMESH_API_KEY=replace-me
```

The CLI reads `.env` on every invocation. If `python-dotenv` is not installed, environment variables must be set in the shell.

Windows PowerShell:

```powershell
$env:AGENTMESH_DB=".agentmesh\my-team.db"
$env:AGENTMESH_AUTH_MODE="api_key"
$env:AGENTMESH_API_KEY="replace-me"
```

macOS/Linux:

```bash
export AGENTMESH_DB=.agentmesh/my-team.db
export AGENTMESH_AUTH_MODE=api_key
export AGENTMESH_API_KEY=replace-me
```

When API key mode is enabled, call protected APIs with:

```bash
curl -H "Authorization: Bearer replace-me" http://127.0.0.1:8790/api/traces
```

## 8. Storage Configuration

### Default SQLite

SQLite is the default and best choice for local development:

```bash
python -m agentmesh.cli --db .agentmesh/my-local.db demo seed --reset
python -m agentmesh.cli --db .agentmesh/my-local.db dashboard
```

In code:

```python
from agentmesh import SQLiteStore

store = SQLiteStore(".agentmesh/my-local.db")
```

### PostgreSQL

PostgreSQL support exists as an adapter, but the alpha dashboard is most heavily exercised with SQLite.

Install optional dependencies:

```bash
python -m pip install -e ".[postgres]"
```

Use a DSN:

```bash
python -m agentmesh.cli --db postgresql://agentmesh@localhost:5432/agentmesh dashboard
```

## 9. Create Your First Custom Agent Workflow

Create `examples/my_first_agentmesh_workflow.py`:

```python
import asyncio
import os

from agentmesh import Agent, MockModelProvider, OpenAICompatibleProvider, SQLiteStore, Workflow


def provider():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return MockModelProvider(["Mock answer because OPENAI_API_KEY is not set."])
    return OpenAICompatibleProvider(
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    )


async def main() -> None:
    store = SQLiteStore(os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db"))

    workflow = Workflow("my-first-agentmesh-workflow", store=store)
    workflow.add_agent(
        Agent(
            name="assistant",
            role="Product assistant",
            instructions="Answer clearly and mention tradeoffs.",
            provider=provider(),
        )
    )
    workflow.add_step("assistant", "Explain how AgentMesh traces model calls")

    result = await workflow.run({"environment": "local"})
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python examples/my_first_agentmesh_workflow.py
```

Open the dashboard and search for `my-first-agentmesh-workflow`.

## 10. Configure Model Providers

### Mock Provider

Use this for tests, CI, demos, and deterministic replay.

```python
from agentmesh import MockModelProvider

provider = MockModelProvider([
    "First deterministic response",
    "Second deterministic response",
])
```

Example:

```python
workflow.add_agent(
    Agent("tester", "Test agent", "Return deterministic output.", MockModelProvider(["OK"]))
)
```

### OpenAI-Compatible Provider

Works with APIs that expose an OpenAI-compatible `/chat/completions` route.

Environment:

```bash
export OPENAI_API_KEY=replace-with-your-openai-compatible-key
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4.1-mini
```

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="replace-with-your-openai-compatible-key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

Code:

```python
import os
from agentmesh import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    api_key=os.environ["OPENAI_API_KEY"],
    model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
)
```

Run the included example:

```bash
python examples/openai_compatible_provider.py
```

### Azure OpenAI

Use `OpenAICompatibleProvider` when your Azure endpoint exposes a compatible `/chat/completions` path.

Example:

```python
import os
from agentmesh import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    base_url=os.environ["AZURE_OPENAI_BASE_URL"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
)
```

Example environment values depend on your Azure deployment route:

```bash
export AZURE_OPENAI_BASE_URL="https://<resource>.openai.azure.com/openai/deployments/<deployment>"
export AZURE_OPENAI_API_KEY="<key>"
export AZURE_OPENAI_DEPLOYMENT="<deployment>"
```

If your Azure route requires a different URL shape or query parameters, wrap it in a custom provider using the `ModelProvider` interface.

### Ollama Provider

Install and start Ollama:

```bash
ollama pull llama3.1
ollama serve
```

Configure:

```bash
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_MODEL=llama3.1
```

Windows PowerShell:

```powershell
$env:OLLAMA_HOST="http://localhost:11434"
$env:OLLAMA_MODEL="llama3.1"
```

Code:

```python
import os
from agentmesh import OllamaProvider

provider = OllamaProvider(
    model=os.environ["OLLAMA_MODEL"],
    base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
)
```

Run:

```bash
python examples/ollama_local_model.py
```

Ollama costs are marked `local/free` by default.

### Anthropic Provider

Environment:

```bash
export ANTHROPIC_API_KEY=...
export ANTHROPIC_MODEL=claude-sonnet-4-5
```

Code:

```python
import os
from agentmesh import AnthropicProvider

provider = AnthropicProvider(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
)
```

### Gemini Provider

Environment:

```bash
export GEMINI_API_KEY=...
export GEMINI_MODEL=gemini-2.5-pro
```

Code:

```python
import os
from agentmesh import GeminiProvider

provider = GeminiProvider(
    api_key=os.environ["GEMINI_API_KEY"],
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
)
```

### vLLM Provider

Start a vLLM OpenAI-compatible server separately, then configure:

```bash
export VLLM_BASE_URL=http://localhost:8000/v1
export VLLM_MODEL=meta-llama/Llama-3.1-8B-Instruct
```

Code:

```python
import os
from agentmesh import VLLMProvider

provider = VLLMProvider(
    model=os.environ["VLLM_MODEL"],
    base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
)
```

vLLM costs are marked `local/free` unless you configure pricing.

## 11. Multi-Agent Workflow Example

```python
import asyncio

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow


async def main() -> None:
    store = SQLiteStore(".agentmesh/agentmesh.db")
    provider = MockModelProvider([
        "Research summary: developers need traceability.",
        "Draft: AgentMesh explains agent workflow behavior.",
        "Review: approved with minor edits.",
    ])

    workflow = Workflow("research-write-review", store=store)
    workflow.add_agent(Agent("researcher", "Researcher", "Find important facts.", provider))
    workflow.add_agent(Agent("writer", "Writer", "Write a concise answer.", provider))
    workflow.add_agent(Agent("reviewer", "Reviewer", "Check accuracy and clarity.", provider))

    workflow.add_step("researcher", "Research agent observability", step_id="research")
    workflow.add_step("writer", "Write based on researcher output", depends_on=("research",), step_id="write")
    workflow.add_step("reviewer", "Review the writer output", depends_on=("write",), step_id="review")

    result = await workflow.run({"environment": "local"})
    print(result.trace_id)
    print(result.output)


asyncio.run(main())
```

Dependency values refer to workflow step IDs, not agent names. The included `examples/researcher_writer_reviewer.py` is the best reference.

## 12. Tool-Using Agent

Tools are typed functions registered with an agent.

```python
import asyncio
from pathlib import Path

from agentmesh import (
    Agent,
    MockModelProvider,
    PermissionLevel,
    SQLiteStore,
    Task,
    ToolCallRequest,
    ToolRegistry,
    Workflow,
    tool,
)


@tool("read_small_file", "Read a local text file", {"path": "string"})
def read_small_file(arguments, context):
    path = Path(str(arguments["path"]))
    text = path.read_text(encoding="utf-8")
    return {"path": str(path), "preview": text[:120]}


async def main() -> None:
    store = SQLiteStore(".agentmesh/agentmesh.db")
    provider = MockModelProvider(["The file was read and summarized."])

    agent = Agent(
        "tool_agent",
        "Tool agent",
        "Use tools when they help.",
        provider,
        ToolRegistry([read_small_file]),
        {PermissionLevel.READ},
    )

    workflow = Workflow("tool-demo", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "tool_agent",
        Task("Read local file", tool_calls=[ToolCallRequest("read_small_file", {"path": "README.md"})]),
    )

    result = await workflow.run({"environment": "local"})
    print(result.trace_id)


asyncio.run(main())
```

Tool inputs, outputs, status, duration, permissions, and errors appear in the dashboard Tool Inspector.

## 13. Human Approval For Sensitive Tools

Use approval gates for actions such as sending emails, deleting data, writing files, or calling production APIs.

```python
import asyncio

from agentmesh import (
    Agent,
    MockModelProvider,
    PermissionLevel,
    SQLiteStore,
    Task,
    ToolCallRequest,
    ToolRegistry,
    Workflow,
    tool,
)


@tool(
    "send_notice",
    "Simulate sending a release notice",
    {"recipient": "string", "message": "string"},
    permission=PermissionLevel.SENSITIVE,
    requires_approval=True,
)
def send_notice(arguments, context):
    return {"sent": True, "recipient": arguments["recipient"]}


async def approve_tool(definition, arguments, context) -> bool:
    print(f"Approve {definition.name}? args={arguments}")
    return True


async def main() -> None:
    store = SQLiteStore(".agentmesh/agentmesh.db")
    agent = Agent(
        "operator",
        "Release operator",
        "Ask for approval before sensitive tools.",
        MockModelProvider(["Notice sent after approval."]),
        ToolRegistry([send_notice]),
        {PermissionLevel.READ, PermissionLevel.SENSITIVE},
    )

    workflow = Workflow("approval-demo", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "operator",
        Task(
            "Send notice",
            tool_calls=[
                ToolCallRequest(
                    "send_notice",
                    {"recipient": "team@example.com", "message": "AgentMesh demo"},
                )
            ],
        ),
    )

    result = await workflow.run({"environment": "local"}, approval_callback=approve_tool)
    print(result.trace_id)


asyncio.run(main())
```

The approval request, decision, and tool execution are persisted and shown in the dashboard.

## 14. Memory And RAG Setup

Use SQLite memory for versioned long-term state:

```python
from agentmesh import SQLiteMemoryStore, SQLiteStore

store = SQLiteStore(".agentmesh/agentmesh.db")
memory = SQLiteMemoryStore(store)

memory.put("researcher", "profile", "last_topic", {"topic": "observability"})
value = memory.get("researcher", "profile", "last_topic")
```

Use SQLite vector retrieval for local RAG:

```python
import asyncio

from agentmesh import RetrievalEngine, SQLiteStore, SQLiteVectorStore


async def main() -> None:
    store = SQLiteStore(".agentmesh/agentmesh.db")
    retrieval = RetrievalEngine(SQLiteVectorStore(store), top_k=2)

    await retrieval.ingest({
        "docs/agentmesh.md": "AgentMesh traces model calls, tool calls, memory, and RAG retrievals."
    })

    results = await retrieval.retrieve("How does AgentMesh trace RAG?")
    for result in results:
        print(result.to_json())


asyncio.run(main())
```

For a full runnable workflow, use:

```bash
python examples/rag_document_qa.py
```

RAG retrievals appear in the dashboard Memory & RAG page and Trace Detail inspector.

## 15. Cost Tracking And Pricing

AgentMesh records token usage and cost confidence.

Cost statuses:

- `exact`: trusted provider-reported or explicitly supplied cost.
- `estimated`: calculated from local pricing config.
- `local/free`: local providers such as Mock, Ollama, or vLLM by default.
- `unknown`: no pricing rule exists.
- `unavailable`: usage/cost data was not available.

Set custom pricing:

```bash
export AGENTMESH_PRICING_JSON='[
  {
    "provider": "openai-compatible",
    "model": "custom-model-*",
    "prompt_per_1k": 0.001,
    "completion_per_1k": 0.002,
    "cached_per_1k": 0.0001,
    "reasoning_per_1k": 0.001,
    "status": "estimated"
  }
]'
```

View costs:

```bash
python -m agentmesh.cli costs summary
python -m agentmesh.cli costs summary --dimension workflow
python -m agentmesh.cli costs summary --dimension agent
python -m agentmesh.cli costs summary --dimension model
python -m agentmesh.cli costs summary --dimension provider
```

## 16. Dashboard API

Start the dashboard:

```bash
python -m agentmesh.cli dashboard --host 127.0.0.1 --port 8790
```

Useful endpoints:

```text
GET /api/health
GET /api/overview
GET /api/traces
GET /api/traces/{trace_id}
GET /api/traces/{trace_id}/spans
GET /api/traces/{trace_id}/events
GET /api/traces/{trace_id}/export
GET /api/traces/{trace_id}/export?format=otel-json
GET /api/costs/summary
GET /api/tools
GET /api/tool-calls
GET /api/memory/operations
GET /api/rag/retrievals
GET /api/prompts
GET /api/replay/checkpoints
GET /api/audit-logs
```

With API key mode:

```bash
curl -H "Authorization: Bearer $AGENTMESH_API_KEY" http://127.0.0.1:8790/api/traces
```

## 17. Docker Demo

Build and run:

```bash
docker compose up --build
```

Open:

```text
http://127.0.0.1:8787
```

By default, Docker Compose seeds demo data into a named SQLite volume.

Skip reseeding:

```bash
AGENTMESH_DEMO_SEED=false docker compose up
```

Windows PowerShell:

```powershell
$env:AGENTMESH_DEMO_SEED="false"
docker compose up
```

Stop:

```bash
docker compose down
```

## 18. Testing

Python:

```bash
python -m compileall -q src
pytest
```

Frontend:

```bash
cd dashboard
npm install
npm run build
npm run test:smoke
npm run screenshots
cd ..
```

Smoke tests expect a running dashboard. If you use a custom port:

```bash
AGENTMESH_DASHBOARD_URL=http://127.0.0.1:8790 npm run test:smoke
```

Windows PowerShell:

```powershell
$env:AGENTMESH_DASHBOARD_URL="http://127.0.0.1:8790"
npm run test:smoke
```

## 19. Recommended Project Layout For Your App

You can embed AgentMesh in your own repo like this:

```text
my-ai-app/
|-- agents/
|   |-- researcher.py
|   |-- writer.py
|-- workflows/
|   |-- research_report.py
|-- tools/
|   |-- safe_file_tools.py
|-- docs/
|-- .agentmesh/
|-- run_workflow.py
```

Recommended patterns:

- Put provider setup in one module.
- Keep tools small and typed.
- Use `MockModelProvider` for CI.
- Use environment variables for secrets.
- Use approval gates for side effects.
- Use a separate database per environment.

Example provider factory:

```python
import os

from agentmesh import MockModelProvider, OllamaProvider, OpenAICompatibleProvider


def build_provider(route: str):
    if route == "mock":
        return MockModelProvider(["Mock response"])
    if route == "ollama":
        return OllamaProvider(os.environ["OLLAMA_MODEL"], os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    if route == "openai":
        return OpenAICompatibleProvider(
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            os.environ["OPENAI_API_KEY"],
            os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        )
    raise ValueError(f"Unknown provider route: {route}")
```

## 20. Troubleshooting

### Empty Dashboard

Seed demo data or run a workflow:

```bash
python -m agentmesh.cli demo seed --reset
python examples/hello_agent.py
```

### SQLite Database Locked

Stop the dashboard process using the same DB, then retry:

```bash
python -m agentmesh.cli demo seed --reset
```

Or use a separate DB:

```bash
python -m agentmesh.cli --db .agentmesh/test.db demo seed --reset
```

### Port Already In Use

Use another port:

```bash
python -m agentmesh.cli dashboard --host 127.0.0.1 --port 8791
```

### Ollama Unavailable

Make sure Ollama is running:

```bash
ollama serve
ollama list
```

If you only want to test the workflow shape, use `MockModelProvider`.

### Missing API Key

If using OpenAI-compatible, Anthropic, Gemini, or a hosted provider, set the relevant key in your shell. AgentMesh redacts common secret patterns in traces, exports, and logs, but you should still avoid putting secrets directly in prompts, tool arguments, or source files.

### Dashboard Build Fails

Install Node.js `22`, then:

```bash
cd dashboard
npm ci
npm run build
```

## 21. Public Alpha Notes

Implemented in `v0.3.0-alpha`:

- Local SQLite observability persistence.
- Trace-first dashboard.
- Demo seed data.
- Real example workflows.
- API and CLI trace export.
- OpenTelemetry-compatible JSON export.
- API-key-ready mode.
- Deterministic replay basics.
- Mocked provider tests.

Partial or planned:

- Full OTLP collector push.
- Advanced RBAC and user authentication.
- Distributed workers.
- Hosted deployment.
- Advanced live replay with provider/model overrides.
- Full enterprise governance.

For more detail, see:

- `README.md` — project overview and quickstart
- `HOW_IT_WORKS.md` — architecture diagrams and deep-dive explanations
- `docs/concepts.md` — core vocabulary
- `docs/dashboard.md` — all dashboard pages explained
- `docs/model-providers.md` — provider configuration
- `docs/opentelemetry.md` — OTEL export format
- `docs/security.md` — auth, redaction, and permissions
- `docs/troubleshooting.md` — common problems and fixes
