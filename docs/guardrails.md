# Guardrails

Observability tells you an agent looped 400 times, called a delete tool in production, or spent $80 on one ticket. Guardrails stop it while it happens.

A **policy** decides, before each tool call, LLM call, and agent start, whether it runs, needs a person's approval, or is blocked. A **halt** (the kill switch) stops a trace, an agent, a service, or everything at once. Both are saved in AgentMesh and reach running agents within seconds, without a redeploy.

![Guardrails page: active halt, blocked calls, and policies](../dashboard/screenshots/guardrails.png)

---

## Where guardrails apply

| Agents built with | What is checked | Status |
|---|---|---|
| Python SDK: `@agentmesh.observe(kind="tool" \| "llm" \| "agent")`, `agentmesh.span()` | every tool, LLM, and agent span, before the function body runs | enforced |
| OpenAI and Anthropic clients via `instrument_openai()` / `instrument_anthropic()` | every Chat Completions, Responses, Embeddings, and Messages call, before the HTTP request | enforced |
| AgentMesh runtime (`Workflow`, `Agent`, `ToolRegistry`) | every tool call, model call, and agent run | enforced |
| TypeScript SDK | | planned; traces still show up |
| Other frameworks over OTLP (`/v1/traces`) | | observe only: spans arrive after the call, so they cannot be blocked |

To enforce policies on a framework that only exports OpenTelemetry, wrap its tool functions with `@agentmesh.observe(kind="tool")`.

---

## Quickstart

```python
import agentmesh
from agentmesh import PolicyViolation

agentmesh.init(service_name="support-bot")      # the local database, or endpoint=... for a server

@agentmesh.observe(kind="tool")
def delete_customer(customer_id: str, env: str) -> str: ...

@agentmesh.observe(kind="tool")
def search_orders(query: str) -> list[dict]: ...
```

Save a policy from the dashboard (**Guardrails → New policy**), the CLI, or the API:

```yaml
# policy.yaml
name: production-safety
mode: enforce
limits:
  max_repeated_calls: 3        # the same tool with the same arguments: a loop
  max_cost_usd: 5
rules:
  - name: no-production-deletes
    match: {tool: "delete_*", arguments: {env: production}}
    action: deny
    reason: Deleting production data needs a person.
```

```bash
agentmesh policy apply policy.yaml
```

The agent now gets an exception instead of running the call:

```python
try:
    delete_customer("c-19", env="production")
except PolicyViolation as exc:
    print(exc.message)            # Deleting production data needs a person.
    print(exc.details["rule"])    # no-production-deletes
```

Every decision is recorded on the span, shown in the trace view, and listed on the Guardrails page. Run `python examples/guardrails.py` for an offline walkthrough.

---

## Writing policies

A policy is YAML or JSON with a `name`, a `mode`, and at least one rule or limit.

```yaml
name: support-agents
description: Guardrails for the support swarm.
mode: monitor                  # enforce | monitor
limits: { ... }                # per trace
rules: [ ... ]                 # checked in order; the first matching rule wins
approval:
  timeout_seconds: 300         # approvals nobody answers are denied
```

### Modes

- **`enforce`** blocks calls and waits for approvals.
- **`monitor`** blocks nothing. It records what would have been blocked (**Would block** on the dashboard), so you can roll a policy out safely: start in monitor mode, check the decisions and the simulation, then switch to enforce.

### Rules

```yaml
rules:
  - name: payments-need-approval
    match: {tool: ["issue_refund", "transfer_*"]}
    action: require_approval

  - name: approved-models-only
    match: {kind: llm}
    except: {model: ["gpt-4.1*", "claude-*"]}
    action: deny
    reason: This model is not on the approved list.

  - name: research-agents-read-only
    match: {agent: "research*", tool: ["write_*", "delete_*", "send_*"]}
    action: deny

  - name: api-keys-in-tool-input
    match: {kind: tool, input_regex: "(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"}
    action: deny

  - name: approved-domains-only
    match: {kind: tool, host: "*"}
    except: {host: ["*.mycompany.com", "api.openai.com"]}
    action: deny               # an egress allowlist, enforced before the call

  - name: health-checks
    match: {tool: ping}
    action: allow              # exempt from this policy, limits included
```

