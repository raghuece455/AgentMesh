# AgentMesh Dashboard

The production dashboard app is served by `agentmesh.dashboard:create_app`.

This directory contains a React + Tailwind frontend for:

- Overview with KPI sparklines, trace volume and latency charts, grouped issues, and provider health
- Trace explorer and trace view: span tree and waterfall in one timeline, a span panel with chat-style input/output, and automatic insights
- Sessions (multi-turn conversations) and scores/feedback
- Datasets & experiments: per-evaluator scores and item-by-item comparisons; Add to dataset on traces
- Alerts: rules, test notifications, and alert history
- Workflow graph, agents, models, tools, memory & RAG, prompts, evaluations, and approvals
- Cost analytics and replay
- Connect page with OTLP and SDK setup snippets

The UI has a grouped sidebar, a global time range and data scope, a Ctrl/⌘ K command palette, and light and dark themes. Shared building blocks live in `src/components/ui` (buttons, badges, cards, stat cards, tables, tabs, drawers, menus, code and JSON viewers) and use the color tokens defined in `src/index.css`, so new pages match both themes without extra work.

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

The smoke test checks the Overview (KPIs, trace volume, issues, spend by model, recent traces, providers), the Traces list, opening a trace (insights, timeline, events, span panel tabs), the Export menu, Costs, and running a replay.

## README Screenshots

With the dashboard running against seeded demo data:

```bash
python -m agentmesh.cli demo seed --reset
python -m agentmesh.cli dashboard
AGENTMESH_DASHBOARD_URL=http://127.0.0.1:8790 npm run screenshots
```

Screenshots are written to `dashboard/screenshots/` in the dark theme (set `AGENTMESH_SCREENSHOT_THEME=light` for light): Overview, Trace detail, Sessions, Trace insights, Workflow graph, Costs, Replay, Connect, Datasets & experiments, Experiment compare, and Alerts. The script needs Chrome or Edge (set `CHROME_PATH` if it is not found) and the seeded demo data, which includes the multi-turn support session used for the Sessions and Insights shots and the experiments and alert rules for the evaluation and alert shots.
