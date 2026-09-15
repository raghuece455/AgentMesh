# Docker

AgentMesh ships a Docker Compose file for one-command local setup. It builds the React dashboard, starts the FastAPI server, seeds demo data, and exposes everything at `http://127.0.0.1:8787`.

---

## Quick Start

```bash
docker compose up --build
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Demo data is seeded automatically on first run.

---

## What the Compose File Does

1. Builds the React dashboard (`dashboard/`) into `dashboard/dist/`
2. Installs AgentMesh with the `otlp` and `postgres` extras, so the OTLP receiver accepts protobuf as well as JSON and PostgreSQL works without rebuilding
3. Starts the dashboard server (UI, REST API, and `POST /v1/traces`)
4. Mounts a named Docker volume for the SQLite database (data persists across restarts); `docker-compose.postgres.yml` switches to PostgreSQL
5. Seeds demo traces on start (`AGENTMESH_DEMO_SEED=true`; this resets the database each start)
6. Publishes port `8787` on `127.0.0.1` only

## Sending Traces to the Container

From your host, point any OpenTelemetry exporter or the AgentMesh SDK at the container:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:8787"   # OpenTelemetry frameworks
export AGENTMESH_ENDPOINT="http://127.0.0.1:8787"            # AgentMesh Python SDK
```

From another container on the same Compose network, use `http://dashboard:8787`. See [integrations.md](integrations.md).

---

## Skipping Demo Data

Demo seeding resets the database on every start. To keep your own traces, turn it off:

```bash
AGENTMESH_DEMO_SEED=false docker compose up
```

On Windows PowerShell:

```powershell
$env:AGENTMESH_DEMO_SEED = "false"
docker compose up
```

---

## Environment Variables in Docker

`docker-compose.yml` reads these from your shell or from a `.env` file next to it:

| Variable | Default | Purpose |
|---|---|---|
| `AGENTMESH_DEMO_SEED` | `true` | Reset and seed demo data on start |
| `AGENTMESH_AUTH_MODE` | `none` | `api_key` to require a key for the UI, REST API, and `/v1/traces` |
| `AGENTMESH_API_KEY` | _(empty)_ | The key clients send as `Authorization: Bearer <key>` |
| `AGENTMESH_CAPTURE_CONTENT` | `true` | `false` stores usage, cost, and timing without prompt/response text |
| `AGENTMESH_MAX_OTLP_BYTES` | `33554432` | Largest accepted `/v1/traces` body (32 MiB) |
| `AGENTMESH_DB_URL` | `/data/agentmesh.db` | SQLite path on the volume, or a PostgreSQL DSN |
| `AGENTMESH_ALERT_INTERVAL_SECONDS` | `60` | Alert rule check interval; `0` disables the scheduler |
| `AGENTMESH_PUBLIC_URL` | _(empty)_ | External dashboard URL used for links in alert notifications |

```dotenv
# .env
AGENTMESH_DEMO_SEED=false
AGENTMESH_AUTH_MODE=api_key
AGENTMESH_API_KEY=change-me-to-a-long-random-string
```

When auth is on, the dashboard asks for the key once and keeps it in that browser.

## Exposing the Dashboard Beyond Localhost

The port is published on `127.0.0.1` because auth is off by default. To reach it from other machines, set `AGENTMESH_AUTH_MODE=api_key` and `AGENTMESH_API_KEY`, change the mapping in `docker-compose.yml` from `"127.0.0.1:8787:8787"` to `"8787:8787"`, and put a TLS-terminating reverse proxy (nginx, Caddy, Traefik) in front of it.

---

## PostgreSQL

The default Compose file keeps traces in SQLite on a Docker volume. To run AgentMesh on PostgreSQL instead, add the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

It starts `postgres:17` with a persistent volume, sets `AGENTMESH_DB_URL` for the dashboard, and turns demo seeding off so restarts keep your data (set `AGENTMESH_DEMO_SEED=true` to load the demo, which clears the database). Change `POSTGRES_PASSWORD` (and the password in `AGENTMESH_DB_URL`) before using it beyond your machine. To use an existing database, set `AGENTMESH_DB_URL=postgresql://...` in `.env` with the base Compose file. See [configuration.md](configuration.md#postgresql).

---

## Rebuilding After Code Changes

```bash
docker compose up --build
```

The `--build` flag rebuilds the image. Omit it to reuse the cached image.

---

## Production Stack

The default Compose file is for local development only. A production-ready stack with PostgreSQL, Redis, NATS, FAISS, and an OpenTelemetry collector is described in [production_stack.md](production_stack.md).

> **Note:** The default Compose file is a single-container setup: SQLite, published on localhost, auth off, no TLS. Enable API-key auth and add a TLS reverse proxy before sharing it with a team.

---

## Health Checks

The container exposes two health endpoints:

```bash
curl http://127.0.0.1:8787/healthz   # → {"status": "ok"}
curl http://127.0.0.1:8787/readyz    # → {"status": "ready"}
```

These are used by the Docker health check configuration in `docker-compose.yml`.