| Action | What happens |
|---|---|
| `deny` | The call does not run. The agent receives `PolicyViolation`. |
| `require_approval` | The call waits for a reviewer on the **Approvals** page. Approved calls run; rejected or unanswered calls raise `ApprovalDenied`. |
| `warn` | The call runs and the decision is recorded. |
| `allow` | The call runs and this policy's limits do not apply to it. |

A rule matches when every key in `match` matches and nothing in `except` does. Patterns use `*` wildcards and are case-insensitive; a list matches any of its patterns.

| Match key | Matches |
|---|---|
| `kind` | `tool`, `llm`, `agent`, or `any` |
| `tool` | tool name (tool calls only) |
| `model` | requested model (LLM calls only) |
| `name` | span name for any kind |
| `agent` | the agent the call runs under |
| `provider`, `service`, `environment` | `gen_ai.provider.name`, `service_name`, `environment` from `agentmesh.init()` |
| `host` | a host the call would reach, from its span attributes (`url.full`, `server.address`, ...) or its arguments. Calls with no host never match, so `match: {kind: tool, host: "*"}` scopes an allowlist to calls that go somewhere. See [access.md](access.md) |
| `arguments` | argument values by name; dotted paths reach nested values (`payee.country`) |
| `input_regex` | a regular expression searched in the call's arguments or prompt |

Names from Python functions match by their bare name too, so `tool: delete_*` matches a method `Tools.delete_user`.

`input_regex` runs on every matching call, so keep patterns simple; a pattern with nested repetition can be slow on long inputs.

### Limits

Limits count what one trace has done. When a call would break a limit, it is denied.

| Limit | Stops |
|---|---|
| `max_repeated_calls` | the same tool called with the same arguments more than N times (a loop) |
| `max_tool_calls` | more than N tool calls |
| `max_calls_per_tool` | more than N calls to any one tool |
| `max_llm_calls` | more than N LLM calls |
| `max_steps` | more than N tool, LLM, and agent calls combined |
| `max_cost_usd` | new calls once the trace has spent N dollars |
| `max_tokens` | new calls once the trace has used N tokens |
| `max_duration_seconds` | new calls once the trace has run N seconds |
| `max_agent_depth` | agents nested more than N deep (agents starting agents starting agents) |
| `max_child_agents` | an agent starting more than N sub-agents (swarm fan-out) |

Spend and tokens are known only after an LLM call returns, so the call that crosses `max_cost_usd` completes and every later call in the trace is stopped. The SDK counts cost from `agentmesh.cost_usd` or estimates it from token usage and the pricing table.

Several policies can apply at once. Every non-allow decision is recorded, and the strictest enforced one decides: `deny` over `require_approval` over `warn`.

### Swarm limits

Per-trace limits are counted inside each agent's own process, so they cannot cap a [swarm](swarms.md) that spreads over many processes: 200 workers each obeying "50 tool calls" still make 10,000 calls. A `swarm:` block limits the swarm as a whole:

```yaml
name: swarm-safety
mode: enforce
swarm:
  max_agents: 500                 # agents started in the swarm
  max_concurrent_agents: 200      # running at the same time
  max_spawn_rate_per_minute: 120  # how fast it is growing
  max_cost_usd: 50
  max_tokens: 5_000_000
  max_duration_minutes: 30
  match: {service: research-*}    # optional: only swarms whose name, service, or environment match
```

| Limit | Stops the swarm when |
|---|---|
| `max_agents` | more than N agents have started in it |
| `max_concurrent_agents` | more than N agents are running at once |
| `max_spawn_rate_per_minute` | more than N agents started in the last minute |
| `max_cost_usd` | spend reaches N dollars |
| `max_tokens` | usage reaches N tokens |
| `max_duration_minutes` | it has been running N minutes |

