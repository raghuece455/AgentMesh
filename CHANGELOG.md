# Changelog

All notable changes to AgentMesh are documented here. AgentMesh follows [Semantic Versioning](https://semver.org/) and this file follows [Keep a Changelog](https://keepachangelog.com/).

---

## [Unreleased]

Nothing yet.

---

## [0.4.1] — 2026-09-15

A packaging and release-process update. No changes to the Python package or TypeScript SDK code.

### Changed
- The PyPI project page no longer says to install from a clone until 0.4.0 is published, and mentions the `postgres` extra.
- The Release workflow now also publishes `agentmesh-sdk` to npm with trusted publishing (OIDC, no stored token, with provenance). It skips when the SDK version is already on npm and fails when the tag and SDK version disagree. `CONTRIBUTING.md` documents the release steps.
- `agentmesh-sdk` 0.4.1 is the first npm release published by the workflow; the dashboard and SDK versions follow the Python package.

---

## [0.4.0] — 2026-09-14

AgentMesh becomes framework-agnostic: observe agents built with anything, not only the AgentMesh runtime, test changes with datasets and experiments, get alerted, and run on PostgreSQL.

### Added
- **Datasets and experiments** (`agentmesh.datasets`, `agentmesh.experiments`): datasets from traces (dashboard **Add to dataset**, `add_trace_to_dataset`), JSONL, or by hand; `agentmesh.run_experiment` / `arun_experiment` run any sync or async task over a dataset with each item in its own trace; item-by-item `compare_experiments` (regressions, improvements, score/cost/latency deltas). Works against the local database or a remote server. REST API under `/api/datasets` and `/api/experiments`; CLI `agentmesh datasets ...` and `agentmesh experiments list|show|compare|run` with `--fail-under` and `--fail-on-regression` for CI.
- **Evaluators** (`agentmesh.evaluators`): `ExactMatch`, `Contains`, `RegexMatch`, `JSONValid`, `Similarity`, `@evaluator` for custom functions, and **`LLMJudge`** (any judge function or `ModelProvider`; presets for correctness, helpfulness, conciseness, faithfulness, harmlessness; score scales and thresholds; robust reply parsing). `agentmesh.evaluate_traces` scores recorded production traces.
- **Alerts** (`agentmesh.alerts`): rules for failure rate, failed runs, spend, expensive traces, p95 latency, and tool loops, with workflow/environment/service/source filters, windows, cooldowns, reminders, and resolved notifications. Delivery to Slack, Discord, or JSON webhooks with optional HMAC-SHA256 signatures. A background scheduler in the server (`AGENTMESH_ALERT_INTERVAL_SECONDS`), `/api/alerts/*`, and `agentmesh alerts add|list|update|remove|check|test|history`.
- **TypeScript SDK** (`sdks/typescript`, npm `agentmesh-sdk`): `init`, `observe`, `trace`, `span`, `startSpan`/`withActiveSpan`, `score`, `updateCurrentTrace`; OTLP/JSON exporter with batching and retries; `instrumentOpenAI` (Chat Completions, Responses, Embeddings, streaming, `.withResponse()`) and `instrumentAnthropic` (`messages.create`, `stream: true`, `messages.stream()`); `runExperiment` with `exactMatch`, `contains`, and `llmJudge`. ESM and CommonJS builds, Node.js 18+, no runtime dependencies.
- **PostgreSQL for every feature.** `PostgreSQLStore` now shares all queries with the SQLite store through a dialect-translating connection adapter, so OTLP/SDK ingestion, sessions, scores, insights, datasets, experiments, alerts, the runtime, and the MCP server work on `postgresql://` URLs. Works behind PgBouncer-style poolers (no server-side prepared statements). The test suite runs every storage test against both databases when `AGENTMESH_TEST_POSTGRES_URL` is set; CI runs it on PostgreSQL 17. `docker-compose.postgres.yml` runs the stack on PostgreSQL.
- Dashboard: **Datasets & Evals** page (datasets, items, experiments with per-evaluator scores, experiment detail, and comparison), **Alerts** page (rules, create/test/enable, history), **Add to dataset** on trace detail, a TypeScript snippet on **Connect**, and deep links (`/?trace=<id>`, `/?page=datasets&experiment=<id>`).
- MCP tools `list_experiments`, `compare_experiments`, and `list_alerts`.
- Demo data now includes a support dataset, two experiment runs with an LLM-judge-style evaluator, and alert rules; screenshots add `datasets-experiments.png`, `experiment-compare.png`, and `alerts.png`.
- Docs: `docs/datasets-and-experiments.md`, `docs/alerts.md`, `docs/typescript-sdk.md`; `docs/evaluations.md` rewritten to match the API. Example: `examples/datasets_experiments.py`; TypeScript examples in `sdks/typescript/examples`.
- **OTLP/HTTP trace receiver** at `POST /v1/traces` (JSON always; protobuf with the new `otlp` extra; gzip/deflate bodies). Any OpenTelemetry exporter or Collector can send traces to AgentMesh.
- **Semantic mapping** (`agentmesh.ingest`) for the OpenTelemetry GenAI conventions (including `gen_ai.usage.cache_read/cache_write.input_tokens`, `gen_ai.usage.reasoning.output_tokens`, `gen_ai.conversation.id`, agent/tool/workflow/retrieval/memory operations, `gen_ai.evaluation.result` events, MCP spans), OpenInference, OpenLLMetry/Traceloop, and Vercel AI SDK attributes. Out-of-order batches and re-delivery are handled idempotently; aggregate wrapper spans are never double-counted.
- **Python tracing SDK** (`agentmesh.sdk`, re-exported at top level): `init`, `@observe` (sync, async, generators), `trace`, `span`, `score`, `update_current_trace`, `flush`; local-SQLite and HTTP (OTLP/JSON) exporters with a background batch processor; `InMemoryExporter` for tests.
- **Auto-instrumentation** for the `openai` client (Chat Completions, Responses, Embeddings; sync/async; streaming with tool-call accumulation) and the `anthropic` client (`messages.create`, `stream=True`, `messages.stream()`; Bedrock/Vertex provider detection; cache token normalization).
- **Sessions, users, and tags** on traces; `GET /api/sessions`, `GET /api/sessions/{id}`, `session_id`/`user_id`/`tag`/`source` trace filters; `agentmesh sessions list|show`.
- **Scores and feedback**: `POST /api/scores`, `GET /api/scores`, `GET /api/traces/{id}/scores`, SDK `score()`, dashboard thumbs up/down.
- **Automatic trace insights** (`agentmesh.analysis`): first failure with causal path, tool-call loops, repeated identical prompts, context-window growth, prompt-cache hit rate, unpriced models, self-time and cost hotspots. `GET /api/traces/{id}/insights`, `agentmesh traces insights`.
- **MCP server** (`agentmesh mcp`, stdio, no extra dependencies) with `list_traces`, `get_trace`, `get_span`, `diagnose_trace`, `search_spans`, `cost_summary`, `list_sessions`, `get_session`, `add_score`.
- **Retention**: `agentmesh traces prune --older-than 30d [--dry-run] [--vacuum]`.
- **Privacy controls**: `AGENTMESH_CAPTURE_CONTENT=false`, `AGENTMESH_MAX_CONTENT_CHARS`, SDK `capture_content=False`.
- `agentmesh ingest <file>` for OTLP/JSON trace files; `GET /api/integrations`; `GET /api/pricing`.
- Dashboard: **Sessions** page, **Connect** page (endpoint + setup snippets), Insights & Scores panel, span names in the span tree and waterfall, session/user/source/tag badges.
- Dashboard works with API-key auth: it prompts for the key on `401`, keeps it in the browser, and sends it on every request and on the live event stream (now read with `fetch` instead of `EventSource`, which cannot send headers).
- `AGENTMESH_MAX_OTLP_BYTES` (default 32 MiB) limits `/v1/traces` request bodies before and after decompression; oversized requests get `413`.
- Demo data now includes a three-turn OpenTelemetry-style support session with a tool loop.
- Docs: `docs/integrations.md`, `docs/sdk.md`, `docs/mcp.md`, a rewritten `docs/opentelemetry.md`, and a new "any framework" section in `HOW_IT_WORKS.md`. Examples: `sdk_quickstart.py`, `otel_genai_export.py`, `llm_client_auto_instrumentation.py`.
- README: architecture diagram, FAQ, and a refreshed screenshot gallery including the new Sessions, Trace Insights, and Connect pages (`npm run screenshots` now captures all eight).

### Changed
- **Pricing rewritten** to USD per million tokens with separate cache-read and cache-write rates. Built-in prices for current Claude models (Fable 5.1, Fable 5, Opus 5, Opus 4.5–4.8, Sonnet 5, Sonnet 4.x, Haiku 4.5) from Anthropic's pricing page, Gemini 2.5, and common OpenAI models. Model IDs are normalized (dated snapshots, Bedrock and Vertex IDs). New `agentmesh pricing sync|show|list` and `AGENTMESH_PRICING_FILE`. The v0.3 `*_per_1k` override format and the documented `{"model": {"prompt": ..., "completion": ...}}` shorthand are still accepted, and `AGENTMESH_PRICING_JSON` may now be a file path.
- Token semantics follow the GenAI conventions: prompt tokens include cached tokens; completion tokens include reasoning tokens. The Anthropic and OpenAI-compatible providers now report cache tokens.
- `AnthropicProvider` default model is now `claude-sonnet-5`.
- Claude 4.6+ models report a 1M-token context window.
- API auth accepts `X-AgentMesh-Api-Key` in addition to `Authorization: Bearer`, and compares keys in constant time.
- The CLI `--db` default honours `AGENTMESH_DB_URL`.
- Provider catalog no longer labels the implemented Anthropic, Gemini, Azure OpenAI and vLLM adapters as "planned".
- **`docker-compose.yml` publishes port 8787 on `127.0.0.1` only** and passes `AGENTMESH_AUTH_MODE`, `AGENTMESH_API_KEY`, `AGENTMESH_CAPTURE_CONTENT`, and `AGENTMESH_MAX_OTLP_BYTES` through from `.env`. If you reached the container from another machine, set an API key and change the port mapping (see `docs/docker.md`).
- The evaluation summary averages only 0–1 scores as task success and computes the pass rate over records with an explicit pass/fail, so arbitrary-scale scores no longer distort it.
- **PostgreSQL databases created by the previous adapter are migrated on first connect:** `jsonb` columns in AgentMesh's own tables become `text`, and the foreign keys on `events` and `checkpoints` are dropped to match SQLite. Other applications' tables in the same database are left untouched.
- `POST /api/scores` accepts `passed`. Docker Compose reads `AGENTMESH_DB_URL` (default: the SQLite volume) and passes the alert settings through; the image installs the `postgres` extra.
- `GET /api/overview` and `/api/providers/health` commit the provider-health refresh they perform, instead of leaving a write transaction open until the next write.

### Packaging
- **The PyPI wheel now ships the React dashboard.** A `setup.py` build hook copies `dashboard/dist` into the wheel as `agentmesh/dashboard_dist`, and `MANIFEST.in` carries it through the sdist. Previously `pip install agentmesh-ai` only served the minimal fallback page because the dashboard was looked up relative to a source checkout.
- The server resolves the dashboard from `AGENTMESH_DASHBOARD_DIR`, then a source checkout's `dashboard/dist` (editable installs, Docker), then the bundled copy. `agentmesh doctor` reports which directory is used.
- The release workflow builds the dashboard with npm before `python -m build`, sets `AGENTMESH_REQUIRE_DASHBOARD=1` so a wheel without the UI fails the build, and asserts the wheel contents. CI builds the wheel, installs it in a clean venv, and checks that the page and its assets are served.

### Fixed
- `new_id()` derived IDs from a hash of the current timestamp, so IDs minted in the same clock tick could collide; IDs are now random.
- Evaluations saved within the same second overwrote each other (IDs were `eval_<unix seconds>`).
- The live event stream (`/api/events/stream`, `/ws/events`) read the *oldest* 250 events, so it stopped reporting activity once a database held more than 250 events.
- `/ws/events` and `POST /api/jobs/compact` could not resolve their `WebSocket`/`BackgroundTasks` parameters (imported inside `create_app` while annotations are strings), so FastAPI treated them as required query parameters.
- The dashboard background image (`/vision-space.svg`) returned 404 when served by the Python server.
- **Security:** `WS /ws/events` accepted connections without the API key in `api_key` mode, streaming every event payload to any client. It now requires the same key as the REST API.
- **Security:** the runtime OpenTelemetry bridge (`configure_opentelemetry`) sent event payloads to the collector without secret redaction.
- The Workflows page and `/api/workflows` multiplied run counts, failed runs, and latency by the number of model calls per run (joined cost records row by row).
- The dashboard was unusable with `AGENTMESH_AUTH_MODE=api_key` because it never sent the key.
- `docs/docker.md` suggested `docker compose up -e ...`, which is not a valid flag, and `.env` auth settings were ignored by the compose file.

---

## Changes between 0.3.0-alpha and 0.4.0 (released as part of 0.4.0)

### Added
- `HOW_IT_WORKS.md` — 21 Mermaid diagrams covering architecture, sequence flows, DAG execution, RAG, cost governance, replay, and time-travel debugging.
- Full docs overhaul: all 23 `docs/` files rewritten with code examples, replacing stub content generated by Codex.
- `docs/README.md` — index of all docs with quick-start learning paths.
- `CITATION.cff` — academic citation file for research use.
- `docs/cli.md` — grouped CLI reference for all commands.
- `.github/ISSUE_TEMPLATE/config.yml` — routes blank issues to Discussions and security issues to Security Advisories.
- `dotenv` extras (`pip install -e ".[dotenv]"`) for automatic `.env` loading.
- OIDC trusted publishing to PyPI in `.github/workflows/release.yml` — no API tokens needed.
- `pip cache` step in CI for faster build times.

### Changed
- `BudgetLimiter` converted from `@dataclass` to a plain class with `threading.Lock` — eliminates race conditions when parallel steps check/update the budget simultaneously.
- `RetryPolicy.delay_for()` now uses full-jitter (`random.uniform(0, base)`) instead of pure exponential backoff — prevents thundering-herd when many retries fire at once.
- Independent tool calls within a single agent step now run concurrently with `asyncio.gather` instead of sequentially.
- `ReplayEngine.replay()` queries `list_checkpoints` once and reuses the result instead of querying twice.
- `get_trace_detail()` skips the `diagnose()` call for succeeded traces — only failed and cancelled traces pay the diagnosis cost.
- Token estimation uses character-count (`len(text) // 4`) instead of word-count — closer to real BPE tokeniser output for English prose.
- CLI `main()` calls `_load_dotenv()` on startup — `.env` is automatically loaded if `python-dotenv` is installed.
- `agentmesh doctor` now checks `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `VLLM_BASE_URL`, and `dashboard_built` in addition to prior checks; uses `COUNT(*)` SQL instead of loading all traces.
- `Setup.md` section 21 updated to remove deleted `docs/getting-started.md` reference.
- 14 redundant/placeholder markdown files deleted: `docs/architecture.md`, `docs/contributing.md`, `docs/costs.md`, `docs/getting-started.md`, `docs/installation.md`, `docs/memory-rag.md`, `docs/models.md`, `docs/quickstart.md`, `docs/roadmap.md`, and 5 `apps/`/`packages/` placeholder READMEs.

### Fixed
- `pyproject.toml` section ordering corrected — `keywords` and `classifiers` were being parsed as `[project.urls]` entries instead of `[project]` entries.
- `pytest` and `pytest-asyncio` removed from main `[project.dependencies]` — they belong in `[dev]` extras only.

---

## [0.3.0-alpha] — 2025-05-01

### Added
- Trace-first React dashboard: trace detail cockpit, span tree, waterfall timeline, inspector tabs, OTEL JSON export action.
- Failure Inbox, Provider Health panel, React Flow workflow graph, TanStack trace tables.
- Replay Studio: deterministic, simulated, and live replay from any checkpoint.
- Cost Center: spend analytics by workflow/agent/model/provider, budget usage, failed-run waste, cache savings.
- Tool Inspector: permissions, approval status, side effects, sandbox logs, MCP metadata.
- Memory & RAG inspector: versioned records, retrieved chunks, similarity scores, source metadata.
- Prompt registry with version history.
- OpenTelemetry-compatible JSON export via FastAPI and CLI (`--format otel-json`).
- API key auth mode (`AGENTMESH_AUTH_MODE=api_key`).
- Docker Compose one-command SQLite dashboard demo.
- Smoke test suite and deterministic screenshot generation.
- `agentmesh doctor` and `agentmesh validate traces` CLI commands.

### Changed
- Componentized React dashboard structure with reusable layout, trace, provider, workflow, and table components.
- Improved trace list usability: primary Open action near the left, sticky actions, row hover/selected states, provider/model tooltips.
- Hardened fresh-clone flow with explicit Windows/macOS/Linux commands.
- Expanded secret redaction coverage for logs, persisted JSON, and exports.
- CI: trace validation, demo seed, and dashboard smoke tests on Python 3.11/3.12/3.13.

### Fixed
- Deterministic replay correctly reconstructs prompts, tool calls, memory state, and checkpoints.
- Provider adapter tests no longer require real API keys.

---

## [0.1.0] — 2025-02-01

### Added
- Async multi-agent workflow runtime: sequential, parallel, hierarchical, and event-driven modes.
- Trace-first SQLite and PostgreSQL persistence for workflows, spans, model calls, tool calls, memory, RAG, approvals, costs, retries, and errors.
- ReplayEngine, TimeTravelDebugger, and FailedRunDiagnosis.
- FastAPI dashboard API: REST, SSE, WebSocket, health, metrics, and structured errors.
- React + TypeScript + TailwindCSS dashboard with Recharts analytics.
- 7 model providers: Mock, OpenAI-compatible, Ollama, Anthropic, Gemini, vLLM, Router.
- Typed tools, permission levels, human approval workflow, tool sandboxing.
- SQLite memory store with versioning and audit logs.
- FAISS and SQLite vector stores with cosine similarity for RAG.
- Cost tracking and pricing for major LLM providers.
- Retry policies (exponential backoff), budget limiter, circuit breaker, rate limiter.
- Plugin system with `AgentMeshPlugin` protocol.
- NATS and Redis event bus adapters for distributed coordination.
- CLI: `init`, `run`, `dashboard`, `traces`, `replay`, `export`, `import`, `diagnose`, `costs`, `demo`, `version`.
- 20 runnable examples.
- Dockerfile, Docker Compose, CI pipeline.
- OpenTelemetry bridge and OTLP export foundation.
