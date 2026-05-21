# How AgentMesh Works — A Complete Guide

This document explains AgentMesh from the ground up: the problem it solves, how every piece works, and how they all connect. Diagrams are included at every step. No prior AI framework experience required.

---

## Table of Contents

1. [The Problem AgentMesh Solves](#1-the-problem-agentmesh-solves)
2. [What is AgentMesh? (Simple Explanation)](#2-what-is-agentmesh-simple-explanation)
3. [Core Concepts — Explained Simply](#3-core-concepts--explained-simply)
4. [System Architecture](#4-system-architecture)
5. [How a Workflow Run Works — Step by Step](#5-how-a-workflow-run-works--step-by-step)
6. [Sequence Diagram: Running a Multi-Agent Workflow](#6-sequence-diagram-running-a-multi-agent-workflow)
7. [Parallel vs Sequential Execution](#7-parallel-vs-sequential-execution)
8. [Tool Execution and Human Approval Flow](#8-tool-execution-and-human-approval-flow)
9. [How Tracing Works](#9-how-tracing-works)
10. [RAG (Retrieval-Augmented Generation) Flow](#10-rag-retrieval-augmented-generation-flow)
11. [Cost Tracking Flow](#11-cost-tracking-flow)
12. [Replay and Time-Travel Debugging](#12-replay-and-time-travel-debugging)
13. [Dashboard Request-Response Flow](#13-dashboard-request-response-flow)
14. [Storage and Data Model](#14-storage-and-data-model)
15. [Real-World Use Cases](#15-real-world-use-cases)
16. [What Makes AgentMesh Different](#16-what-makes-agentmesh-different)
17. [Glossary](#17-glossary)

---

## 1. The Problem AgentMesh Solves

Imagine you asked a group of AI assistants to research a topic, write an article, and review it — all working together. Something goes wrong. The final article is wrong. Now you ask yourself:

> *Which AI made the mistake? What did it say? What information did it have? How much did it cost? Can I run it again safely?*

Without a tool like AgentMesh, you have **no answers**. You only see the final output. Everything that happened in between — which model was called, what it received, what tools were used, what it cost — is invisible.

This is the **observability gap** in AI agent systems.

```
Without AgentMesh                    With AgentMesh
─────────────────────                ─────────────────────────────────────
Input ──► [Black Box] ──► Output     Input ──► [Every step recorded] ──► Output
             ?                              ↕ (inspectable, replayable,
             ?                                 debuggable, costed)
             ?
```

**The specific problems AgentMesh solves:**

| Problem | What happens today | AgentMesh solution |
|---|---|---|
| No visibility into agent steps | You see output, nothing else | Every step is a recorded trace |
| Can't debug failures | Guess why it went wrong | Trace shows the exact failing event |
| Unknown costs | No idea what each run costs | Token usage and cost tracked per step |
| Can't reproduce a run | Same prompt → different result | Deterministic replay from saved state |
| No human oversight | Agents execute sensitive actions automatically | Human approval gates for any tool |
| Memory is lost | Each run starts fresh | Versioned long-term memory |
| Multi-model chaos | No idea which model did what | Every model call attributed and costed |

---

## 2. What is AgentMesh? (Simple Explanation)

**AgentMesh is a framework that:**
1. Lets you build AI agent systems (multiple AI assistants working together)
2. Records everything that happens during each run
3. Lets you inspect, debug, replay, and measure those runs from a dashboard

Think of it like **a flight data recorder (black box) + air traffic control tower** for your AI agents.

- The **flight data recorder** records everything that happened (prompts, responses, tool calls, costs, errors).
- The **air traffic control tower** (dashboard) shows you what's happening in real time and lets you investigate past flights.

```
Your AI Agents
      │
      │ (every action recorded automatically)
      ▼
 AgentMesh Runtime ──────────────────────────────────────┐
      │                                                   │
      │ writes                                            │
      ▼                                                   │
  SQLite DB                                              Dashboard
 (trace store) ◄──────────────────────────────────────── (read & inspect)
```

---

## 3. Core Concepts — Explained Simply

### 🤖 Agent
An **Agent** is one AI worker with a specific role. Like an employee: it has a job title, instructions, tools it can use, and an AI model powering its responses.

```
Agent = Role + Instructions + AI Model + Tools + Permissions
         ↓            ↓           ↓         ↓         ↓
      "Researcher"  "Find        GPT-4  [web_search]  READ
                    key facts"
```

### 📋 Task
A **Task** is a specific piece of work assigned to an agent. Like a ticket or request: "Summarize this document" or "Send a notification."

### 🔄 Workflow
A **Workflow** coordinates multiple agents and tasks. Like a project plan: it decides which agent does what, in what order, and how outputs flow between them.

```
Workflow: Research → Write → Review
             │          │        │
         Researcher   Writer  Reviewer
           Agent      Agent    Agent
```

### 🛠️ Tool
A **Tool** is a function an agent can call to interact with the world. Like a real tool: a phone (send email), a calculator (compute), a database (look something up).

### 🧠 Memory
**Memory** is state that persists across steps. Short-term memory lives during one run. Long-term memory is saved to the database and available across runs.

### 📊 Trace
A **Trace** is the complete recording of one workflow run — every event, from start to finish. Like a video recording of everything that happened.

### 💰 Cost
AgentMesh tracks how many tokens each model call used and estimates the dollar cost, so you know exactly what each run costs.

### ⏪ Replay
**Replay** lets you re-run a previous workflow using the recorded inputs and outputs — without calling real APIs. Like watching a replay in a sports game, but you can also fork from any point.

---

## 4. System Architecture

This is the full picture of AgentMesh. Every box is a component; every arrow is how they communicate.

```mermaid
flowchart TD
    subgraph USER["👤 Your Code / CLI"]
        CODE["workflow.run()"]
        CLI["agentmesh CLI"]
    end

    subgraph RUNTIME["⚙️ AgentMesh Runtime"]
        direction TB
        WF["Workflow\n(orchestrator)"]
        SCHED["WorkflowScheduler\n(sequential / parallel /\nhierarchical / event-driven)"]
        AGENT["Agent\n(role + model + tools)"]
        TOOLS["ToolRegistry\n(typed tools + permissions)"]
        PROVIDER["ModelProvider\n(OpenAI / Anthropic /\nOllama / Gemini / Mock)"]
        BUDGET["BudgetLimiter\n(token + cost budget)"]
        RETRY["RetryPolicy\n(exponential backoff + jitter)"]
        MEMORY["WorkflowMemory\n(short-term state)"]
    end

    subgraph OBS["🔍 Observability Layer"]
        TRACE["TraceRecorder\n(writes every event)"]
        METRICS["Metrics\n(Prometheus-style)"]
        OTEL["OpenTelemetry Bridge\n(OTLP export)"]
    end

    subgraph STORAGE["💾 Storage Layer"]
        SQLITE["SQLiteStore\n(default local DB)"]
        POSTGRES["PostgreSQLStore\n(production)"]
    end

    subgraph DASH["🖥️ Dashboard"]
        API["FastAPI\n(REST + SSE + WebSocket)"]
        UI["React Dashboard\n(browser)"]
    end

    subgraph EXTRA["🔌 Optional Adapters"]
        FAISS["FAISS VectorStore\n(RAG)"]
        REDIS["Redis EventBus"]
        NATS["NATS EventBus"]
    end

    CODE --> WF
    CLI --> API
    WF --> SCHED
    SCHED --> AGENT
    AGENT --> TOOLS
    AGENT --> PROVIDER
    AGENT --> BUDGET
    AGENT --> RETRY
    AGENT --> MEMORY
    WF --> TRACE
    AGENT --> TRACE
    TRACE --> SQLITE
    TRACE --> POSTGRES
    TRACE --> METRICS
    METRICS --> OTEL
    SQLITE --> API
    POSTGRES --> API
    API --> UI
    FAISS --> AGENT
    REDIS --> SCHED
    NATS --> SCHED
```

---

## 5. How a Workflow Run Works — Step by Step

Here is exactly what happens when you call `workflow.run()`:

```mermaid
flowchart LR
    A([Start:\nworkflow.run]) --> B[Generate\ntrace_id]
    B --> C[Create RunContext\n+ WorkflowMemory\n+ BudgetLimiter]
    C --> D{Workflow\nMode?}

    D -->|sequential| E[Run Step 1\nthen Step 2\nthen Step N]
    D -->|parallel| F[Run all steps\nsimultaneously]
    D -->|hierarchical| G[Run steps in\ndependency order]
    D -->|event_driven| H[Wait for events\nthen run steps]

    E --> I[For each Step:\nSend AgentMessage\nto Agent]
    F --> I
    G --> I
    H --> I

    I --> J[Agent runs Tools\nin parallel]
    J --> K[Agent builds Prompt\nfrom task + tools +\nmemory + context]
    K --> L[ModelProvider.generate\nAPI call to LLM]
    L --> M[Record cost,\nlatency, tokens]
    M --> N[Save checkpoint\nto DB]
    N --> O{More\nsteps?}
    O -->|yes| I
    O -->|no| P[Mark workflow\nsucceeded]
    P --> Q([Return WorkflowResult\nwith trace_id])
```

**Key insight:** At every arrow in this diagram, an event is written to the database. By the time you see `trace_id`, the entire run is already recorded and inspectable in the dashboard.

---

## 6. Sequence Diagram: Running a Multi-Agent Workflow

This shows the exact sequence of calls for a **Researcher → Writer → Reviewer** workflow:

```mermaid
sequenceDiagram
    participant U as Your Code
    participant W as Workflow
    participant S as Scheduler
    participant TR as TraceRecorder
    participant DB as SQLiteStore
    participant R as Researcher Agent
    participant MP as ModelProvider (OpenAI)
    participant Wr as Writer Agent
    participant Rv as Reviewer Agent

    U->>W: workflow.run({"goal": "write article"})
    W->>TR: start_workflow("research-write-review")
    TR->>DB: INSERT workflows (trace_id, status=running)

    W->>S: run_sequential(steps)

    Note over S,R: ── Step 1: Researcher ──
    S->>TR: event("task.started", "researcher")
    TR->>DB: INSERT events
    S->>R: agent.run(AgentMessage)
    R->>TR: event("agent.started", "researcher")
    TR->>DB: INSERT events
    R->>MP: generate(ModelRequest)
    MP-->>R: ModelResponse(text, tokens, cost)
    R->>TR: event("model.response", tokens=412, cost=$0.002)
    TR->>DB: INSERT model_calls, cost_records
    R-->>S: AgentResult("Research complete: ...")
    S->>TR: event("task.finished", "researcher")
    TR->>DB: INSERT events, checkpoint

    Note over S,Wr: ── Step 2: Writer (gets researcher output) ──
    S->>Wr: agent.run(AgentMessage with researcher output)
    Wr->>MP: generate(ModelRequest with context)
    MP-->>Wr: ModelResponse(text, tokens, cost)
    Wr->>TR: event("model.response", tokens=891, cost=$0.004)
    TR->>DB: INSERT model_calls, cost_records
    Wr-->>S: AgentResult("Draft article: ...")

    Note over S,Rv: ── Step 3: Reviewer ──
    S->>Rv: agent.run(AgentMessage with writer output)
    Rv->>MP: generate(ModelRequest)
    MP-->>Rv: ModelResponse
    Rv-->>S: AgentResult("Approved with edits")

    S-->>W: all outputs collected
    W->>TR: finish_workflow(status=succeeded)
    TR->>DB: UPDATE workflows, INSERT cost summary
    W-->>U: WorkflowResult(trace_id="abc123", output="Approved with edits")

    Note over U,DB: Every step is now in the DB — inspectable from the dashboard
```

---

## 7. Parallel vs Sequential Execution

AgentMesh supports 4 workflow modes. Here's how they look:

### Sequential — one after another

```mermaid
gantt
    title Sequential Workflow (total = sum of all steps)
    dateFormat X
    axisFormat %s

    section Agents
    Researcher  : 0, 3
    Writer      : 3, 6
    Reviewer    : 6, 8
```

### Parallel — all at once

```mermaid
gantt
    title Parallel Workflow (total = longest step)
    dateFormat X
    axisFormat %s

    section Agents
    Researcher  : 0, 3
    Writer      : 0, 5
    Reviewer    : 0, 2
```

### Hierarchical — dependency-based

```mermaid
flowchart LR
    A[Researcher] --> C[Writer]
    B[Data Fetcher] --> C
    C --> D[Reviewer]
    D --> E[Publisher]

    style A fill:#3b82f6,color:#fff
    style B fill:#3b82f6,color:#fff
    style C fill:#8b5cf6,color:#fff
    style D fill:#f59e0b,color:#fff
    style E fill:#10b981,color:#fff
```

A and B run in parallel. C waits for both. D waits for C. E waits for D. Each `depends_on` in `add_step()` controls this graph.

### Event-Driven — triggered by events

```mermaid
sequenceDiagram
    participant EB as AsyncEventBus
    participant S as Scheduler
    participant A as Alert Agent
    participant N as Notifier Agent

    EB->>S: event("data.anomaly", payload)
    S->>A: trigger Alert Agent
    A-->>EB: publish("alert.created")
    EB->>S: event("alert.created")
    S->>N: trigger Notifier Agent
    N-->>EB: publish("notification.sent")
```

---

## 8. Tool Execution and Human Approval Flow

Tools are functions your agents can call — like searching the web, reading a file, or sending an email. Sensitive tools can require a human to approve before they run.

```mermaid
sequenceDiagram
    participant A as Agent
    participant TR as ToolRegistry
    participant P as Permission Check
    participant H as Human (Approval Callback)
    participant T as Tool Function
    participant DB as SQLiteStore

    A->>TR: execute("send_email", {to: "team@...", body: "..."})
    TR->>P: check permissions (SENSITIVE level)
    P-->>TR: ✅ agent has SENSITIVE permission

    TR->>DB: INSERT approval_request (status=pending)
    TR->>H: 🔔 "Approve send_email for team@example.com?"
    H-->>TR: approved=True, reason="looks good"
    TR->>DB: UPDATE approval (status=approved)

    TR->>T: run tool function(arguments)
    T-->>TR: result {sent: true}

    TR->>DB: INSERT tool_calls (duration, result, status=success)
    TR-->>A: {"sent": true}

    Note over A,DB: Entire approval chain is in the trace
```

**If a tool is rejected:**

```mermaid
flowchart LR
    A[Agent requests\nsend_email] --> B{Human\napproves?}
    B -->|Yes| C[Tool runs\nresult recorded]
    B -->|No| D[PermissionDenied\nerror raised]
    D --> E[Workflow records\nrejection event]
    E --> F[Dashboard shows\nrejected approval]
    style D fill:#ef4444,color:#fff
    style F fill:#f97316,color:#fff
```

---

## 9. How Tracing Works

Every single thing that happens in a workflow gets recorded as a **span** (a timed unit of work) nested inside a **trace** (the full run). This is similar to how a medical chart records every procedure during a hospital visit.

```mermaid
flowchart TD
    T["Trace: research-write-review\ntrace_id: abc123\nStarted: 10:00:00  Ended: 10:00:08"]

    T --> S1["Span: task.researcher\n10:00:00 → 10:00:03"]
    T --> S2["Span: task.writer\n10:00:03 → 10:00:06"]
    T --> S3["Span: task.reviewer\n10:00:06 → 10:00:08"]

    S1 --> E1["Event: agent.started"]
    S1 --> E2["Event: model.call\nprompt=... tokens=412"]
    S1 --> E3["Event: model.response\ncost=$0.002 latency=1.2s"]
    S1 --> E4["Event: agent.finished"]

    S2 --> E5["Event: agent.started"]
    S2 --> E6["Event: tool.started (web_search)"]
    S2 --> E7["Event: tool.finished\nresult={...}"]
    S2 --> E8["Event: model.call"]
    S2 --> E9["Event: model.response"]

    S3 --> E10["Event: agent.started"]
    S3 --> E11["Event: model.response"]
    S3 --> E12["Event: agent.finished"]

    style T fill:#1e293b,color:#94a3b8
    style S1 fill:#1e40af,color:#fff
    style S2 fill:#1e40af,color:#fff
    style S3 fill:#1e40af,color:#fff
```

**Every recorded field for a model call:**
- Prompt text (what the agent was told)
- Model name and provider
- Token counts (prompt, completion, cached, reasoning)
- Latency in milliseconds
- Estimated cost in USD
- Error details (if it failed)
- Request ID (from the provider)
- Parent span ID (which task triggered this call)

**What happens in the database:** Every event is a row in the `events` table. The dashboard queries these rows and reconstructs the visual timeline you see in the Trace Explorer.

---

## 10. RAG (Retrieval-Augmented Generation) Flow

RAG means giving your agent access to a document library. Instead of relying only on what the AI model knows, the agent first searches your documents, then uses what it finds to answer better.

```mermaid
sequenceDiagram
    participant A as Agent
    participant RE as RetrievalEngine
    participant VS as VectorStore (FAISS or SQLite)
    participant TR as TraceRecorder
    participant DB as SQLiteStore

    Note over A,DB: Step 1 — Ingest documents (done once)
    A->>RE: ingest({"docs/guide.md": "AgentMesh traces..."})
    RE->>VS: embed text → store vectors
    VS->>DB: INSERT documents (content, embedding)

    Note over A,DB: Step 2 — Retrieve during a run
    A->>RE: retrieve("How does AgentMesh trace RAG?", top_k=3)
    RE->>VS: similarity_search(query_embedding)
    VS-->>RE: [chunk1 score=0.91, chunk2 score=0.87, ...]
    RE->>TR: event("rag.retrieved", query, chunks, scores)
    TR->>DB: INSERT rag_retrievals
    RE-->>A: [RetrievalResult(text, source, score), ...]

    A->>A: Build prompt with retrieved chunks
    A->>MP: generate(prompt with RAG context)
    MP-->>A: ModelResponse (grounded in your docs)
```

**In the dashboard** — the Memory & RAG page shows:
- Which query triggered each retrieval
- Which chunks were returned and their similarity scores
- Which source documents were used
- How this affected the final model answer

---

## 11. Cost Tracking Flow

AgentMesh automatically measures what every LLM call costs and accumulates it into a budget.

```mermaid
flowchart TD
    MC["Model Call Completes\nGPT-4o mini\nprompt_tokens: 1,200\ncompletion_tokens: 450"]

    MC --> PE["Pricing Engine\nestimates cost\nfrom pricing table"]

    PE --> CS["Cost: $0.0019\n(1200 × $0.00015 + 450 × $0.0006)"]
    CS --> BL["BudgetLimiter.reserve\n(thread-safe check)"]

    BL -->|within budget| CR["INSERT cost_records\ntrace_id, agent, model\ncost_usd, tokens, status=estimated"]
    BL -->|over budget| EX["BudgetExceeded raised\nworkflow stops immediately\nerror recorded in trace"]

    CR --> CA["CostTracker aggregates\ntotal spend by:\n• workflow\n• agent\n• model\n• provider"]

    CA --> DASH["Dashboard Cost Center:\n💰 Today: $0.42\n📉 Budget used: 67%\n🔴 Failed-run waste: $0.08"]
```

**Cost statuses:**

| Status | Meaning |
|---|---|
| `exact` | Provider reported the exact cost |
| `estimated` | Calculated from local pricing rules |
| `local/free` | Ollama, vLLM, or Mock — no cloud cost |
| `unknown` | No pricing rule found for this model |

**Set a budget to automatically stop runaway agents:**
```python
budget = BudgetLimiter(max_cost_usd=0.50, max_total_tokens=100_000)
workflow = Workflow("my-workflow", budget=budget)
```

The moment an agent exceeds $0.50 total, the workflow raises `BudgetExceeded` and stops — no surprise bills.

---

## 12. Replay and Time-Travel Debugging

This is one of AgentMesh's most powerful features. Because every prompt, response, tool call, and memory state is recorded, you can:

1. **Replay** a past run without calling real LLMs (deterministic)
2. **Fork** from any checkpoint and change the memory
3. **Diagnose** exactly which step failed and why

```mermaid
flowchart TD
    ORIG["Original Run\ntrace_id: abc123\nFailed at Step 3"]

    ORIG --> CP1["Checkpoint 1\nafter Step 1\nState: {topic: 'AI'}"]
    ORIG --> CP2["Checkpoint 2\nafter Step 2\nState: {draft: '...'}"]
    ORIG --> FAIL["Step 3 FAILED\nBudgetExceeded"]

    CP2 --> FORK["Time-Travel Fork\nPatch memory:\n{draft: 'shorter draft'}"]
    FORK --> REPLAY["Replay from Step 3\nUsing patched state\nNo real API calls"]
    REPLAY --> SUCCESS["Step 3 Succeeds\nNew trace_id: xyz789"]

    style FAIL fill:#ef4444,color:#fff
    style FORK fill:#8b5cf6,color:#fff
    style SUCCESS fill:#10b981,color:#fff
```

**Three replay modes:**

| Mode | What it does | Real API calls? |
|---|---|---|
| `deterministic` | Uses recorded model outputs and tool results | ❌ None |
| `simulated` | Uses mock outputs matching the original shape | ❌ None |
| `live` | Calls real providers/tools — may get different results | ✅ Yes |

```bash
# Safe replay — no API costs
agentmesh replay abc123 --mode deterministic

# Fork from a checkpoint and patch memory
agentmesh checkpoints list abc123
agentmesh checkpoints patch-memory ckpt_456 --set '{"draft": "shorter version"}'

# Diagnose what went wrong
agentmesh diagnose abc123
```

---

## 13. Dashboard Request-Response Flow

This shows exactly what happens when you open the AgentMesh dashboard in your browser.

```mermaid
sequenceDiagram
    actor U as You (Browser)
    participant N as React App
    participant API as FastAPI Server
    participant S as TraceService
    participant DB as SQLiteStore

    Note over U,DB: Opening the Dashboard
    U->>N: open http://127.0.0.1:8787
    N->>API: GET /api/overview
    API->>S: overview()
    S->>DB: SELECT traces, costs, provider_health...
    DB-->>S: aggregated data
    S-->>API: {total_runs: 42, success_rate: 94%, ...}
    API-->>N: JSON response
    N-->>U: Overview page renders

    Note over U,DB: Clicking on a Trace
    U->>N: click "research-write-review" trace
    N->>API: GET /api/traces/abc123
    API->>S: get_trace_detail("abc123")
    S->>DB: SELECT events, spans, model_calls,\ntool_calls, costs, checkpoints...
    DB-->>S: all trace data
    S-->>API: {trace, events, spans, model_calls, ...}
    API-->>N: JSON response
    N-->>U: Trace Detail cockpit renders\n(span tree, waterfall, inspector)

    Note over U,DB: Live Updates via SSE
    N->>API: GET /api/events/stream (SSE connection)
    loop Every new workflow event
        DB-->>API: new event written
        API-->>N: data: {event_type: "model.response", ...}
        N-->>U: Dashboard updates in real-time
    end

    Note over U,DB: Exporting a Trace
    U->>N: click "Export as OTEL JSON"
    N->>API: GET /api/traces/abc123/export?format=otel-json
    API->>S: export_trace_otel_json("abc123")
    S->>DB: load full trace
    S->>S: convert to OpenTelemetry spans format
    API-->>N: otel-compatible JSON
    N-->>U: file download triggered
```

### Dashboard API Endpoints at a Glance

```mermaid
flowchart LR
    subgraph OVERVIEW["Overview"]
        O1["GET /api/overview\n(metrics summary)"]
        O2["GET /api/overview/timeseries\n(chart data)"]
    end

    subgraph TRACES["Traces"]
        T1["GET /api/traces\n(list with filters)"]
        T2["GET /api/traces/:id\n(full detail)"]
        T3["GET /api/traces/:id/spans"]
        T4["GET /api/traces/:id/export\n(?format=otel-json)"]
        T5["GET /api/compare?left=&right="]
    end

    subgraph OPS["Operations"]
        C1["GET /api/costs/summary"]
        M1["GET /api/memory/operations"]
        R1["GET /api/rag/retrievals"]
        A1["GET /api/approvals\nPOST /api/approvals/:id/resolve"]
        P1["GET /api/prompts"]
    end

    subgraph HEALTH["Health"]
        H1["GET /healthz (liveness)"]
        H2["GET /readyz (readiness)"]
        H3["GET /api/health (provider status)"]
    end
```

---

## 14. Storage and Data Model

AgentMesh stores everything in SQLite (default) or PostgreSQL. Here is the data model:

```mermaid
erDiagram
    WORKFLOWS {
        text trace_id PK
        text name
        text status
        text started_at
        text ended_at
        text input_json
        text output_json
        text error_json
    }

    EVENTS {
        text event_id PK
        text trace_id FK
        text span_id
        text parent_span_id
        text timestamp
        text event_type
        text actor
        text payload_json
    }

    MODEL_CALLS {
        text call_id PK
        text trace_id FK
        text agent
        text provider
        text model
        int prompt_tokens
        int completion_tokens
        real cost_usd
        real latency_ms
    }

    TOOL_CALLS {
        text tool_call_id PK
        text trace_id FK
        text agent
        text tool_name
        text status
        text input_json
        text output_json
        real duration_ms
    }

    COST_RECORDS {
        int id PK
        text trace_id FK
        text agent
        text model
        real cost_usd
        text cost_status
    }

    CHECKPOINTS {
        text checkpoint_id PK
        text trace_id FK
        text step_id
        text checkpoint_type
        text state_json
    }

    APPROVALS {
        text approval_id PK
        text trace_id FK
        text agent
        text tool
        text status
        text reason
    }

    WORKFLOWS ||--o{ EVENTS : "has"
    WORKFLOWS ||--o{ MODEL_CALLS : "has"
    WORKFLOWS ||--o{ TOOL_CALLS : "has"
    WORKFLOWS ||--o{ COST_RECORDS : "has"
    WORKFLOWS ||--o{ CHECKPOINTS : "has"
    WORKFLOWS ||--o{ APPROVALS : "has"
```

**How the data flows:**

```
workflow.run() called
      │
      ├─► INSERT workflows (status=running)
      │
      │   (for each agent step)
      ├─► INSERT events (agent.started, model.call, model.response, agent.finished)
      ├─► INSERT model_calls (one row per LLM call)
      ├─► INSERT tool_calls (one row per tool execution)
      ├─► INSERT cost_records (one row per model call)
      ├─► INSERT checkpoints (before + after each step)
      │
      └─► UPDATE workflows (status=succeeded/failed)
```

All of this happens automatically — you write `workflow.run()`, AgentMesh handles the rest.

---

## 15. Real-World Use Cases

### Use Case 1: Customer Support Automation

```mermaid
flowchart LR
    Q["Customer Query:\n'My order #1234 is late'"]

    Q --> A1["Order Lookup Agent\n(tool: query_database)"]
    A1 --> A2["Status Agent\n(tool: check_carrier_api)"]
    A2 --> A3["Response Agent\n(writes customer reply)"]
    A3 --> R["'Your order ships tomorrow.\nTracking: UPS-789'"]

    A1 -.->|"AgentMesh records"| DB[(Trace DB)]
    A2 -.->|"every DB query"| DB
    A3 -.->|"every API call"| DB
    A3 -.->|"full cost + latency"| DB
```

**What AgentMesh gives you:**
- Which step caused slow responses (latency by span)
- What the DB query returned (tool call inspector)
- How much each customer interaction costs (cost per trace)
- Why a reply was wrong (replay with the exact recorded prompt)

---

### Use Case 2: Research and Report Generation

```mermaid
sequenceDiagram
    participant U as User
    participant W as Workflow
    participant R as Researcher
    participant W2 as Writer
    participant Rev as Reviewer
    participant DB as AgentMesh DB

    U->>W: run("Write a report on AI trends")

    par Parallel research
        W->>R: research("AI trends 2025")
        W->>R: research("AI market size")
    end

    R-->>W: research summaries
    W->>W2: write(summaries)
    W2-->>W: draft report

    W->>Rev: review(draft)
    Rev-->>W: "Approved"

    W-->>U: Final report + trace_id

    Note over U,DB: Later — someone questions a fact
    U->>DB: agentmesh replay trace_id
    DB-->>U: Exact prompt + sources used + model answer
```

---

### Use Case 3: Code Review Pipeline

```mermaid
flowchart TD
    PR["Pull Request\nopened"]

    PR --> A1["Security Scanner Agent\n(checks for vulnerabilities)"]
    PR --> A2["Style Checker Agent\n(checks code style)"]
    PR --> A3["Test Coverage Agent\n(checks test gaps)"]

    A1 --> A4["Summary Agent\n(combines all findings)"]
    A2 --> A4
    A3 --> A4

    A4 --> COM["Post review comment\n(requires human approval\nif CRITICAL issues found)"]

    style A1 fill:#ef4444,color:#fff
    style A4 fill:#8b5cf6,color:#fff
    style COM fill:#f59e0b,color:#fff
```

**With AgentMesh:**
- The `send_comment` tool requires `requires_approval=True` when security issues are critical
- A human reviews the findings before the comment is posted
- The entire decision trail is in the audit log

---

### Use Case 4: Data Processing with Cost Control

```python
# Stop if this run costs more than $2
budget = BudgetLimiter(max_cost_usd=2.00)
workflow = Workflow("nightly-analysis", budget=budget)
```

```mermaid
flowchart LR
    D["1000 records\nto process"]

    D --> B{Budget\n$2.00}
    B -->|within budget| P["Process records\none by one"]
    P --> C{Cost so far\n> $2.00?}
    C -->|No| P
    C -->|Yes| STOP["BudgetExceeded\nraise + record"]
    STOP --> DASH["Dashboard shows:\n'Processed 847/1000\nStopped at $2.00'\n'Failed-run waste: $0'\n(clean stop, not an error)"]
    B -->|over at start| ERR["Immediate stop"]

    style STOP fill:#f59e0b,color:#fff
    style DASH fill:#10b981,color:#fff
```

---

## 16. What Makes AgentMesh Different

Most tools either **orchestrate** AI agents OR **observe** them. AgentMesh does both in one package.

```mermaid
flowchart LR
    subgraph OTHERS["Other Tools"]
        direction TB
        LC["LangChain\nOrchestrates\nbut limited observability"]
        LS["LangSmith\nObserves\nbut doesn't orchestrate"]
        LF["LangFuse\nObserves LLM calls\nbut not full workflows"]
    end

    subgraph AM["AgentMesh"]
        direction TB
        ORCH["Orchestrates workflows\n(sequential/parallel/hierarchical)"]
        OBS["Observes everything\n(traces/costs/replay)"]
        ORCH <--> OBS
    end

    style AM fill:#1e293b,color:#94a3b8
    style ORCH fill:#3b82f6,color:#fff
    style OBS fill:#8b5cf6,color:#fff
```

**Key differentiators:**

| Feature | What it means for you |
|---|---|
| **One package for orchestration + observability** | No need to wire two separate systems together |
| **Local-first** | Your prompts and data never leave your machine by default |
| **Zero config** | `pip install -e .` + one command and you have a working dashboard |
| **Deterministic replay** | Re-run without API costs — great for debugging and CI |
| **Time-travel checkpoints** | Go back to any step, change memory, continue |
| **Human approval gates** | Any tool can require approval before running |
| **Budget enforcement** | Hard stop if costs exceed limits — no surprise bills |
| **Works with any LLM** | OpenAI, Anthropic, Gemini, Ollama, vLLM, Azure, your own |
| **OpenTelemetry export** | Send traces to Jaeger, Grafana Tempo, Datadog, Honeycomb |

---

## 17. Glossary

| Term | Simple definition |
|---|---|
| **Agent** | An AI worker with a role, instructions, and a model powering it |
| **Workflow** | A plan that coordinates multiple agents and their tasks |
| **Task** | A specific piece of work assigned to one agent |
| **Tool** | A function an agent can call (search, database, email, etc.) |
| **Trace** | The complete recording of one workflow run |
| **Span** | One timed unit of work inside a trace (e.g., one agent step) |
| **Event** | A single recorded moment (model call, tool call, error, etc.) |
| **Checkpoint** | A snapshot of workflow memory saved at each step |
| **Replay** | Re-running a past trace without calling real APIs |
| **Time-Travel** | Forking a workflow from any saved checkpoint |
| **BudgetLimiter** | A hard limit on tokens or dollars spent per run |
| **RetryPolicy** | Rules for automatically retrying failed steps |
| **CircuitBreaker** | Stops trying a provider after too many failures |
| **RAG** | Retrieval-Augmented Generation — searching your documents during a run |
| **VectorStore** | A database that stores document embeddings for similarity search |
| **Embedding** | A numeric representation of text used for similarity comparisons |
| **MockModelProvider** | A fake AI model that returns preset answers — used for testing |
| **OTEL / OpenTelemetry** | An industry standard for traces and metrics that tools like Jaeger and Datadog understand |
| **SQLite** | A local file-based database — AgentMesh's default storage |
| **Trace ID** | A unique ID for one workflow run — use it to find anything in the dashboard |
| **Dashboard** | The local web UI that shows traces, costs, tools, memory, and replays |
| **SSE** | Server-Sent Events — how the dashboard receives live updates from running workflows |
| **Approval Gate** | A pause where a human must approve before a sensitive tool executes |

---

## Quick Reference: Key Files

```
AgentMesh/
├── src/agentmesh/
│   ├── agents.py          # Agent class — runs tasks, calls tools and models
│   ├── workflow.py        # Workflow class — coordinates agents
│   ├── scheduler.py       # WorkflowScheduler — sequential/parallel/hierarchical execution
│   ├── providers.py       # 7 model providers (OpenAI, Anthropic, Gemini, Ollama, vLLM, Mock)
│   ├── tools.py           # Tool registry, permissions, approval flow
│   ├── storage.py         # SQLiteStore — all database reads and writes
│   ├── observability.py   # TraceRecorder — captures every event
│   ├── reliability.py     # RetryPolicy, BudgetLimiter, CircuitBreaker, RateLimiter
│   ├── rag.py             # RetrievalEngine, FAISS and SQLite vector stores
│   ├── debug.py           # ReplayEngine, TimeTravelDebugger, FailedRunDiagnosis
│   ├── dashboard.py       # FastAPI server — all REST endpoints
│   ├── cli.py             # Command-line interface
│   └── memory.py          # WorkflowMemory, SQLiteMemoryStore
├── dashboard/src/         # React + TypeScript frontend
├── examples/              # 20 runnable example workflows
├── tests/                 # pytest test suite
└── docs/                  # Reference documentation
```

---

*This document was written to be understandable to someone new to AI agent systems. If something is still unclear, please open a [GitHub Discussion](https://github.com/raghuece455/AgentMesh/discussions) — feedback improves this guide for everyone.*
