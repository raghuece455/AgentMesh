# Security

AgentMesh is `v0.3.0-alpha` software. The security posture is **local-first and auth-ready**, designed for safe local development and team evaluation — not yet enterprise-hardened.

---

## Current Security Features

### Secret Redaction

AgentMesh automatically redacts common secret patterns before persisting trace data or exporting:

- API keys matching patterns like `sk-...`, `AIza...`, `sk-ant-...`
- Environment variable names matching `*_API_KEY`, `*_SECRET`, `*_TOKEN`, `*_PASSWORD`
- Values passed as tool arguments under sensitive key names

Redaction happens at the `TraceRecorder` layer — secrets never reach the database or OTEL export.

```python
# This is safe — the key value is redacted before it's stored
agent = Agent(
    ...,
    model_provider=OpenAICompatibleProvider(
        api_key=os.environ["OPENAI_API_KEY"],   # redacted in traces
        ...
    ),
)
```

---

### API Key Authentication

Protect the dashboard API with a bearer token:

```bash
export AGENTMESH_AUTH_MODE=api_key
export AGENTMESH_API_KEY=your-secret-key
```

All API routes then require:

```
Authorization: Bearer your-secret-key
```

The default is `AGENTMESH_AUTH_MODE=none` (open access), which is correct for local single-user development.

---

### Tool Permission Levels

Every tool declares a permission level. An agent must hold the matching permission in its `permissions` set to call the tool. Attempts to call a tool without the required permission are blocked and recorded in the trace.

```python
from agentmesh import tool, PermissionLevel, Agent

@tool("delete_user", "Delete a user account.", {"user_id": "string"},
      permission=PermissionLevel.SENSITIVE)
def delete_user(arguments, context): ...

# This agent can call sensitive tools
agent = Agent(..., permissions={PermissionLevel.READ, PermissionLevel.SENSITIVE})

# This agent cannot — the call will be blocked
restricted_agent = Agent(..., permissions={PermissionLevel.READ})
```

---

### Human Approval Gates

Sensitive tools can require explicit human approval before running. The workflow pauses, creates an approval record, and resumes only after a human approves via the dashboard or API. Every decision is persisted.

```python
@tool("send_invoice", "Email an invoice to the customer.",
      args_schema={"email": "string", "amount": "number"},
      permission=PermissionLevel.SENSITIVE,
      requires_approval=True)
def send_invoice(arguments, context): ...
```

See [approvals.md](approvals.md) for the full flow.

---

### Audit Events

The following actions create audit records in the trace:

| Action | Audit event |
|---|---|
| Tool approved or rejected | `approval.resolved` with decision, reason, and timestamp |
| Sensitive tool called | `tool.started` with `requires_approval=True` flag |
| Permission violation attempt | `tool.blocked` with agent name and missing permission |
| Memory write | `memory.write` with key, value, and agent name |
| Trace exported | `trace.exported` with format and destination |
| Replay run started | `replay.started` with mode and source trace |

---

## Planned Features

| Feature | Status |
|---|---|
| User authentication | Planned — v0.4 |
| RBAC (role-based access control) | Planned — v0.5 |
| Workspace / team isolation | Planned — v0.5 |
| OTEL audit log export | Planned — v0.4 |
| Hosted deployment hardening | Planned — v1.0 |

---

## Reporting Vulnerabilities

See [SECURITY.md](../SECURITY.md) in the project root for the full security policy and how to report vulnerabilities privately.

Do not open a public GitHub issue for security vulnerabilities — use the GitHub Security Advisories link instead.

---

## Local-First Data Model

By default, all trace data stays on your machine:

- SQLite database at `.agentmesh/agentmesh.db`
- Dashboard API bound to `127.0.0.1` (not exposed to the network)
- No telemetry sent to Anthropic or any third party
- No cloud account required

To share data with a team, deploy the dashboard server behind a reverse proxy (nginx, Caddy) with TLS and set `AGENTMESH_AUTH_MODE=api_key`.
