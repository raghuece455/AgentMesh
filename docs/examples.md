# Examples

AgentMesh ships with 23 runnable examples covering every major feature. Examples use `MockModelProvider`, a local provider, or the SDK offline by default — no API key required unless noted.

---

## Running Examples

```bash
# Run any example directly
python examples/hello_agent.py

# Or via the CLI
agentmesh run examples/hello_agent.py
```

Start the dashboard first to see traces appear in real time:

```bash
agentmesh demo seed --reset
agentmesh dashboard
```

---

## Example Index

### Observe any agent

| File | What it demonstrates |
|---|---|
| `sdk_quickstart.py` | Trace plain Python with `@agentmesh.observe`, `trace()`, sessions, and scores. Offline, no API keys. |
| `otel_genai_export.py` | A standard OpenTelemetry app sending GenAI spans to `POST /v1/traces` (needs a running dashboard) |
| `llm_client_auto_instrumentation.py` | `instrument_openai()` / `instrument_anthropic()` with real API calls, including streaming |
| `agent_swarm.py` | A planner fans work out to 12 researchers in workers that share only a JSON context; they message a writer, who hands off to a reviewer. Shows one swarm across 13 traces. Offline, no API keys. |
| `guardrails.py` | Block a production delete, break a tool loop, wait for approval, and halt a service with a policy. Offline, no API keys. |
| `policies/production-safety.yaml` | A starter policy: loop and spend limits, approvals for refunds, approved models only |
| `datasets_experiments.py` | Save a trace as a test case, run two agent versions as experiments with `ExactMatch`, `Contains`, and `LLMJudge`, then compare. Offline, no API keys. |
| `../sdks/typescript/examples/quickstart.mjs` | TypeScript: trace a Node.js agent with a session and scores (needs a running dashboard) |
| `../sdks/typescript/examples/experiment.mjs` | TypeScript: run an experiment over a dataset stored in AgentMesh |

### Basics

| File | What it demonstrates |
|---|---|
| `hello_agent.py` | The simplest possible workflow — one agent, one step, mock provider |
| `simple_two_agent.py` | A planner and writer working in sequence |
| `researcher_writer_reviewer.py` | Classic 3-agent sequential pipeline with step dependencies |

### Parallel and Hierarchical

| File | What it demonstrates |
|---|---|
| `parallel_multi_agent.py` | Three agents running concurrently (`WorkflowMode.PARALLEL`) — sentiment, entity, and topic analysis at the same time |

### Tools

| File | What it demonstrates |
|---|---|
| `tool_calling_agent.py` | Agent with typed `@tool` functions, permission levels, and tool call recording |
| `tool_using_agent.py` | `ToolCallRequest` — passing explicit tool calls in a `Task` |

### Memory and RAG

| File | What it demonstrates |
|---|---|
| `rag_document_qa.py` | Full RAG pipeline — ingest documents, retrieve chunks, agent answers with citations |
| `rag_qa.py` | Shorter RAG example focused on retrieval tracing |

### Human Approvals

| File | What it demonstrates |
|---|---|
| `human_approval_workflow.py` | Sensitive tool requiring approval before execution; workflow pauses until approved |
| `human_approval.py` | Minimal approval gate example |

### Cost and Budgets

| File | What it demonstrates |
|---|---|
| `cost_budget_workflow.py` | `BudgetLimiter` with `max_cost_usd` and `max_total_tokens`; shows `BudgetExceeded` handling |

### Debugging and Replay

| File | What it demonstrates |
|---|---|
| `failed_run_debugging.py` | Deliberate workflow failure, `agentmesh diagnose` output, failure inbox in the dashboard |
| `time_travel_debugging.py` | Checkpoints, `patch-memory`, and re-run from a mid-workflow state |
| `replay_from_checkpoint.py` | Deterministic replay from a selected checkpoint |

### Model Providers

| File | What it demonstrates |
|---|---|
| `openai_compatible_provider.py` | `OpenAICompatibleProvider` wiring with `OPENAI_API_KEY` *(requires API key)* |
| `ollama_local_model.py` | `OllamaProvider` with a local Llama model *(requires Ollama running)* |
| `multi_model_routing.py` | `ModelRouter` routing tasks to different providers based on task tags |

### Dashboard and CI

| File | What it demonstrates |
|---|---|
| `dashboard_demo.py` | Generates a rich trace with agents, tools, RAG, memory, and approvals — designed to populate the dashboard |
| `mock_model_test_workflow.py` | Deterministic CI workflow using `MockModelProvider` — safe for automated testing |
| `research_team.py` | Full research team workflow with researcher, writer, and reviewer agents |

---

## Example Output

Running `hello_agent.py`:

```
trace_id : trc_a1b2c3d4e5f6
status   : succeeded
output   : Draft plan
```

Open the dashboard and search for the `trace_id` to see the full span tree, token usage, and cost for that run.
