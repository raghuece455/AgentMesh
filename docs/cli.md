# CLI Reference

The `agentmesh` CLI is the command-line interface for managing workflows, traces, costs, and the dashboard.

---

## Installation

The CLI is installed automatically when you install AgentMesh:

```bash
pip install -e .
agentmesh --help
```

---

## Global Options

```bash
agentmesh --db <path-or-dsn>   # override the database (SQLite path or PostgreSQL DSN)
agentmesh --help               # show help for any command
agentmesh version              # print the installed version
```

---

## Dashboard

```bash
agentmesh dashboard                              # start at 127.0.0.1:8787
agentmesh dashboard --host 0.0.0.0 --port 9000  # custom host and port
```

---

## Demo Data

```bash
agentmesh demo seed            # seed demo traces (keeps existing data)
agentmesh demo seed --reset    # clear the database first, then seed
```

---

## Traces

```bash
agentmesh traces list                            # list recent traces
agentmesh traces show <trace_id>                 # full detail: spans, events, cost
agentmesh traces export <trace_id> --out trace.json
agentmesh traces export <trace_id> --format otel-json --out trace.otel.json
agentmesh traces insights <trace_id>             # root cause, loops, context growth, hotspots
agentmesh traces prune --older-than 30d --dry-run
agentmesh traces prune --older-than 30d --vacuum # delete and reclaim disk space
agentmesh ingest trace.otlp.json                 # import an OTLP/JSON ExportTraceServiceRequest
```

---

## Sessions

```bash
agentmesh sessions list [--limit 20] [--user-id u-7]
agentmesh sessions show <session_id>
```

---

## MCP Server

```bash
agentmesh --db /absolute/path/agentmesh.db mcp   # stdio; register it with your MCP client
```

See [mcp.md](mcp.md).

---

## Pricing

```bash
agentmesh pricing show claude-sonnet-5 [--provider anthropic]
agentmesh pricing list
agentmesh pricing sync [--url URL] [--out PATH]  # download the LiteLLM community price list
```

---

## Replay

```bash
agentmesh replay <trace_id> --mode deterministic            # exact reproduction, no API calls
agentmesh replay <trace_id> --mode simulated                # mock outputs, no API calls
agentmesh replay <trace_id> --mode live --allow-side-effects  # real API calls
agentmesh replay <trace_id> --from-span <span_id> --mode deterministic
```

---

## Checkpoints

```bash
agentmesh checkpoints list <trace_id>                       # list all checkpoints for a trace
agentmesh checkpoints show <checkpoint_id>                   # inspect memory state
agentmesh checkpoints patch-memory <checkpoint_id> \
  --set '{"key": "new-value"}'                              # patch memory, then replay
```

---

## Diagnosis

```bash
agentmesh diagnose <trace_id>    # classify errors, retries, and budget events
```

---

## Costs

```bash
agentmesh costs summary                       # total spend summary
agentmesh costs summary --dimension model     # break down by model
agentmesh costs summary --dimension agent     # break down by agent
agentmesh costs summary --dimension workflow  # break down by workflow
```

---

## Datasets and Experiments

```bash
agentmesh datasets list
agentmesh datasets create support-regressions --description "Approved answers"
agentmesh datasets add support-regressions --input '{"question": "Do you ship to Canada?"}' --expected "Yes, in 4-7 days"
agentmesh datasets add-trace support-regressions <trace_id> [--span-id <span_id>] [--no-expected]
agentmesh datasets import support-regressions items.jsonl     # JSONL or a JSON array of {"input", "expected", "metadata"}
agentmesh datasets export support-regressions --out items.jsonl
agentmesh datasets show support-regressions
agentmesh datasets delete support-regressions

agentmesh experiments list [--dataset support-regressions]
agentmesh experiments show <experiment_id>
agentmesh experiments compare <baseline_id> <candidate_id>
agentmesh experiments run --dataset support-regressions --task app/agent.py:answer \
  --evaluator exact_match --evaluator contains --evaluator app/evals.py:tone_judge \
  --fail-under exact_match=0.9 --baseline <experiment_id> --fail-on-regression [--json] [--endpoint URL]
```

`experiments run` exits with status 1 when a mean score is below `--fail-under` or, with `--fail-on-regression`, when any item regressed against `--baseline`. See [datasets-and-experiments.md](datasets-and-experiments.md).

---

## Alerts

```bash
agentmesh alerts add --name "checkout failures" --kind failure_rate --threshold 0.2 --window 15m \
  --workflow checkout --webhook https://hooks.slack.com/services/... [--format slack|discord|json] [--secret S]
agentmesh alerts list
agentmesh alerts update "checkout failures" --threshold 0.3 [--window 30m] [--cooldown 1h] [--enable|--disable]
agentmesh alerts test "checkout failures"      # send a test notification
agentmesh alerts check [--no-deliver]           # evaluate every rule once
agentmesh alerts history [--rule NAME]
agentmesh alerts remove "checkout failures"
```

Kinds: `failure_rate`, `failure_count`, `cost`, `trace_cost`, `latency_p95`, `loop_detected`. See [alerts.md](alerts.md).

---

## Health and Validation

```bash
agentmesh doctor                  # check environment, database, and dashboard build
agentmesh validate traces         # validate trace data integrity
agentmesh validate traces --json  # output validation results as JSON
```

---

## Run an Example

```bash
agentmesh run examples/hello_agent.py
agentmesh run examples/researcher_writer_reviewer.py
```

---

## Using PostgreSQL

Any command accepts `--db` with a PostgreSQL DSN:

```bash
agentmesh --db postgresql://agentmesh:password@localhost:5432/agentmesh traces list
agentmesh --db postgresql://agentmesh:password@localhost:5432/agentmesh dashboard
```

Or set the environment variable:

```bash
export AGENTMESH_DB_URL=postgresql://agentmesh:password@localhost:5432/agentmesh
agentmesh traces list
```
