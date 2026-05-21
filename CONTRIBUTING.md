# Contributing to AgentMesh

Thanks for taking the time to contribute. AgentMesh is an open-source observability and orchestration platform for multi-agent AI systems — every contribution, from a typo fix to a new provider adapter, helps.

## Quick Start

```bash
git clone https://github.com/raghuece455/AgentMesh.git
cd AgentMesh
python3 -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# Run the full test suite
pytest

# Verify nothing is broken
python -m compileall -q src
python -m agentmesh.cli doctor
```

For dashboard changes:

```bash
cd dashboard
npm ci
npm run build
npm run test:smoke  # requires a running dashboard
```

## Ways to Contribute

**Good first issues** — labeled [`good first issue`](https://github.com/raghuece455/AgentMesh/issues?q=label%3A%22good+first+issue%22):
- Improve error messages or documentation.
- Add a new runnable example in `examples/`.
- Fix a typo or expand a doc page in `docs/`.
- Add a test for an untested path.

**Substantial contributions welcome:**
- New model provider adapters (Bedrock, Groq, Mistral, Cohere, etc.).
- New vector store backends.
- Dashboard UI improvements (pages, charts, filtering, accessibility).
- CLI subcommands or flags.
- OTLP collector push integration.
- Plugin system improvements.
- Distributed worker support.
- Performance work on the SQLite schema or query layer.

## Development Principles

- Keep APIs typed and small. Every public function or class must have a type annotation.
- Prefer readable orchestration over clever control flow.
- Add trace events for new runtime behavior — if it affects a workflow run, it should be in the trace.
- Redact secrets before logging or persistence. Use the redaction utilities in `types.py`.
- Include deterministic tests with `MockModelProvider`. Tests must not call real APIs.
- Keep the public `__init__.py` exports clean — new exports need a clear reason.

## Commit Style

Use short, imperative commit messages:

```
add Bedrock provider adapter
fix cost estimate for cached Anthropic tokens
improve replay checkpoint pagination
```

No issue numbers required in commit messages (link them in the PR description instead).

## Pull Request Process

1. Fork the repo and create a branch from `main`.
2. Make your change with tests.
3. Run `pytest` and confirm it passes.
4. Run `python -m compileall -q src` to catch syntax errors.
5. If you changed the dashboard, run `cd dashboard && npm run build`.
6. Open a pull request using the PR template. Include:
   - What the change does and why.
   - How you tested it.
   - Any trace, security, or dashboard impact.

PRs are reviewed within a few days. Small, focused PRs merge faster.

## Adding a Model Provider

1. Add a class in `src/agentmesh/providers.py` that implements the `ModelProvider` protocol.
2. Export it from `src/agentmesh/__init__.py`.
3. Add an example in `examples/`.
4. Add a test in `tests/test_provider_adapters.py` using `MockModelProvider` for the model response.
5. Document it in `docs/model-providers.md` and `Setup.md`.

See `OllamaProvider` in `providers.py` as a reference for a minimal implementation.

## Adding a Tool

Tools are typed Python functions registered with `ToolRegistry`. See `tools.py` and `examples/tool_calling_agent.py` for the pattern.

New built-in tools go in `src/agentmesh/tools.py`. Example-level tools stay in `examples/`.

## Adding a Dashboard Page

The React frontend lives in `dashboard/src/`. Pages are in `dashboard/src/pages/`. Add your page component, register it in `App.tsx`, and add navigation items in `layout/Navigation.tsx`.

Use existing components from `dashboard/src/components/` before creating new ones.

## Running Specific Tests

```bash
pytest tests/test_workflow.py -v
pytest tests/test_production_features.py -v -k "approval"
pytest -x  # stop on first failure
```

## Code Style

Python: `ruff` (configured in `pyproject.toml`). Run `ruff check src` before submitting.

TypeScript/React: follow existing component patterns. No additional linter is currently enforced.

## Reporting Bugs

Use the [bug report template](https://github.com/raghuece455/AgentMesh/issues/new?template=bug_report.md). Include:
- AgentMesh version (`agentmesh version`)
- Python version
- OS
- Model provider
- `agentmesh export <trace_id>` output if the bug happened inside a workflow

## Asking Questions

Open a [GitHub Discussion](https://github.com/raghuece455/AgentMesh/discussions) for questions, ideas, or show-and-tell. Issues are for bugs and concrete feature requests.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
