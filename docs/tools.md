# Tools

A tool is a typed Python function that an agent can call during a task. Every call is recorded with its inputs, output, duration, permission level, and approval status — so you can see exactly what each agent did and why.

---

## Defining a Tool

Use the `@tool` decorator to register a function as a tool. You provide a name, description, and JSON-schema for the arguments.

```python
from agentmesh import tool, PermissionLevel

@tool(
    name="read_file",
    description="Read a local text file and return its contents.",
    args_schema={"path": "string"},
    permission=PermissionLevel.READ,
)
def read_file(arguments: dict, context) -> dict:
    path = arguments["path"]
    with open(path) as f:
        return {"content": f.read()[:2000]}
```

The `context` parameter gives the tool access to the current run's workflow memory and trace recorder.

---

## Permission Levels

Every tool declares one permission level. An agent must hold that level in its `permissions` set to be allowed to call the tool.

| Level | Use for |
|---|---|
| `READ` | Read-only operations — file reads, database queries, API GETs |
| `WRITE` | Write operations — file writes, database inserts, API POSTs |
| `EXECUTE` | Subprocess or shell commands |
| `SENSITIVE` | Side-effectful actions — emails, webhooks, deletions, payments |

```python
from agentmesh import Agent, PermissionLevel

agent = Agent(
    name="analyst",
    role="Data Analyst",
    instructions="Analyse the uploaded CSV file.",
    model_provider=provider,
    tools=ToolRegistry([read_file, write_csv]),
    permissions={PermissionLevel.READ, PermissionLevel.WRITE},
)
```

If an agent tries to call a tool whose permission level it doesn't hold, the call is blocked and the violation is recorded in the trace.

---

## Registering Tools

```python
from agentmesh import ToolRegistry

registry = ToolRegistry([read_file, write_csv, send_email])

agent = Agent(..., tools=registry)
```

---

## Tool Context

The `context` argument gives each tool read/write access to the shared workflow memory for the current run.

```python
@tool("store_summary", "Save a summary to memory.", {"text": "string"})
def store_summary(arguments: dict, context) -> dict:
    context.workflow_memory.set("summary", arguments["text"])
    return {"stored": True}
```

---

## Requiring Human Approval

Mark sensitive tools with `requires_approval=True`. When an agent calls this tool, execution pauses and an approval record is created. The workflow resumes only after a human approves via the dashboard or the API.

```python
@tool(
    name="send_email",
    description="Send an email to a customer.",
    args_schema={"to": "string", "body": "string"},
    permission=PermissionLevel.SENSITIVE,
    requires_approval=True,
)
def send_email(arguments: dict, context) -> dict:
    # Only runs after a human clicks Approve
    send(arguments["to"], arguments["body"])
    return {"sent": True}
```

See [approvals.md](approvals.md) for the full approval flow.

---

## What Gets Recorded per Tool Call

Every tool call emits two trace events automatically:

| Event | What it captures |
|---|---|
| `tool.started` | Tool name, input arguments, permission level, `requires_approval` flag |
| `tool.finished` | Result value, duration, side-effect flag, stdout/stderr, sandbox logs |

If the tool raises an exception, a `tool.failed` event is recorded instead of `tool.finished`.

These events appear in the Tools page of the dashboard and in the span tree of the Trace Explorer.

---

## Inspecting Tool Calls in the Dashboard

Open **Tools** in the dashboard to see:

- Every tool call across all runs
- Input arguments and output result
- Duration and permission level
- Approval status (pending / approved / rejected)
- Side-effect flag and sandbox logs
- Which agent and trace each call belongs to

---

## Tool Call in a Workflow Step

```python
from agentmesh import Task, ToolCallRequest

task = Task(
    "Fetch and summarise the homepage",
    tool_calls=[
        ToolCallRequest("fetch_url", {"url": "https://example.com"}),
    ],
)
workflow.add_step("agent-name", task)
```

`ToolCallRequest` passes tool call instructions directly in the task rather than leaving it to the model to decide.
