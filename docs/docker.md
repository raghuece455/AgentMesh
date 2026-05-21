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
2. Starts the FastAPI server with uvicorn
3. Mounts a named Docker volume for the SQLite database (data persists across restarts)
4. Seeds demo traces on first start (`AGENTMESH_DEMO_SEED=true`)
5. Exposes port `8787` to the host

---

## Skipping Demo Data

To preserve existing data and skip re-seeding:

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

Pass configuration to the container via the `environment` section of `docker-compose.yml`, or with `-e` flags:

```bash
docker compose up -e AGENTMESH_AUTH_MODE=api_key -e AGENTMESH_API_KEY=my-secret
```

Or add a `.env` file and Docker Compose picks it up automatically:

```dotenv
AGENTMESH_AUTH_MODE=api_key
AGENTMESH_API_KEY=my-secret
OPENAI_API_KEY=sk-...
```

---

## Connecting to PostgreSQL

Override `AGENTMESH_DB_URL` to use PostgreSQL instead of SQLite:

```bash
docker compose up -e AGENTMESH_DB_URL=postgresql://user:pass@host:5432/agentmesh
```

Install the PostgreSQL extra:

```bash
pip install -e ".[postgres]"
```

---

## Rebuilding After Code Changes

```bash
docker compose up --build
```

The `--build` flag rebuilds the image. Omit it to reuse the cached image.

---

## Production Stack

The default Compose file is for local development only. A production-ready stack with PostgreSQL, Redis, NATS, FAISS, and an OpenTelemetry collector is described in [production_stack.md](production_stack.md).

> **Note:** Do not use the default Compose file as a production deployment. It uses SQLite, binds to localhost, and does not include authentication or TLS.

---

## Health Checks

The container exposes two health endpoints:

```bash
curl http://127.0.0.1:8787/healthz   # → {"status": "ok"}
curl http://127.0.0.1:8787/readyz    # → {"status": "ready"}
```

These are used by the Docker health check configuration in `docker-compose.yml`.
