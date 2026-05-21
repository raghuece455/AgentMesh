# Governance

Governance in AgentMesh is the set of controls that let you understand, audit, and limit what agents are allowed to do — especially in production environments.

---

## What's Implemented

### Tool Permission Levels

Every tool declares the minimum permission level required to call it. Agents only receive the permissions you explicitly grant them — any attempt to call a tool above their permission level is blocked and recorded.

```python
from agentmesh import Agent, PermissionLevel, tool

@tool("delete_records", "Delete DB records.", {"table": "string"},
      permission=PermissionLevel.SENSITIVE)
def delete_records(arguments, context): ...

# Restricted agent — can only call READ-level tools
read_only_agent = Agent(
    "reader", "Data Reader", "Read and summarise data.",
    provider,
    permissions={PermissionLevel.READ},
)

# Privileged agent — can call READ and SENSITIVE tools
admin_agent = Agent(
    "admin", "Admin Agent", "Manage data.",
    provider,
    permissions={PermissionLevel.READ, PermissionLevel.SENSITIVE},
)
```

---

### Human Approval Queue

Sensitive tools can require approval before executing. See [approvals.md](approvals.md) for the full workflow.

```python
@tool("send_email", "Email a customer.", {"to": "string", "body": "string"},
      permission=PermissionLevel.SENSITIVE,
      requires_approval=True)
def send_email(arguments, context): ...
```

The dashboard **Approvals** page shows the pending queue. Approve or reject via the dashboard or the API:

```bash
curl -X POST http://127.0.0.1:8787/api/approvals/<id>/resolve \
  -d '{"decision": "approved", "reason": "Confirmed safe"}'
```

---

### Audit Events

Every significant action writes a permanent audit event to the trace. These events are immutable — they cannot be edited or deleted.

| Action | Audit event |
|---|---|
| Tool called | `tool.started` with arguments and permission level |
| Tool approved | `approval.resolved` with decision, resolver, and reason |
| Tool rejected | `approval.resolved` with decision and reason |
| Permission violation | `tool.blocked` with agent and missing permission |
| Memory written | `memory.write` with key, value, and agent |
| Trace exported | `trace.exported` with format |
| Budget exceeded | `budget.exceeded` with limit and current spend |

Query audit events via the CLI or API:

```bash
agentmesh traces show <trace_id>          # includes all audit events
agentmesh traces export <trace_id>        # full event log as JSON
```

---

### Secret Redaction

API keys and tokens are redacted before any data is persisted or exported. The trace stores `[REDACTED]` instead of the actual secret value. See [security.md](security.md) for details.

---

## Planned Features

| Feature | Target |
|---|---|
| User authentication | v0.4 |
| RBAC — roles and team permissions | v0.5 |
| Workspace isolation (separate DBs per team) | v0.5 |
| Data retention policies | v0.5 |
| Workspace export/import | v1.0 |
