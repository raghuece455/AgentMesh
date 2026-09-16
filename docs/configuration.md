# Configuration

AgentMesh reads configuration from environment variables. Set them in a `.env` file (auto-loaded if `python-dotenv` is installed) or export them in your shell.

```bash
pip install -e ".[dotenv]"   # enables .env auto-loading
```

---

## Core Settings

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_DB_URL` | `.agentmesh/agentmesh.db` | SQLite file path (or `sqlite:///path`) or PostgreSQL DSN (`postgresql://user:pass@host/db`) |
| `AGENTMESH_HOST` | `127.0.0.1` | Dashboard bind host |
| `AGENTMESH_PORT` | `8787` | Dashboard port |
| `AGENTMESH_AUTH_MODE` | `none` | `none` for open local access; `api_key` to require a bearer token |
| `AGENTMESH_API_KEY` | _(unset)_ | Required when `AGENTMESH_AUTH_MODE=api_key` |
| `AGENTMESH_DASHBOARD_DIR` | _(unset)_ | Serve a dashboard build from this directory (must contain `index.html`). By default a source checkout's `dashboard/dist` is used, then the copy bundled in the wheel. |

---

## Model Provider Keys

| Variable | Provider |
|---|---|
| `OPENAI_API_KEY` | OpenAI (also Azure OpenAI) |
| `OPENAI_BASE_URL` | OpenAI-compatible base URL (default: `https://api.openai.com/v1`) |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` | Google Gemini |
| `OLLAMA_HOST` | Ollama server (default: `http://localhost:11434`) |
| `VLLM_BASE_URL` | vLLM server (default: `http://localhost:8000/v1`) |

---

## Cost and Pricing

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_PRICING_JSON` | _(unset)_ | Price overrides: inline JSON or a path to a JSON file (see [cost-tracking.md](cost-tracking.md)) |
| `AGENTMESH_PRICING_FILE` | `.agentmesh/pricing.json` | Where `agentmesh pricing sync` writes community prices, and where they are read from |

Override format (USD per million tokens):
```json
[{"provider": "*", "model": "my-finetune", "input_per_mtok": 3.0, "output_per_mtok": 12.0, "cache_read_per_mtok": 0.3}]
```

---

## Ingestion and Privacy (server)

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_CAPTURE_CONTENT` | `true` | `false` drops prompts, completions, tool arguments/results and document text at ingest; usage, cost, timing and errors are kept |
| `AGENTMESH_MAX_CONTENT_CHARS` | `100000` | Maximum stored characters per content field |
| `AGENTMESH_MAX_OTLP_BYTES` | `33554432` (32 MiB) | Largest `/v1/traces` request body, before and after gzip/deflate decompression; larger requests get `413` |

## Tracing SDK (your application)

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_ENDPOINT` | _(unset)_ | Send spans to a remote AgentMesh server instead of a local database |
| `AGENTMESH_API_KEY` | _(unset)_ | Bearer token for that server |
| `AGENTMESH_SERVICE_NAME` | `agentmesh-app` | Service name on every trace (falls back to `OTEL_SERVICE_NAME`) |
| `AGENTMESH_ENVIRONMENT` | _(unset)_ | Environment label, e.g. `prod` |
| `AGENTMESH_TRACING_ENABLED` | `true` | `false` makes all SDK spans no-ops |

See [sdk.md](sdk.md) and [integrations.md](integrations.md).

---

## Alerts

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_ALERT_INTERVAL_SECONDS` | `60` | How often the server evaluates alert rules; `0` turns the scheduler off (use `agentmesh alerts check` instead) |
| `AGENTMESH_PUBLIC_URL` | _(unset)_ | The dashboard's external URL, e.g. `https://agentmesh.example.com`; alert notifications then link to the offending traces |

See [alerts.md](alerts.md).

---

## Swarms

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_SWARM_ID` | _(unset)_ | Put every trace this process starts into this swarm (for workers launched per swarm) |
| `AGENTMESH_SWARM_NAME` | _(unset)_ | Display name for that swarm |

See [swarms.md](swarms.md).

---

## Guardrails

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_GUARDRAILS` | `true` | Enforce guardrail policies and halts in this process |
| `AGENTMESH_POLICY_FILE` | _(unset)_ | Policy files to enforce in addition to saved policies, separated by `;` (Windows) or `:` |
| `AGENTMESH_GUARDRAILS_REFRESH_SECONDS` | `5` | How often policies and halts are reloaded from the database or server |
| `AGENTMESH_GUARDRAILS_FAIL_CLOSED` | `false` | Deny every call while no policies could be loaded |

See [guardrails.md](guardrails.md).

---

## Observability

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_OTEL_ENABLED` | `false` | Enable OpenTelemetry setup in user code |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(unset)_ | Set this **in your agent app** to `http://<agentmesh-host>:8787` to export OpenTelemetry traces into AgentMesh |

---

## Demo and Development

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_DEMO_SEED` | `true` | Whether the Docker image seeds demo data on first start |
| `AGENTMESH_LOG_LEVEL` | `info` | Log verbosity: `debug`, `info`, `warning`, `error` |

---

## Example `.env` File

```dotenv
# Core
AGENTMESH_DB_URL=.agentmesh/agentmesh.db
AGENTMESH_HOST=127.0.0.1
AGENTMESH_PORT=8787

# Auth (comment out for open local access)
# AGENTMESH_AUTH_MODE=api_key
# AGENTMESH_API_KEY=change-me

# Model providers
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
OLLAMA_HOST=http://localhost:11434

# Cost overrides
AGENTMESH_PRICING_JSON=./pricing.json
```

---

## PostgreSQL

Switch from SQLite to PostgreSQL (14 or newer) by changing `AGENTMESH_DB_URL`:

```dotenv
AGENTMESH_DB_URL=postgresql://agentmesh:secret@localhost:5432/agentmesh
```

Install the driver:

```bash
pip install "agentmesh-ai[postgres]"
```

Every feature works on PostgreSQL: OTLP and SDK ingestion, sessions, scores, insights, datasets, experiments, alerts, the runtime, replay, and the MCP server. Tables are created on first connect. Point the dashboard, the CLI, the Python SDK (`agentmesh.init(db_path="postgresql://...")`), and `agentmesh mcp` at the same DSN.

Notes:

- AgentMesh does not use server-side prepared statements, so it works behind transaction-pooling proxies such as PgBouncer and the Supabase and Neon poolers.
- Each store holds one connection; the dashboard serializes database access within a process. Run more server replicas for more throughput, with the alert scheduler enabled on only one of them.
- Databases created by the pre-0.4 PostgreSQL adapter are upgraded in place: `jsonb` columns in AgentMesh's own tables become `text` and the foreign keys on `events` and `checkpoints` are dropped (SQLite never enforced them). Other tables in the database are never modified.
- Switching databases does not copy existing traces; start the new database fresh, or re-send traces to it.

See [production_stack.md](production_stack.md) for a full PostgreSQL + Redis + NATS setup.

---

## CLI Flags

Most settings can also be passed as CLI flags, which override environment variables:

```bash
agentmesh dashboard --host 0.0.0.0 --port 9000
agentmesh traces list --db postgresql://user:pass@host/db
```

Run `agentmesh --help` or `agentmesh <command> --help` to see all available flags.
