# MCP server: let your coding agent debug your agents

AgentMesh ships a [Model Context Protocol](https://modelcontextprotocol.io) server so Claude Code,
Cursor, VS Code, or any MCP client can read your traces directly:

> "Why did the last support-bot run fail?"
> "Which model call cost the most today?"
> "Is the planner stuck in a loop on trace 4ecd04d1...?"

It runs locally over stdio, reads the same database as the dashboard, and needs no extra packages.

```bash
agentmesh mcp --db /absolute/path/to/.agentmesh/agentmesh.db
```

## Setup

**Claude Code**

```bash
claude mcp add agentmesh -- agentmesh mcp --db /absolute/path/to/.agentmesh/agentmesh.db
```

**Cursor / VS Code / other clients** (JSON config)

```json
{
  "mcpServers": {
    "agentmesh": {
      "command": "agentmesh",
      "args": ["mcp", "--db", "/absolute/path/to/.agentmesh/agentmesh.db"]
    }
  }
}
```

If `agentmesh` is installed in a virtual environment, use the full path to that environment's
`agentmesh` executable (or `python -m agentmesh.cli`). You can also set `AGENTMESH_DB_URL`
instead of passing `--db`.

## Tools

| Tool | What it returns |
|---|---|
| `list_traces` | Recent traces with status, duration, tokens, cost, session and error. Filters: `status`, `workflow`, `session_id`, `user_id`, `query`. |
| `get_trace` | A compact span tree (depth, name, type, status, duration, model, tokens, cost, errors). `include_content=true` adds truncated inputs/outputs. |
| `get_span` | Full detail of one span, including prompt messages, output, tool arguments/results and attributes |
| `diagnose_trace` | Automatic insights: first failure (root cause) with its path, tool-call loops, repeated identical prompts, context-window growth, prompt-cache hit rate, unpriced models, self-time hotspots, costliest calls |
| `search_spans` | Search across all traces by text (span name, error message, tool, model, agent), status and category |
| `cost_summary` | Totals, optionally grouped by model, provider, agent or workflow |
| `list_sessions` / `get_session` | Multi-turn conversations and every turn's input, output and scores |
| `list_experiments` | Experiments on a dataset with mean scores, pass rates and errors |
| `compare_experiments` | What changed between two experiments: regressed and improved items with both outputs, score deltas, cost change |
| `list_alerts` | Alert rules with their firing state, and recent alert notifications |
| `add_score` | Record a verdict on a trace after reviewing it (the only tool that writes) |

Read-only tools are annotated with `readOnlyHint` so clients can auto-approve them.
Large values are truncated with a note telling the model how to fetch more.

Supported protocol versions: `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`.
