# AgentMesh Dashboard

The production dashboard app is served by `agentmesh.dashboard:create_app`.

This directory contains a React + Tailwind frontend for:

- Trace explorer with span tree, waterfall, and automatic insights
- Sessions (multi-turn conversations) and scores/feedback
- Datasets & Evals: datasets, experiments with per-evaluator scores, and item-by-item comparisons; Add to dataset on traces
- Alerts: rules, test notifications, and alert history
- Workflow graph and agent monitoring
- Cost analytics
- Replay and checkpoint inspection
- Connect page with OTLP and SDK setup snippets

The build in `dist/` is bundled into the Python wheel (see `setup.py`), so commit it after changing the UI.

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

Screenshots are written to `dashboard/screenshots/`: Overview, Trace Detail cockpit, Sessions, Trace Insights, Workflow Graph, Cost Center, Replay Studio, Connect, Datasets & Experiments, Experiment Compare, and Alerts. The script needs Chrome or Edge (set `CHROME_PATH` if it is not found) and the seeded demo data, which includes the multi-turn support session used for the Sessions and Insights shots and the experiments and alert rules for the evaluation and alert shots.
