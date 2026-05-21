# Agents

An agent is the basic building block of an AgentMesh workflow. It combines a role, instructions, a model provider, optional tools, and a permission set.

---

## Creating an Agent

```python
from agentmesh import Agent, OpenAICompatibleProvider, ToolRegistry, PermissionLevel
import os

agent = Agent(
    name="analyst",                          # unique identifier within the workflow
    role="Data Analyst",                     # shown in traces and dashboard
    instructions="Analyse data and report findings concisely.",
    model_provider=OpenAICompatibleProvider(
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ["OPENAI_API_KEY"],
        model="gpt-4o-mini",
    ),
    tools=ToolRegistry([my_tool]),           # optional
    permissions={PermissionLevel.READ},      # what tool permissions it has
    temperature=0.2,
    max_tokens=1024,
)
```

---

## Using Mock for Tests and CI

`MockModelProvider` returns preset responses without calling any API. Use it for all tests and CI pipelines — no API keys needed.

```python
from agentmesh import Agent, MockModelProvider

agent = Agent(
    name="tester",
    role="Test agent",
    instructions="Return deterministic output.",
    model_provider=MockModelProvider([
        "First response",
        "Second response",
        # When list runs out → returns "Mock response to: <prompt>" automatically
    ]),
)
```

---

## Permission Levels

Permission levels control which tools an agent can call. An agent must hold the required level in its `permissions` set, and the tool must declare the same level.

| Level | Use for |
|---|---|
| `READ` | Read-only operations: file reads, DB queries |
| `WRITE` | Write operations: file writes, DB inserts |
| `EXECUTE` | Subprocess or shell commands |
| `SENSITIVE` | Side-effectful actions: emails, API calls, deletions |

```python
agent = Agent(..., permissions={PermissionLevel.READ, PermissionLevel.WRITE})
```

---

## What Gets Recorded per Agent Run

Every agent execution emits trace events automatically — no instrumentation required:

| Event | What it captures |
|---|---|
| `agent.started` | Role, message, parent span |
| `model.call` | Provider, model, full prompt text, temperature |
| `model.response` | Output text, token counts (prompt/completion/cached), cost, latency |
| `model.failed` | Error type, latency, whether it will retry |
| `tool.started` | Tool name, input arguments, permission level |
| `tool.finished` | Result, duration, side-effect flag |
| `agent.finished` | Full result including all tool outputs |

These events appear in the span tree, waterfall timeline, and agent detail page in the dashboard.

---

## Multiple Agents in a Workflow

Agents are registered once and referenced by name in each step.

```python
from agentmesh import Agent, MockModelProvider, Workflow

provider = MockModelProvider(["Research done.", "Article written.", "Approved."])

workflow = Workflow("team")
workflow.add_agent(Agent("researcher", "Researcher", "Find key facts.", provider))
workflow.add_agent(Agent("writer",     "Writer",     "Write clearly.",  provider))
workflow.add_agent(Agent("reviewer",   "Reviewer",   "Check accuracy.", provider))

workflow.add_step("researcher", "Research AI observability", step_id="r")
workflow.add_step("writer",     "Write a summary",           step_id="w", depends_on=("r",))
workflow.add_step("reviewer",   "Review the summary",        step_id="rv", depends_on=("w",))

result = await workflow.run()
```

---

## Dashboard: Agent Page

The Agents page shows per-agent metrics derived from trace events:

- Current status and active task
- Token usage and cost trend over time
- Tool call count and error rate
- Memory operation history
- Recent traces the agent appeared in
