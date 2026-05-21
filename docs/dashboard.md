# Dashboard

The AgentMesh local dashboard is a production-oriented debugging console. Every page is built around a real use case: diagnosing a failure, understanding cost, reviewing an approval, or replaying a broken run.

---

## Starting the Dashboard

```bash
agentmesh dashboard
```

Or with explicit host and port:

```bash
agentmesh dashboard --host 127.0.0.1 --port 8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787) in your browser.

---

## Seeding Demo Data

To explore the dashboard with realistic data before running your own workflows:

```bash
agentmesh demo seed --reset
```

This populates the database with a set of pre-built traces covering successful runs, failures, retries, RAG retrievals, and approval events.

---

## Dashboard Pages

### Overview

The landing page. Answers: *is everything healthy right now?*

- Total runs today / this week, success/failure rate
- Average latency, total tokens, total cost
- Provider health indicators
- Budget usage progress bars
- Recent failures — click any to go straight to the trace
- Active workflow runs with live status

### Trace Explorer

The core debugging tool. Answers: *what exactly happened in this run?*

- Search and filter traces by status, agent, date range, cost
- **Span tree** — nested view: workflow → task → agent → model call → tool call
- **Waterfall timeline** — horizontal bar chart showing timing and parallelism
- **Event table** — every recorded event in chronological order
- **Span detail panel** — click any span for full inputs, outputs, latency, and metadata
- **Raw JSON** — view or copy the complete trace
- **Export** — download as standard JSON or OTEL JSON
- **Replay** — jump straight to Replay Studio for this trace

### Workflows

Answers: *how is my pipeline structured and where did it get slow or fail?*

- Node graph built from actual trace data — agent nodes, task nodes, model nodes, tool nodes, memory nodes, approval nodes
- Each node shows status, retries, cost, and latency
- Highlight the critical path through the graph

### Agents

Answers: *which agents are most expensive or error-prone?*

- Per-agent metrics: current status, active task, token usage, cost trend over time
- Tool call count and error rate
- Memory operation history
- Recent traces the agent appeared in

### Models

Answers: *which providers are slow or failing?*

- Provider health: calls, token split, cost, latency, p95, error rate, rate-limit hits
- Compare models side by side

### Costs

Answers: *where is my budget going?*

- Spend today / this week / this month
- Budget used vs remaining with visual progress bars
- Cost by workflow, agent, model, and provider
- Failed-run waste (cost spent on runs that ultimately failed)
- Cache savings (prompt-cache hits)
- Token split: prompt vs completion

### Tools

Answers: *what did each agent actually do?*

- Every tool call with input arguments and output result
- Duration, permission level, side-effect flag
- Approval status (pending / approved / rejected)
- Sandbox logs and MCP metadata

### Memory & RAG

Answers: *which document or memory record influenced this answer?*

- Memory operations: every read/write with key, value, agent, timestamp
- Versioned records: full history for long-term memory keys
- RAG retrievals: query, chunks, similarity scores, source metadata

### Approvals

Answers: *what is waiting for my review?*

- Pending approval queue, sorted by time
- Expand any request to see the full tool arguments
- Approve or reject with an optional reason
- Full history of past decisions

### Replay Studio

Answers: *how would the run have gone differently?*

- Browse all checkpoints for a trace (timeline view)
- Inspect full memory state at any checkpoint
- Patch memory values inline and re-run from that point
- Compare original run vs replayed run side by side

---

## Building the Frontend

The dashboard has two modes:

1. **HTML fallback** — FastAPI serves a minimal single-page app. Works with no build step. Good for quick local use.
2. **React build** — Full production UI with all features.

```bash
cd dashboard
npm ci
npm run build
cd ..
agentmesh dashboard
```

---

## Generating Screenshots

```bash
agentmesh demo seed --reset
agentmesh dashboard &       # start the server
cd dashboard
npm run screenshots
```

Screenshots are written to `dashboard/screenshots/`. They appear in the README and HOW_IT_WORKS.md.

---

## Live Updates

The dashboard subscribes to live events via Server-Sent Events:

```
GET /api/events/stream
WS  /ws/events
```

Workflow status, agent status, and approval events all update in real time without refreshing the page.

---

## API Reference

See [api_reference.md](api_reference.md) for the full list of REST endpoints, query parameters, and authentication format.

---

## Light and Dark Mode

Toggle in the top-right corner of the dashboard. Preference is saved in `localStorage`.
