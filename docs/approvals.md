# Human Approvals

AgentMesh lets you pause workflow execution before a sensitive tool runs and require a human to approve or reject it. This is useful for actions that send emails, delete data, charge payments, or call external APIs.

---

## How It Works

1. An agent decides to call a tool marked `requires_approval=True`.
2. AgentMesh creates an **approval record** and pauses that step.
3. The approval appears in the dashboard queue and is accessible via the API.
4. A human clicks **Approve** or **Reject** (or your code calls the API).
5. If approved, the tool runs and the workflow continues.
6. If rejected, the step fails with a `ApprovalRejected` error and the trace records the reason.

Every decision is persisted and audited — you can see who approved what and when.

---

## Marking a Tool as Requiring Approval

```python
from agentmesh import tool, PermissionLevel

@tool(
    name="delete_records",
    description="Permanently delete database records matching a filter.",
    args_schema={"table": "string", "filter": "string"},
    permission=PermissionLevel.SENSITIVE,
    requires_approval=True,          # <-- pauses before running
)
def delete_records(arguments: dict, context) -> dict:
    db.execute(f"DELETE FROM {arguments['table']} WHERE {arguments['filter']}")
    return {"deleted": True}
```

---

## Full Example with Approval Callback

```python
import asyncio
from agentmesh import (
    Agent, MockModelProvider, Workflow, WorkflowMode,
    ToolRegistry, PermissionLevel, tool, SQLiteStore,
)

@tool(
    name="send_alert",
    description="Send a critical alert to the on-call team.",
    args_schema={"message": "string"},
    permission=PermissionLevel.SENSITIVE,
    requires_approval=True,
)
def send_alert(arguments: dict, context) -> dict:
    print(f"[ALERT SENT] {arguments['message']}")
    return {"sent": True}

async def main():
    store    = SQLiteStore()
    provider = MockModelProvider(["Sending alert now."])

    workflow = Workflow("incident-response", store=store)
    workflow.add_agent(Agent(
        "responder", "Incident Responder",
        "Respond to incidents.",
        provider,
        tools=ToolRegistry([send_alert]),
        permissions={PermissionLevel.SENSITIVE},
    ))
    workflow.add_step("responder", "Handle the memory spike alert")

    result = await workflow.run({"alert": "Memory usage at 95%"})
    print(result.status)

asyncio.run(main())
```

When this runs, the workflow pauses before `send_alert` executes. Open the dashboard at `http://127.0.0.1:8787` and click the **Approvals** queue to approve or reject the call.

---

## Approving via the API

You can approve or reject programmatically without the dashboard:

```bash
# List pending approvals
curl http://127.0.0.1:8787/api/approvals

# Approve
curl -X POST http://127.0.0.1:8787/api/approvals/<approval_id>/resolve \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "reason": "Verified alert is genuine"}'

# Reject
curl -X POST http://127.0.0.1:8787/api/approvals/<approval_id>/resolve \
  -H "Content-Type: application/json" \
  -d '{"decision": "rejected", "reason": "False alarm"}'
```

---

## What Gets Recorded in an Approval Record

| Field | Description |
|---|---|
| `approval_id` | Unique ID for this approval request |
| `trace_id` | The workflow run that requested approval |
| `agent_name` | The agent that called the tool |
| `tool_name` | The tool waiting for approval |
| `arguments` | The exact input the tool will receive if approved |
| `status` | `pending`, `approved`, or `rejected` |
| `resolution_reason` | Free-text reason entered at resolution time |
| `created_at` | When the approval request was created |
| `resolved_at` | When it was approved or rejected |

---

## Dashboard: Approval Queue

The **Approvals** page in the dashboard shows:

- All pending approval requests, sorted by creation time
- Expand any request to see the full arguments the tool will receive
- Approve or reject with an optional reason
- History of all past decisions (who, when, reason)

---

## Running the Example

```bash
python examples/human_approval_workflow.py
```

Open `http://127.0.0.1:8787` and navigate to **Approvals** to process the pending request.
