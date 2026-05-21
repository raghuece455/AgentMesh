# AgentMesh Dashboard

The production dashboard app is served by `agentmesh.dashboard:create_app`.

This directory contains a React + Tailwind frontend for:

- Workflow graph
- Agent monitoring
- Trace explorer
- Cost analytics
- Replay and checkpoint inspection

```bash
npm install
npm run build
cd ..
agentmesh dashboard
```

During development:

```bash
npm run dev
```

The Vite dev server proxies `/api` and `/metrics` to the FastAPI dashboard backend on port `8787`.

## Smoke Test

Start the AgentMesh dashboard backend with seeded data, then run:

```bash
AGENTMESH_DASHBOARD_URL=http://127.0.0.1:8790 npm run test:smoke
```

The smoke test checks the Overview, Recent Traces table, Open trace action, Failure Inbox, Provider Health, Trace Detail, Span Tree, Waterfall Timeline, Inspector tabs, OTEL export action, Cost Center, Replay Studio, cost status labels, and diagnostics text.

## README Screenshots

With the dashboard running against seeded demo data:

```bash
python -m agentmesh.cli demo seed --reset
python -m agentmesh.cli dashboard
AGENTMESH_DASHBOARD_URL=http://127.0.0.1:8790 npm run screenshots
```

Screenshots are written to `dashboard/screenshots/` for the Overview, Trace Detail cockpit, Workflow Graph, Cost Center, and Replay Studio.
