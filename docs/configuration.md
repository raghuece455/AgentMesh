# Configuration

AgentMesh reads configuration from environment variables. Set them in a `.env` file (auto-loaded if `python-dotenv` is installed) or export them in your shell.

```bash
pip install -e ".[dotenv]"   # enables .env auto-loading
```

---

## Core Settings

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_DB_URL` | `.agentmesh/agentmesh.db` | SQLite file path or PostgreSQL DSN (`postgresql://user:pass@host/db`) |
| `AGENTMESH_HOST` | `127.0.0.1` | Dashboard bind host |
| `AGENTMESH_PORT` | `8787` | Dashboard port |
| `AGENTMESH_AUTH_MODE` | `none` | `none` for open local access; `api_key` to require a bearer token |
| `AGENTMESH_API_KEY` | _(unset)_ | Required when `AGENTMESH_AUTH_MODE=api_key` |

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
| `AGENTMESH_PRICING_JSON` | _(unset)_ | JSON string or path to a JSON file overriding built-in model pricing |

Pricing JSON format:
```json
{
  "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
  "claude-3-5-sonnet-20241022": {"prompt": 0.003, "completion": 0.015}
}
```
Units: USD per 1,000 tokens.

---

## Observability

| Variable | Default | Description |
|---|---|---|
| `AGENTMESH_OTEL_ENABLED` | `false` | Enable OpenTelemetry setup in user code |
| `AGENTMESH_OTEL_ENDPOINT` | _(unset)_ | OTLP collector endpoint (planned — not yet active in v0.3.0) |

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

Switch from SQLite to PostgreSQL by changing `AGENTMESH_DB_URL`:

```dotenv
AGENTMESH_DB_URL=postgresql://agentmesh:secret@localhost:5432/agentmesh
```

Install the PostgreSQL adapter:

```bash
pip install -e ".[postgres]"
```

See [production_stack.md](production_stack.md) for a full PostgreSQL + Redis + NATS setup.

---

## CLI Flags

Most settings can also be passed as CLI flags, which override environment variables:

```bash
agentmesh dashboard --host 0.0.0.0 --port 9000
agentmesh traces list --db postgresql://user:pass@host/db
```

Run `agentmesh --help` or `agentmesh <command> --help` to see all available flags.
