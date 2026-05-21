# Troubleshooting

## Port Already In Use

Run the dashboard on another port:

```bash
python -m agentmesh.cli dashboard --host 127.0.0.1 --port 8790
```

## SQLite Database Locked

Stop any running dashboard using the same `.agentmesh/agentmesh.db`, then retry:

```bash
python -m agentmesh.cli demo seed --reset
```

If you want to avoid touching the active database, use a separate path:

```bash
python -m agentmesh.cli --db .agentmesh/test.db demo seed --reset
```

## Dashboard Build Failure

Install Node.js 22 or newer, then rebuild:

```bash
cd dashboard
npm ci
npm run build
```

## Missing Python Version

AgentMesh supports Python 3.11 through 3.13. Confirm with:

```bash
python --version
```

## Ollama Not Running

Ollama examples require a local daemon and model. The test suite mocks Ollama and does not require it.

## API Key Not Configured

If `AGENTMESH_AUTH_MODE=api_key`, set `AGENTMESH_API_KEY` and send `Authorization: Bearer <key>`.

## Empty Dashboard

Seed demo data or run an example:

```bash
python -m agentmesh.cli demo seed --reset
python examples/hello_agent.py
```

## Old Demo Data

Reset the local demo database:

```bash
python -m agentmesh.cli demo seed --reset
```