The server evaluates these from the spans it has received and **halts the swarm** when one is broken: every agent in it fails its next call, in every process, and the halt stays until someone releases it on the Guardrails page. In `monitor` mode the breach is recorded and nothing is stopped.

This is not instant. A swarm is stopped once its spans reach the server (about a second), the server has evaluated the limits (`AGENTMESH_SWARM_LIMIT_INTERVAL_SECONDS`, default 15), and its agents have polled the halt (`AGENTMESH_GUARDRAILS_REFRESH_SECONDS`, default 5) — so expect a handful of seconds and some overshoot. Use per-trace limits for instant, in-process caps and swarm limits for the total.

A limit halts a swarm once. If you release that halt while the swarm is still over the limit, AgentMesh leaves it alone — the override is yours — until a different limit breaks.

Run a check yourself with `agentmesh swarms check` or `POST /api/swarms/check`; `--no-enforce` (`?enforce=false`) is a dry run that writes nothing. The Swarms page shows usage against every limit that applies.

---

## Simulate before you enforce

Replay recent traces through a policy to see what it would have blocked, without touching running agents:

```bash
agentmesh policy simulate policy.yaml --hours 24
```

```json
{
  "traces_evaluated": 412,
  "traces_affected": 9,
  "blocked_calls": 31,
  "approval_calls": 4,
  "rules": [{"rule": "limit:max_repeated_calls", "action": "deny", "calls": 27, "traces": 6}]
}
```

In the dashboard, **Simulate on recent traces** in the policy editor shows the same report with links to each affected trace.

---

## Kill switch

Stop agents now, from the dashboard (**Stop agents**), the CLI, or the API:

```bash
agentmesh halt create --service support-bot --reason "Refund loop in production"
agentmesh halt create --agent research_swarm
agentmesh halt create --swarm swarm_8c1f04e2a9b3d756      # every agent in one swarm, see swarms.md
agentmesh halt create --trace 4bf92f3577b34da6a3ce929d0e0e4736
agentmesh halt create --all
agentmesh halt list
agentmesh halt release <halt_id>
```

A halted agent's next span raises `AgentHalted` (a `PolicyViolation`). Halting a service or everything also stops new traces from starting. Halts and releases are written to the audit log.

---

## Approvals

`require_approval` creates a pending request on the **Approvals** page with the call's arguments and the rule that asked for it. The agent waits:

- **Synchronous code** blocks the calling thread until a reviewer answers.
- **Async code** (`async def` tools, `await client.messages.create(...)`) waits in a worker thread, so the event loop keeps serving other requests.

When nobody answers within `approval.timeout_seconds` (default 300), the call is denied. Approvals work with the local database and with an AgentMesh server (`endpoint=`); policies passed only in code have nowhere to send the request, so those calls are denied.

---

## Policies in code

Pass policies to `agentmesh.init()` as dicts, YAML/JSON text, file paths, or `Policy` objects. They apply on top of the policies saved in AgentMesh:

```python
agentmesh.init(
    service_name="support-bot",
    policies=["policies/production.yaml", {"name": "local-limits", "limits": {"max_steps": 200}}],
)
```

Or set `AGENTMESH_POLICY_FILE=policies/production.yaml` (several files separated by `;` on Windows and `:` elsewhere).

---

## How enforcement works

