# Security

AgentMesh is `v0.4.1` software. The security posture is **local-first and auth-ready**, designed for safe local development, evaluation, and single-team self-hosting — not yet enterprise-hardened.

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

All API routes, the live event stream, and the OTLP receiver (`POST /v1/traces`) then require:

```
Authorization: Bearer your-secret-key
```

`X-AgentMesh-Api-Key: your-secret-key` is accepted as well. The dashboard asks for the key the first time it gets a `401` and keeps it in that browser's local storage. OpenTelemetry exporters send it with `OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20your-secret-key"`; the SDK with `agentmesh.init(api_key=...)` or `AGENTMESH_API_KEY`.

The default is `AGENTMESH_AUTH_MODE=none` (open access), which is correct for local single-user development.

---

### Trace Ingestion and Privacy

| Control | Setting |
|---|---|
| Don't store prompt/response text at all | `AGENTMESH_CAPTURE_CONTENT=false` on the server, or `agentmesh.init(capture_content=False)` in the SDK. Token usage, cost, timing, and errors are still recorded. |
| Limit stored content size | `AGENTMESH_MAX_CONTENT_CHARS` (default 100,000 characters per field) |
| Limit request size | `AGENTMESH_MAX_OTLP_BYTES` (default 32 MiB, enforced before and after gzip/deflate decompression; larger requests get `413`) |
| Delete old data | `agentmesh traces prune --older-than 30d [--vacuum]` |

### Alert Webhooks

- Only `http`/`https` webhook URLs are accepted, and redirects are never followed.
- Webhook URLs (which often embed a token, as Slack's do) and signing secrets are masked in API responses and the dashboard.
- With `--secret` / `channel.secret`, payloads carry `X-AgentMesh-Timestamp` and `X-AgentMesh-Signature` (HMAC-SHA256 over `"<timestamp>.<body>"`) so receivers can reject forged calls. See [alerts.md](alerts.md#verify-signatures).
- The server makes outbound requests to the URLs in alert rules. Turn on API-key auth before exposing it, so that only trusted clients can create rules.

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
| User authentication (login) | Planned — v0.5+ |
| RBAC (role-based access control) | Planned — v0.5+ |
| Workspace / team isolation | Planned — v0.5+ |
| OTEL audit log export | Planned |
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
