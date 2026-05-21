# Production Stack

AgentMesh keeps the default install lightweight and enables production infrastructure through optional extras.

## Packaging With uv

The project is configured through `pyproject.toml` and is compatible with uv:

```bash
uv sync --extra production
uv run pytest
uv run agentmesh dashboard
```

`pip install -e .` remains supported for local development.

## Messaging

Default local workflows use `AsyncEventBus`.

Install Redis support:

```bash
pip install -e ".[redis]"
```

Use `RedisEventBus` for Redis pub/sub.

Install NATS support:

```bash
pip install -e ".[nats]"
```

Use `NATSEventBus` for NATS subjects.

## Persistence

SQLite is the default:

```python
from agentmesh import SQLiteStore
```

PostgreSQL is available through:

```bash
pip install -e ".[postgres]"
```

```python
from agentmesh import PostgreSQLStore

store = PostgreSQLStore("postgresql://agentmesh@localhost:5432/agentmesh")
```

The CLI and dashboard accept PostgreSQL DSNs:

```bash
agentmesh --db postgresql://agentmesh@localhost:5432/agentmesh dashboard
```

## Vector Search

FAISS support is available through:

```bash
pip install -e ".[faiss]"
```

```python
from agentmesh import FAISSVectorStore, RetrievalEngine

retriever = RetrievalEngine(FAISSVectorStore(dimensions=64))
```

## OpenTelemetry

Install OTEL support:

```bash
pip install -e ".[otel]"
```

```python
from agentmesh import TraceRecorder, SQLiteStore, configure_opentelemetry

otel = configure_opentelemetry(
    service_name="agentmesh",
    otlp_endpoint="http://localhost:4318/v1/traces",
)
recorder = TraceRecorder(SQLiteStore(), otel=otel)
```

## Docker

`docker-compose.yml` includes:

- AgentMesh dashboard
- PostgreSQL
- Redis
- NATS
- OpenTelemetry Collector

```bash
docker compose up --build
```