- Policies and active halts are loaded from wherever traces go (the database, or `GET /api/guardrails/runtime` on the server) and cached for `AGENTMESH_GUARDRAILS_REFRESH_SECONDS` (default 5).
- Checks run in the agent's process against the cached policies: pattern matching and counters, with no network call. Only the very first check waits for policies to load; after that, a server is re-polled in a background thread, so a slow or unreachable server never delays an agent.
- If policies cannot be loaded, the last loaded policies stay in force (a warning is logged once). If none were ever loaded, calls are allowed, unless `AGENTMESH_GUARDRAILS_FAIL_CLOSED=true`, which denies every call until policies load.
- With `AGENTMESH_CAPTURE_CONTENT=false`, approval requests show argument names but not their values. Secrets are redacted from approval arguments either way.
- `AGENTMESH_GUARDRAILS=false` (or `agentmesh.init(guardrails=False)`) turns enforcement off in that process.
- Per-trace counters for limits are kept in memory for the most recent 2,000 traces per process. A trace that spans several processes is limited per process.
- SDK decisions travel with the span as `agentmesh.policy.decision` events and are stored when the span is ingested; runtime decisions are written directly and appear as `policy.decision` trace events.

---

## Reference

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `AGENTMESH_GUARDRAILS` | `true` | Enforce policies in this process |
| `AGENTMESH_POLICY_FILE` | | Extra policy files to enforce |
| `AGENTMESH_GUARDRAILS_REFRESH_SECONDS` | `5` | How often policies and halts are reloaded |
| `AGENTMESH_GUARDRAILS_FAIL_CLOSED` | `false` | Deny calls while no policies could be loaded |
| `AGENTMESH_SWARM_LIMIT_INTERVAL_SECONDS` | `15` | How often the server checks swarm limits; `0` turns the scheduler off (use `agentmesh swarms check`) |

### Exceptions

| Exception | Raised when |
|---|---|
| `agentmesh.PolicyViolation` | a rule or limit denied the call (base class of the two below) |
| `agentmesh.AgentHalted` | a halt stopped the call |
| `agentmesh.ApprovalDenied` | a reviewer rejected the call or nobody answered in time |

`exc.details` includes `rule`, `policy`, `kind`, `target`, `trace_id`, and, for limits, `limit`, `max`, and `used`.

### CLI

```bash
agentmesh policy validate policy.yaml
agentmesh policy apply policy.yaml [--disabled]     # create, or update the policy with that name
agentmesh policy list
agentmesh policy show <name>
agentmesh policy enable <name> | disable <name> | remove <name>
agentmesh policy simulate <file-or-name> [--hours 24] [--limit 200]
agentmesh policy decisions [--action blocked|would_block|require_approval|warn] [--trace <id>]
agentmesh swarms check [--no-enforce]                # evaluate swarm limits once
agentmesh halt create (--all | --swarm ID | --service NAME | --agent NAME | --trace ID) [--reason TEXT]
agentmesh halt list [--all]
agentmesh halt release <halt_id>
```

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/policies` | List policies |
| `POST` | `/api/policies` | Create a policy: `{"text": "<yaml or json>", "enabled": true}` or `{"spec": {...}}` |
| `GET` / `PATCH` / `DELETE` | `/api/policies/{id-or-name}` | Read, update (`text`, `spec`, `mode`, `enabled`), or delete |
| `POST` | `/api/policies/validate` | Check a policy without saving it |
| `POST` | `/api/policies/simulate` | Replay recent traces: `{"text": ...}` or `{"policy": "<name>"}`, optional `limit`, `hours` |
| `GET` | `/api/policy-decisions` | Decisions, filtered by `action`, `trace_id`, `hours`, `limit` |
| `GET` | `/api/guardrails/summary` | Counts for the last `hours` (default 24) |
| `GET` | `/api/guardrails/runtime` | Enabled policies and active halts, polled by SDKs |
| `GET` / `POST` | `/api/halts` | List (`?active=false` for history) or create `{"scope": "service", "value": "support-bot", "reason": "..."}`; scopes: `all`, `swarm`, `service`, `agent`, `trace` |
| `POST` | `/api/halts/{halt_id}/release` | Lift a halt |
| `POST` | `/api/swarms/check` | Evaluate swarm limits now; `?enforce=false` reports without halting |
| `POST` / `GET` | `/api/approvals`, `/api/approvals/{approval_id}` | Request an approval and poll it (used by SDKs) |

Invalid policies return `422` with `{"error": "invalid_policy", "errors": [...]}`, listing every problem found.
