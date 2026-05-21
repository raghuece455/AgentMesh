# Security Policy

AgentMesh is `v0.3.0-alpha` — a public alpha for local development and evaluation. It is not yet a hardened production control plane.

---

## Supported Versions

| Version | Supported |
|---|---|
| `0.3.x-alpha` (current) | ✅ Security fixes accepted |
| `0.1.x` | ❌ No longer maintained |

---

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately using one of these methods:

1. **GitHub Security Advisories (preferred)** — click **"Report a vulnerability"** on the [Security tab](https://github.com/raghuece455/AgentMesh/security/advisories/new) of this repository. GitHub keeps the report private until a fix is released.

2. **Email** — send details to **raghuece455@gmail.com** with the subject line `[AgentMesh Security] <brief description>`.

### What to include

- A description of the vulnerability and its potential impact
- Steps to reproduce (minimal script or trace export if applicable)
- Affected version (`agentmesh version`)
- Your environment (OS, Python version, provider)
- Any suggested fix or mitigation you have in mind

---

## Response Timeline

| Step | Target |
|---|---|
| Acknowledgement of your report | Within 48 hours |
| Initial assessment and severity rating | Within 5 business days |
| Fix or workaround provided | Within 30 days for critical issues |
| Public disclosure | After fix is released and users have time to update |

If a vulnerability is particularly severe, a patch release will be issued ahead of the normal schedule.

---

## Disclosure Policy

AgentMesh follows **coordinated disclosure**:

1. You report privately.
2. We confirm and reproduce the issue.
3. We develop and test a fix.
4. We release the fix and credit you (unless you prefer to remain anonymous).
5. We publish a security advisory describing the vulnerability.

We ask that you give us a reasonable window (typically 30 days) before any public disclosure.

---

## What Is In Scope

- Vulnerabilities in the AgentMesh Python runtime (`src/agentmesh/`)
- Secret leakage through traces, exports, or logs
- Authentication bypass in API key mode (`AGENTMESH_AUTH_MODE=api_key`)
- Permission escalation — an agent calling a tool above its declared permission level
- SQL injection or data corruption through the SQLite or PostgreSQL store
- Arbitrary code execution through tool sandboxing
- Denial of service through the budget limiter or retry policy

## What Is Out of Scope

- Vulnerabilities in third-party dependencies (report directly to the dependency maintainer)
- Issues that require physical access to the machine running AgentMesh
- Social engineering attacks against maintainers
- Issues in the demo seed data that have no real-world impact
- The dashboard running without TLS on localhost (by design for local development — do not expose it to the public internet without a reverse proxy)

---

## Current Security Posture

### Implemented

| Feature | Detail |
|---|---|
| Secret redaction | API keys, tokens, passwords, private keys, AWS credentials, database URLs, cookies, and auth headers are redacted before any trace data is persisted or exported |
| API key auth | `AGENTMESH_AUTH_MODE=api_key` requires `Authorization: Bearer <key>` for all dashboard API routes |
| Tool permission levels | `READ`, `WRITE`, `EXECUTE`, `SENSITIVE` — agents are blocked from calling tools above their granted level |
| Human approval gates | Sensitive tools pause for human approval before executing; decisions are audit-logged |
| Audit events | Tool calls, approvals, memory writes, and trace exports all create immutable audit records |

### Planned

| Feature | Target |
|---|---|
| User authentication (login) | v0.4 |
| RBAC — roles and team permissions | v0.5 |
| Workspace isolation | v0.5 |
| Full OTLP exporter hardening | v0.4 |
| Hosted deployment security review | v1.0 |

---

## Acknowledgements

We are grateful to everyone who takes the time to responsibly disclose security issues. Reporters of valid vulnerabilities will be credited in the release notes unless they request anonymity.
