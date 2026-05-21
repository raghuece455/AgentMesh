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
