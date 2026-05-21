# Core Concepts

A quick reference to every term you'll encounter in AgentMesh.

---

## Agent

An AI worker with a fixed role, a set of instructions, and a model provider powering its responses. Agents receive structured messages and return structured results. They do not hold state themselves — state lives in WorkflowMemory or the long-term memory store.

```python
from agentmesh import Agent, MockModelProvider

agent = Agent(
    name="researcher",
    role="Research Analyst",
    instructions="Find key facts and cite sources clearly.",
    model_provider=MockModelProvider(["Research complete."]),
)
```

---

## Task

The unit of work sent to an agent. A task carries a description, optional tool calls to execute, retry policy, timeout, and metadata.

```python
from agentmesh import Task, ToolCallRequest

task = Task(
    "Summarise the article",
    tool_calls=[ToolCallRequest("fetch_url", {"url": "https://example.com"})],
    max_retries=2,
)
```

---

## Workflow

The orchestrator. A workflow holds agents, steps, and a mode that controls execution order. Every `workflow.run()` call generates a unique `trace_id` and records all activity automatically.

```python
from agentmesh import Workflow, WorkflowMode

workflow = Workflow("my-pipeline", mode=WorkflowMode.SEQUENTIAL)
workflow.add_agent(agent)
workflow.add_step("researcher", "Find 3 recent AI papers")
result = await workflow.run({"topic": "LLM scaling"})
print(result.trace_id)
```

**Workflow modes:**

| Mode | Behaviour |
|---|---|
| `SEQUENTIAL` | Steps run one after another in order |
| `PARALLEL` | All steps run at the same time |
| `HIERARCHICAL` | Steps run in dependency order (DAG) |
| `EVENT_DRIVEN` | Steps are triggered by named events |

---

## Tool

A typed Python function that an agent can call during a task. Every tool call is recorded with input arguments, output, duration, permission level, and approval status.

```python
from agentmesh import tool, PermissionLevel

@tool("read_file", "Read a local text file", {"path": "string"})
def read_file(arguments, context):
    return {"content": open(arguments["path"]).read()[:500]}
```

Permission levels: `READ`, `WRITE`, `EXECUTE`, `SENSITIVE`.

---

## Memory

**Short-term (WorkflowMemory):** A key-value store shared between all agents within a single run. Cleared after the run.

**Long-term (SQLiteMemoryStore):** Versioned key-value records persisted across runs, with full audit history.

```python
# Short-term — available on the run context
context.workflow_memory.set("summary", "AI adoption is accelerating")

# Long-term — persisted to SQLite
from agentmesh import SQLiteStore, SQLiteMemoryStore
store = SQLiteStore()
mem = SQLiteMemoryStore(store)
mem.put("agent1", "profile", "last_topic", {"topic": "AI"})
```

---

## Trace

The complete, immutable recording of one workflow run. A trace contains:
- Every agent start/finish
- Every model prompt and response (with tokens and cost)
- Every tool call (input, output, duration)
- Every memory read/write
- Every RAG retrieval (query, chunks, scores)
- Every retry and error
- Checkpoints at each step

Access via the dashboard or CLI:
```bash
agentmesh traces list
agentmesh traces show <trace_id>
agentmesh traces export <trace_id> --out trace.json
```

---

## Span

A timed unit of work within a trace. Spans nest: the workflow span contains task spans, which contain agent spans, which contain model-call spans. This hierarchy is shown as the span tree in the Trace Explorer.

---

## Checkpoint

A snapshot of the full workflow state (memory, completed steps, outputs) saved after each step. Checkpoints power time-travel debugging and replay from any point.

```bash
agentmesh checkpoints list <trace_id>
agentmesh checkpoints patch-memory <checkpoint_id> --set '{"topic": "new value"}'
```

---

## Replay

Re-executing a past trace without making real API calls. The recorded prompts, model outputs, and tool results are used instead.

| Mode | Uses real API? | Use case |
|---|---|---|
| `deterministic` | No | Safe debugging, CI validation |
| `simulated` | No | Shape testing with mock outputs |
| `live` | Yes | Verify behaviour with current model |

---

## Budget

A per-run spending limit. When exceeded, `BudgetExceeded` is raised and the workflow stops immediately.

```python
from agentmesh import BudgetLimiter, Workflow

workflow = Workflow("safe-run", budget=BudgetLimiter(max_cost_usd=1.00))
```

---

## Provider

The component that calls an LLM. AgentMesh includes providers for OpenAI-compatible APIs, Anthropic, Gemini, Ollama, vLLM, and a deterministic Mock. Providers implement a single interface so they are interchangeable.

---

## RAG (Retrieval-Augmented Generation)

A technique where an agent searches a document library before answering. AgentMesh records every retrieval — which query, which chunks, which similarity scores — so you can see exactly what information influenced the answer.
