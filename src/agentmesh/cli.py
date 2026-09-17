from __future__ import annotations

import argparse
import json
import os
import platform
import re
import runpy
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from agentmesh.alerts import ALERT_KINDS
from agentmesh.costs import CostTracker
from agentmesh.dashboard import create_app
from agentmesh.debug import FailedRunDiagnosis, ReplayEngine, TimeTravelDebugger
from agentmesh.stores import create_store
from agentmesh.tracing import TraceReplayer


def _load_dotenv() -> None:
    """Load a .env file if python-dotenv is installed. Silent no-op if it isn't."""
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]
        load_dotenv()
    except ImportError:
        pass


def main() -> None:
    _load_dotenv()
    parser = argparse.ArgumentParser(prog="agentmesh", description="AgentMesh: open-source observability for AI agents")
    parser.add_argument(
        "--db",
        default=os.getenv("AGENTMESH_DB_URL") or os.getenv("AGENTMESH_DB") or ".agentmesh/agentmesh.db",
        help="Trace database path or URL (default: AGENTMESH_DB_URL or .agentmesh/agentmesh.db)",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("init", help="Create local AgentMesh project files")

    run_parser = subcommands.add_parser("run", help="Run a Python workflow file")
    run_parser.add_argument("file", help="Path to a Python workflow file")

    dashboard_parser = subcommands.add_parser("dashboard", help="Run the local dashboard")
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8787)

    traces_parser = subcommands.add_parser("traces", help="Inspect traces")
    traces_subcommands = traces_parser.add_subparsers(dest="traces_command", required=True)
    list_parser = traces_subcommands.add_parser("list", help="List recent traces")
    list_parser.add_argument("--limit", type=int, default=20)
    show_parser = traces_subcommands.add_parser("show", help="Show a trace")
    show_parser.add_argument("trace_id")
    export_trace_parser = traces_subcommands.add_parser("export", help="Export a trace as JSON")
    export_trace_parser.add_argument("trace_id")
    export_trace_parser.add_argument("--format", choices=["json", "otel-json"], default="json")
    export_trace_parser.add_argument("--out", help="Optional output file")
    validate_parser = traces_subcommands.add_parser("validate", help="Validate trace/span data integrity")
    validate_parser.add_argument("--limit", type=int, default=200)
    validate_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    insights_parser = traces_subcommands.add_parser("insights", help="Root cause, loops, context growth, and cost hotspots for a trace")
    insights_parser.add_argument("trace_id")
    prune_parser = traces_subcommands.add_parser("prune", help="Delete traces older than a retention window")
    prune_parser.add_argument("--older-than", required=True, help="Retention window, e.g. 30d, 12h, 2w")
    prune_parser.add_argument("--dry-run", action="store_true", help="Only count what would be deleted")
    prune_parser.add_argument("--vacuum", action="store_true", help="Reclaim disk space after deleting (runs VACUUM)")

    sessions_parser = subcommands.add_parser("sessions", help="Inspect multi-turn sessions")
    sessions_subcommands = sessions_parser.add_subparsers(dest="sessions_command", required=True)
    sessions_list = sessions_subcommands.add_parser("list", help="List recent sessions")
    sessions_list.add_argument("--limit", type=int, default=20)
    sessions_list.add_argument("--user-id")
    sessions_show = sessions_subcommands.add_parser("show", help="Show every trace in a session")
    sessions_show.add_argument("session_id")

    access_parser = subcommands.add_parser("access", help="What agents reached: outbound hosts and the data they read")
    access_subcommands = access_parser.add_subparsers(dest="access_command", required=True)
    access_summary = access_subcommands.add_parser("summary", help="Destinations and resources, most used first")
    access_summary.add_argument("--hours", type=float, help="Only the last N hours (marks destinations first seen in the window)")
    access_summary.add_argument("--kind", choices=["network", "retrieval", "memory", "db", "file", "api", "other"])
    access_summary.add_argument("--limit", type=int, default=50)
    access_list = access_subcommands.add_parser("list", help="Individual accesses, newest first")
    access_list.add_argument("--kind", choices=["network", "retrieval", "memory", "db", "file", "api", "other"])
    access_list.add_argument("--target", help="Match a host or resource (substring)")
    access_list.add_argument("--exact", action="store_true", help="Match --target exactly")
    access_list.add_argument("--trace")
    access_list.add_argument("--agent")
    access_list.add_argument("--hours", type=float)
    access_list.add_argument("--limit", type=int, default=50)

    swarms_parser = subcommands.add_parser("swarms", help="Inspect agent swarms: many agents working as one run")
    swarms_subcommands = swarms_parser.add_subparsers(dest="swarms_command", required=True)
    swarms_list = swarms_subcommands.add_parser("list", help="List recent swarms")
    swarms_list.add_argument("--limit", type=int, default=20)
    swarms_list.add_argument("--query", help="Match swarm id, name, or service")
    swarms_check = swarms_subcommands.add_parser("check", help="Evaluate swarm-wide limits once (e.g. from cron when no server runs)")
    swarms_check.add_argument("--no-enforce", action="store_true", help="Report breaches without halting swarms")
    swarms_show = swarms_subcommands.add_parser("show", help="Show a swarm's summary, roles, and insights")
    swarms_show.add_argument("swarm_id")
    swarms_show.add_argument("--full", action="store_true", help="Include every agent, edge, message, and the timeline")

    ingest_parser = subcommands.add_parser("ingest", help="Ingest an OTLP/JSON trace file (ExportTraceServiceRequest)")
    ingest_parser.add_argument("file", help="Path to an OTLP JSON file")

    mcp_parser = subcommands.add_parser("mcp", help="Run the AgentMesh MCP server over stdio (for Claude Code, Cursor, ...)")
    mcp_parser.add_argument("--transport", choices=["stdio"], default="stdio")

    pricing_parser = subcommands.add_parser("pricing", help="Inspect or refresh model pricing")
    pricing_subcommands = pricing_parser.add_subparsers(dest="pricing_command", required=True)
    pricing_sync = pricing_subcommands.add_parser("sync", help="Download the community price list (LiteLLM) to .agentmesh/pricing.json")
    pricing_sync.add_argument("--url", help="Alternative price list URL")
    pricing_sync.add_argument("--out", help="Output path (default: AGENTMESH_PRICING_FILE or .agentmesh/pricing.json)")
    pricing_show = pricing_subcommands.add_parser("show", help="Show the price rule used for a model")
    pricing_show.add_argument("model")
    pricing_show.add_argument("--provider")
    pricing_subcommands.add_parser("list", help="List all configured price rules")

    replay_parser = subcommands.add_parser("replay", help="Replay a previous run")
    replay_parser.add_argument("trace_id")
    replay_parser.add_argument("--from-span", dest="from_span")
    replay_parser.add_argument("--mode", choices=["deterministic", "simulated", "live"], default="deterministic")
    replay_parser.add_argument("--allow-side-effects", action="store_true", help="Required for live replay")

    export_parser = subcommands.add_parser("export", help="Export a trace as JSON")
    export_parser.add_argument("trace_id")
    export_parser.add_argument("--format", choices=["json", "otel-json"], default="json")
    export_parser.add_argument("--out", help="Optional output file")

    import_parser = subcommands.add_parser("import", help="Import a trace JSON export")
    import_parser.add_argument("file", help="Path to exported trace JSON")

    diagnose_parser = subcommands.add_parser("diagnose", help="Diagnose failed or suspicious traces")
    diagnose_parser.add_argument("trace_id")

    costs_parser = subcommands.add_parser("costs", help="Show token and cost analytics")
    costs_subcommands = costs_parser.add_subparsers(dest="costs_command")
    costs_summary = costs_subcommands.add_parser("summary", help="Show workspace cost summary")
    costs_summary.add_argument("--dimension", choices=["workflow", "agent", "model", "provider", "failed-run"])
    costs_trace = costs_subcommands.add_parser("trace", help="Show one trace cost summary")
    costs_trace.add_argument("trace_id")

    demo_parser = subcommands.add_parser("demo", help="Seed or inspect AgentMesh demo data")
    demo_subcommands = demo_parser.add_subparsers(dest="demo_command", required=True)
    demo_seed = demo_subcommands.add_parser("seed", help="Seed realistic dashboard demo data")
    demo_seed.add_argument("--reset", action="store_true", help="Clear the configured database before seeding")

    subcommands.add_parser("doctor", help="Check local AgentMesh dependencies and configuration")
    validate_command = subcommands.add_parser("validate", help="Validate AgentMesh data integrity")
    validate_command.add_argument("target", choices=["traces"])
    validate_command.add_argument("--limit", type=int, default=200)
    validate_command.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    subcommands.add_parser("version", help="Print AgentMesh version")

    checkpoints_parser = subcommands.add_parser("checkpoints", help="Inspect time-travel checkpoints")
    checkpoints_subcommands = checkpoints_parser.add_subparsers(dest="checkpoints_command", required=True)
    checkpoint_list = checkpoints_subcommands.add_parser("list", help="List checkpoints for a trace")
    checkpoint_list.add_argument("trace_id")
    checkpoint_show = checkpoints_subcommands.add_parser("show", help="Show one checkpoint")
    checkpoint_show.add_argument("checkpoint_id")
    checkpoint_patch = checkpoints_subcommands.add_parser("patch-memory", help="Fork a checkpoint with memory updates")
    checkpoint_patch.add_argument("checkpoint_id")
    checkpoint_patch.add_argument("--set", required=True, help="JSON object merged into workflow memory values")

    datasets_parser = subcommands.add_parser("datasets", help="Manage datasets of test cases (from traces, JSONL, or by hand)")
    datasets_subcommands = datasets_parser.add_subparsers(dest="datasets_command", required=True)
    datasets_subcommands.add_parser("list", help="List datasets")
    dataset_create = datasets_subcommands.add_parser("create", help="Create a dataset")
    dataset_create.add_argument("name")
    dataset_create.add_argument("--description")
    dataset_show = datasets_subcommands.add_parser("show", help="Show a dataset and its items")
    dataset_show.add_argument("name")
    dataset_show.add_argument("--limit", type=int, default=5000)
    dataset_add = datasets_subcommands.add_parser("add", help="Add one item")
    dataset_add.add_argument("name")
    dataset_add.add_argument("--input", required=True, help="Item input (JSON, or plain text)")
    dataset_add.add_argument("--expected", help="Expected output (JSON, or plain text)")
    dataset_add.add_argument("--metadata", help="JSON object")
    dataset_add_trace = datasets_subcommands.add_parser("add-trace", help="Copy a trace's input (and output as expected) into a dataset")
    dataset_add_trace.add_argument("name")
    dataset_add_trace.add_argument("trace_id")
    dataset_add_trace.add_argument("--span-id", help="Use this span's input/output instead of the trace root")
    dataset_add_trace.add_argument("--no-expected", action="store_true", help="Do not use the recorded output as the expected value")
    dataset_import = datasets_subcommands.add_parser("import", help="Import items from JSONL or a JSON array (creates the dataset if needed)")
    dataset_import.add_argument("name")
    dataset_import.add_argument("file")
    dataset_export = datasets_subcommands.add_parser("export", help="Export items as JSONL")
    dataset_export.add_argument("name")
    dataset_export.add_argument("--out")
    dataset_delete = datasets_subcommands.add_parser("delete", help="Delete a dataset with its items and experiments")
    dataset_delete.add_argument("name")

    experiments_parser = subcommands.add_parser("experiments", help="Run a task over a dataset, score it, and compare runs")
    experiments_subcommands = experiments_parser.add_subparsers(dest="experiments_command", required=True)
    experiments_list = experiments_subcommands.add_parser("list", help="List experiments")
    experiments_list.add_argument("--dataset")
    experiments_list.add_argument("--limit", type=int, default=50)
    experiments_show = experiments_subcommands.add_parser("show", help="Show an experiment with per-item results")
    experiments_show.add_argument("experiment_id")
    experiments_compare = experiments_subcommands.add_parser("compare", help="Compare two experiments item by item")
    experiments_compare.add_argument("base")
    experiments_compare.add_argument("candidate")
    experiments_run = experiments_subcommands.add_parser("run", help="Run an experiment (use in CI to gate releases)")
    experiments_run.add_argument("--dataset", required=True)
    experiments_run.add_argument("--task", required=True, help="module:function or path/to/file.py:function")
    experiments_run.add_argument(
        "--evaluator",
        action="append",
        default=[],
        help="exact_match, contains, json_valid[:key,key], similarity[:threshold], regex:<pattern>, or module:object (repeatable)",
    )
    experiments_run.add_argument("--name")
    experiments_run.add_argument("--concurrency", type=int, default=4)
    experiments_run.add_argument("--endpoint", help="Send traces and results to an AgentMesh server instead of --db")
    experiments_run.add_argument("--fail-under", action="append", default=[], metavar="EVALUATOR=SCORE", help="Exit 1 if a mean score is below this")
    experiments_run.add_argument("--baseline", help="Experiment id to compare against")
    experiments_run.add_argument("--fail-on-regression", action="store_true", help="Exit 1 if any item regressed vs --baseline")
    experiments_run.add_argument("--json", action="store_true", help="Print the full result as JSON")

    alerts_parser = subcommands.add_parser("alerts", help="Alert rules for failures, cost, latency, tool loops, new destinations, and swarm anomalies")
    alerts_subcommands = alerts_parser.add_subparsers(dest="alerts_command", required=True)
    alerts_subcommands.add_parser("list", help="List alert rules")
    alerts_add = alerts_subcommands.add_parser("add", help="Create an alert rule")
    alerts_add.add_argument("--name", required=True)
    alerts_add.add_argument("--kind", required=True, choices=list(ALERT_KINDS))
    alerts_add.add_argument("--threshold", required=True, type=float)
    alerts_add.add_argument("--window", default="15m", help="e.g. 15m, 1h, 1d")
    alerts_add.add_argument("--cooldown", default="30m")
    alerts_add.add_argument("--webhook", help="Webhook URL (Slack and Discord URLs are detected)")
    alerts_add.add_argument("--format", choices=["json", "slack", "discord"])
    alerts_add.add_argument("--secret", help="Sign payloads with HMAC-SHA256 (X-AgentMesh-Signature header)")
    alerts_add.add_argument("--workflow")
    alerts_add.add_argument("--environment")
    alerts_add.add_argument("--service")
    alerts_add.add_argument("--source", help="runtime, sdk, otlp, or file")
    alerts_add.add_argument("--min-runs", type=int)
    alerts_add.add_argument("--swarm", help="Only swarms whose id or name matches (swarm and new_destination rules; * allowed)")
    alerts_add.add_argument("--access-kind", choices=["network", "retrieval", "memory", "db", "file", "api", "other"], help="new_destination rules only")
    alerts_add.add_argument("--disabled", action="store_true")
    alerts_update = alerts_subcommands.add_parser("update", help="Change an alert rule")
    alerts_update.add_argument("name")
    alerts_update.add_argument("--threshold", type=float)
    alerts_update.add_argument("--window")
    alerts_update.add_argument("--cooldown")
    alerts_update.add_argument("--webhook")
    enabled_group = alerts_update.add_mutually_exclusive_group()
    enabled_group.add_argument("--enable", dest="enabled", action="store_true", default=None)
    enabled_group.add_argument("--disable", dest="enabled", action="store_false")
    alerts_remove = alerts_subcommands.add_parser("remove", help="Delete an alert rule")
    alerts_remove.add_argument("name")
    alerts_check = alerts_subcommands.add_parser("check", help="Evaluate all rules once and send notifications (for cron)")
    alerts_check.add_argument("--no-deliver", action="store_true", help="Record alerts without calling webhooks")
    alerts_test = alerts_subcommands.add_parser("test", help="Send a test notification for a rule")
    alerts_test.add_argument("name")
    alerts_history = alerts_subcommands.add_parser("history", help="Show recent alert notifications")
    alerts_history.add_argument("--rule")
    alerts_history.add_argument("--limit", type=int, default=50)

    policy_parser = subcommands.add_parser("policy", help="Guardrail policies that block, pause, or limit what agents do")
    policy_subcommands = policy_parser.add_subparsers(dest="policy_command", required=True)
    policy_validate = policy_subcommands.add_parser("validate", help="Check a policy file without saving it")
    policy_validate.add_argument("file", help="YAML or JSON policy file")
    policy_apply = policy_subcommands.add_parser("apply", help="Create or update a policy from a file (matched by name)")
    policy_apply.add_argument("file")
    policy_apply.add_argument("--disabled", action="store_true", help="Save without enforcing it yet")
    policy_subcommands.add_parser("list", help="List policies")
    policy_show = policy_subcommands.add_parser("show", help="Show a policy")
    policy_show.add_argument("name")
    policy_enable = policy_subcommands.add_parser("enable", help="Turn a policy on")
    policy_enable.add_argument("name")
    policy_disable = policy_subcommands.add_parser("disable", help="Turn a policy off")
    policy_disable.add_argument("name")
    policy_remove = policy_subcommands.add_parser("remove", help="Delete a policy")
    policy_remove.add_argument("name")
    policy_simulate = policy_subcommands.add_parser("simulate", help="Replay recent traces through a policy to see what it would have blocked")
    policy_simulate.add_argument("target", help="A policy file, or the name of a saved policy")
    policy_simulate.add_argument("--limit", type=int, default=200, help="Most recent traces to replay")
    policy_simulate.add_argument("--hours", type=float, help="Only traces started in the last N hours")
    policy_decisions = policy_subcommands.add_parser("decisions", help="Show recent guardrail decisions")
    policy_decisions.add_argument("--trace")
    policy_decisions.add_argument("--action", choices=["blocked", "would_block", "require_approval", "warn", "allow", "deny"])
    policy_decisions.add_argument("--limit", type=int, default=50)

    halt_parser = subcommands.add_parser("halt", help="Kill switch: stop agents now, everywhere guardrails run")
    halt_subcommands = halt_parser.add_subparsers(dest="halt_command", required=True)
    halt_create = halt_subcommands.add_parser("create", help="Stop a trace, an agent, a service, or everything")
    halt_scope = halt_create.add_mutually_exclusive_group(required=True)
    halt_scope.add_argument("--all", action="store_true", help="Stop every agent")
    halt_scope.add_argument("--swarm", help="Stop every agent in a swarm, by swarm id")
    halt_scope.add_argument("--trace", help="Stop one trace")
    halt_scope.add_argument("--agent", help="Stop an agent by name")
    halt_scope.add_argument("--service", help="Stop a service by name")
    halt_create.add_argument("--reason")
    halt_list = halt_subcommands.add_parser("list", help="List halts")
    halt_list.add_argument("--all", action="store_true", help="Include released halts")
    halt_release = halt_subcommands.add_parser("release", help="Lift a halt")
    halt_release.add_argument("halt_id")

    args = parser.parse_args()
    if args.command == "init":
        _init_project()
    elif args.command == "run":
        runpy.run_path(str(Path(args.file).resolve()), run_name="__main__")
    elif args.command == "dashboard":
        _run_dashboard(args.db, args.host, args.port)
    elif args.command == "traces":
        _run_traces(args.db, args)
    elif args.command == "replay":
        print(json.dumps(_run_replay(args.db, args.trace_id, args.mode, args.from_span, args.allow_side_effects), indent=2))
    elif args.command == "export":
        store = create_store(args.db)
        payload = _export_trace_payload(store, args.trace_id, args.format)
        rendered = json.dumps(payload, indent=2)
        if args.out:
            Path(args.out).write_text(rendered, encoding="utf-8")
            print(args.out)
        else:
            print(rendered)
    elif args.command == "import":
        store = create_store(args.db)
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit("Trace import file must contain a JSON object")
        trace_id = ReplayEngine(store).import_json(payload)
        print(json.dumps({"trace_id": trace_id, "imported": True}, indent=2))
    elif args.command == "diagnose":
        store = create_store(args.db)
        print(json.dumps(FailedRunDiagnosis(store).diagnose(args.trace_id), indent=2))
    elif args.command == "costs":
        store = create_store(args.db)
        if args.costs_command == "summary":
            if args.dimension == "failed-run":
                payload = store.cost_by_failed_run()
            elif args.dimension:
                payload = store.cost_by_dimension(args.dimension)
            elif hasattr(store, "cost_summary"):
                payload = store.cost_summary()
            else:
                payload = CostTracker(store).summarize().to_json()
        elif args.costs_command == "trace":
            payload = CostTracker(store).summarize(args.trace_id).to_json()
        else:
            payload = CostTracker(store).summarize().to_json()
        print(json.dumps(payload, indent=2))
    elif args.command == "demo":
        from agentmesh.demo import seed_demo_data

        if args.demo_command == "seed":
            try:
                payload = seed_demo_data(args.db, reset=args.reset)
            except RuntimeError as exc:
                raise SystemExit(str(exc)) from exc
            print(json.dumps(payload, indent=2))
    elif args.command == "doctor":
        print(json.dumps(_doctor(args.db), indent=2))
    elif args.command == "validate":
        from agentmesh.validation import validate_traces

        store = create_store(args.db)
        print(json.dumps(validate_traces(store, args.limit), indent=2))
    elif args.command == "version":
        print(_version())
    elif args.command == "checkpoints":
        _run_checkpoints(args.db, args)
    elif args.command == "sessions":
        store = create_store(args.db)
        if not hasattr(store, "list_sessions"):
            raise SystemExit("Sessions require an AgentMesh SQLite or PostgreSQL store")
        if args.sessions_command == "list":
            print(json.dumps(store.list_sessions(limit=args.limit, user_id=args.user_id), indent=2))
        else:
            session = store.get_session(args.session_id)
            if session is None:
                raise SystemExit(f"Session not found: {args.session_id}")
            print(json.dumps(session, indent=2))
    elif args.command == "access":
        store = create_store(args.db)
        since = None
        if args.hours:
            from datetime import UTC, datetime, timedelta

            since = (datetime.now(UTC) - timedelta(hours=args.hours)).isoformat()
        if args.access_command == "summary":
            _print(store.access_summary(since=since, limit=args.limit, kind=args.kind))
        else:
            _print(store.list_access(limit=args.limit, kind=args.kind, target=args.target, trace_id=args.trace, agent=args.agent, since=since, exact=args.exact))
    elif args.command == "swarms":
        store = create_store(args.db)
        if args.swarms_command == "list":
            _print(store.list_swarms(limit=args.limit, query=args.query))
        elif args.swarms_command == "check":
            _print(store.check_swarm_limits(enforce=not args.no_enforce))
        else:
            detail = store.get_swarm(args.swarm_id)
            if detail is None:
                raise SystemExit(f"Swarm not found: {args.swarm_id}")
            if not args.full:
                detail = {key: detail[key] for key in ("swarm_id", "name", "service_name", "summary", "roles", "insights")}
            _print(detail)
    elif args.command == "ingest":
        from agentmesh.otlp import decode_json

        store = create_store(args.db)
        if not hasattr(store, "ingest_spans"):
            raise SystemExit("Span ingestion requires an AgentMesh SQLite or PostgreSQL store")
        payload = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
        print(json.dumps(store.ingest_spans(decode_json(payload), source="file"), indent=2))
    elif args.command == "mcp":
        from agentmesh.mcp_server import run_stdio_server

        run_stdio_server(args.db)
    elif args.command == "pricing":
        _run_pricing(args)
    elif args.command == "datasets":
        _run_datasets(args.db, args)
    elif args.command == "experiments":
        _run_experiments(args.db, args)
    elif args.command == "alerts":
        _run_alerts(args.db, args)
    elif args.command == "policy":
        _run_policy(args.db, args)
    elif args.command == "halt":
        _run_halt(args.db, args)


def _read_policy_file(path: str) -> str:
    file = Path(path)
    if not file.is_file():
        raise SystemExit(f"Policy file not found: {path}")
    return file.read_text(encoding="utf-8")


def _run_policy(db_path: str, args: argparse.Namespace) -> None:
    from agentmesh.policy import Policy, PolicyError
    from agentmesh.policy_store import validate_policy

    command = args.policy_command
    if command == "validate":
        result = validate_policy({"text": _read_policy_file(args.file)})
        _print(result)
        if not result["valid"]:
            raise SystemExit(1)
        return
    store = create_store(db_path)
    try:
        if command == "apply":
            text = _read_policy_file(args.file)
            name = Policy.from_spec(text).name
            payload = {"text": text, "enabled": not args.disabled}
            existing = store.get_policy(name)
            _print(store.update_policy(name, payload) if existing else store.create_policy(payload))
        elif command == "list":
            _print(store.list_policies())
        elif command in {"show", "enable", "disable", "remove"}:
            if command == "show":
                result = store.get_policy(args.name)
            elif command == "remove":
                result = {"deleted": True} if store.delete_policy(args.name) else None
            else:
                result = store.update_policy(args.name, {"enabled": command == "enable"})
            if result is None:
                raise SystemExit(f"Policy not found: {args.name}")
            _print(result)
        elif command == "simulate":
            if Path(args.target).is_file():
                policies = [Policy.from_spec(_read_policy_file(args.target))]
            else:
                saved = store.get_policy(args.target)
                if saved is None:
                    raise SystemExit(f"No policy file or saved policy named: {args.target}")
                policies = [Policy.from_spec(saved["spec"], policy_id=saved["policy_id"])]
            since = None
            if args.hours:
                from datetime import UTC, datetime, timedelta

                since = (datetime.now(UTC) - timedelta(hours=args.hours)).isoformat()
            _print(store.simulate_policy(policies, args.limit, since))
        elif command == "decisions":
            _print(store.list_policy_decisions(limit=args.limit, trace_id=args.trace, action=args.action))
    except PolicyError as exc:
        _print({"valid": False, "errors": exc.errors})
        raise SystemExit(1) from exc


def _run_halt(db_path: str, args: argparse.Namespace) -> None:
    store = create_store(db_path)
    command = args.halt_command
    if command == "create":
        scope, value = next(
            (name, getattr(args, name)) for name in ("all", "swarm", "trace", "agent", "service") if getattr(args, name)
        )
        halt = store.create_halt({"scope": scope, "value": None if scope == "all" else value, "reason": args.reason, "created_by": "cli"})
        store.audit(None, "cli", "guardrails.halt", scope, {"halt": halt})
        _print(halt)
    elif command == "list":
        _print(store.list_halts(active_only=not args.all))
    elif command == "release":
        halt = store.release_halt(args.halt_id, "cli")
        if halt is None:
            raise SystemExit(f"Halt not found: {args.halt_id}")
        store.audit(None, "cli", "guardrails.release", str(halt["scope"]), {"halt": halt})
        _print(halt)


def _json_arg(value: str | None) -> object:
    """Parse a CLI value as JSON, falling back to the plain string."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _error_text(exc: Exception) -> str:
    # KeyError wraps its message in quotes.
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def _run_datasets(db_path: str, args: argparse.Namespace) -> None:
    store = create_store(db_path)
    command = args.datasets_command
    try:
        if command == "list":
            _print(store.list_datasets())
        elif command == "create":
            _print(store.create_dataset(args.name, args.description))
        elif command == "show":
            dataset = store.get_dataset(args.name, limit=args.limit)
            if dataset is None:
                raise SystemExit(f"Dataset not found: {args.name}")
            _print(dataset)
        elif command == "add":
            metadata = _json_arg(args.metadata) if args.metadata else {}
            if not isinstance(metadata, dict):
                raise SystemExit("--metadata must be a JSON object")
            item = {"input": _json_arg(args.input), "expected": _json_arg(args.expected), "metadata": metadata}
            _print(store.add_dataset_items(args.name, [item]))
        elif command == "add-trace":
            kwargs = {"expected": None} if args.no_expected else {}
            _print(store.add_trace_to_dataset(args.name, args.trace_id, args.span_id, **kwargs))
        elif command == "import":
            text = Path(args.file).read_text(encoding="utf-8-sig").strip()
            if text.startswith("["):
                items = json.loads(text)
            else:
                items = [json.loads(line) for line in text.splitlines() if line.strip()]
            store.create_dataset(args.name, exist_ok=True)
            added = store.add_dataset_items(args.name, items)
            _print({"dataset": args.name, "imported": len(added)})
        elif command == "export":
            dataset = store.get_dataset(args.name, limit=None)
            if dataset is None:
                raise SystemExit(f"Dataset not found: {args.name}")
            lines = [
                json.dumps({key: item[key] for key in ("item_id", "input", "expected", "metadata")}, ensure_ascii=False)
                for item in dataset["items"]
            ]
            rendered = "".join(f"{line}\n" for line in lines)
            if args.out:
                Path(args.out).write_text(rendered, encoding="utf-8")
                print(args.out)
            else:
                sys.stdout.write(rendered)
        elif command == "delete":
            if not store.delete_dataset(args.name):
                raise SystemExit(f"Dataset not found: {args.name}")
            _print({"deleted": args.name})
    except (KeyError, ValueError) as exc:
        raise SystemExit(_error_text(exc)) from exc


def _run_experiments(db_path: str, args: argparse.Namespace) -> None:
    command = args.experiments_command
    if command == "run":
        raise SystemExit(_run_experiment_command(db_path, args))
    store = create_store(db_path)
    if command == "list":
        _print(store.list_experiments(dataset=args.dataset, limit=args.limit))
    elif command == "show":
        experiment = store.get_experiment(args.experiment_id)
        if experiment is None:
            raise SystemExit(f"Experiment not found: {args.experiment_id}")
        _print(experiment)
    elif command == "compare":
        comparison = store.compare_experiments(args.base, args.candidate)
        if comparison is None:
            raise SystemExit("Experiment not found")
        _print(comparison)


def _run_experiment_command(db_path: str, args: argparse.Namespace) -> int:
    import agentmesh
    from agentmesh.evaluators import builtin_evaluator, evaluator

    evaluators = []
    for spec in args.evaluator:
        resolved = builtin_evaluator(spec)
        if resolved is None:
            resolved = load_object(spec)
            if isinstance(resolved, type):
                resolved = resolved()
            elif callable(resolved) and not hasattr(resolved, "evaluate"):
                resolved = evaluator(resolved)
        evaluators.append(resolved)
    thresholds: dict[str, float] = {}
    for spec in args.fail_under:
        name, _, value = spec.partition("=")
        try:
            thresholds[name] = float(value)
        except ValueError:
            raise SystemExit(f"--fail-under expects EVALUATOR=SCORE, got {spec!r}") from None
    task = load_object(args.task)
    store = None
    if args.endpoint:
        agentmesh.init(endpoint=args.endpoint)
    else:
        agentmesh.init(db_path=db_path)
        store = create_store(db_path)
    try:
        result = agentmesh.run_experiment(args.dataset, task, evaluators, name=args.name, max_concurrency=args.concurrency, store=store)
    except KeyError as exc:
        raise SystemExit(_error_text(exc)) from exc
    finally:
        agentmesh.shutdown()
    exit_code = 0
    failed_thresholds = []
    for name, minimum in thresholds.items():
        actual = result.score(name)
        if actual is None or actual < minimum:
            failed_thresholds.append({"evaluator": name, "minimum": minimum, "actual": actual})
            exit_code = 1
    comparison = None
    if args.baseline:
        if store is None:
            raise SystemExit("--baseline needs a local --db (on a server, use GET /api/experiments/compare)")
        comparison = store.compare_experiments(args.baseline, result.experiment_id)
        if comparison is None:
            raise SystemExit(f"Baseline experiment not found: {args.baseline}")
        if args.fail_on_regression and comparison["counts"]["regressed"]:
            exit_code = 1
    if args.json:
        payload = {**result.to_json(), "failed_thresholds": failed_thresholds, "exit_code": exit_code}
        if comparison is not None:
            payload["comparison"] = {"counts": comparison["counts"], "score_deltas": comparison["score_deltas"]}
        _print(payload)
    else:
        print(result.format_summary())
        for failure in failed_thresholds:
            print(f"  FAIL {failure['evaluator']}: {failure['actual']} < {failure['minimum']}")
        if comparison is not None:
            counts = comparison["counts"]
            print(f"  vs {args.baseline}: {counts['improved']} improved, {counts['regressed']} regressed, {counts['unchanged']} unchanged")
    return exit_code


def load_object(ref: str) -> object:
    """Import ``module:attr`` or ``path/to/file.py:attr``."""
    import importlib
    import importlib.util

    target, _, attribute = ref.rpartition(":")
    if not target or not attribute:
        raise SystemExit(f"Expected module:name or path/to/file.py:name, got {ref!r}")
    if target.endswith(".py"):
        path = Path(target).resolve()
        if not path.is_file():
            raise SystemExit(f"File not found: {path}")
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise SystemExit(f"Cannot import {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        sys.path.insert(0, os.getcwd())
        module = importlib.import_module(target)
    value: object = module
    for part in attribute.split("."):
        value = getattr(value, part)
    return value


def _run_alerts(db_path: str, args: argparse.Namespace) -> None:
    store = create_store(db_path)
    command = args.alerts_command
    try:
        if command == "list":
            _print(store.list_alert_rules())
        elif command == "add":
            filters = {
                "workflow": args.workflow,
                "environment": args.environment,
                "service": args.service,
                "source": args.source,
                "min_runs": args.min_runs,
                "swarm": args.swarm,
                "access_kind": args.access_kind,
            }
            channel = {"url": args.webhook, "format": args.format, "secret": args.secret} if args.webhook else {}
            payload = {
                "name": args.name,
                "kind": args.kind,
                "threshold": args.threshold,
                "window": args.window,
                "cooldown": args.cooldown,
                "filters": {key: value for key, value in filters.items() if value is not None},
                "channel": {key: value for key, value in channel.items() if value is not None},
                "enabled": not args.disabled,
            }
            _print(store.create_alert_rule(payload))
        elif command == "update":
            changes: dict[str, object] = {"threshold": args.threshold, "window": args.window, "cooldown": args.cooldown, "enabled": args.enabled}
            if args.webhook:
                changes["channel"] = {"url": args.webhook}
            rule = store.update_alert_rule(args.name, {key: value for key, value in changes.items() if value is not None})
            if rule is None:
                raise SystemExit(f"Alert rule not found: {args.name}")
            _print(rule)
        elif command == "remove":
            if not store.delete_alert_rule(args.name):
                raise SystemExit(f"Alert rule not found: {args.name}")
            _print({"deleted": args.name})
        elif command == "check":
            _print({"fired": store.check_alerts(deliver=not args.no_deliver)})
        elif command == "test":
            result = store.test_alert_rule(args.name)
            if result is None:
                raise SystemExit(f"Alert rule not found: {args.name}")
            _print(result)
        elif command == "history":
            _print(store.list_alert_events(limit=args.limit, rule=args.rule))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _init_project() -> None:
    config_dir = Path(".agentmesh")
    config_dir.mkdir(exist_ok=True)
    config = config_dir / "config.toml"
    if not config.exists():
        config.write_text('db_path = ".agentmesh/agentmesh.db"\n', encoding="utf-8")
    print("Initialized AgentMesh project in .agentmesh/")


def _run_dashboard(db_path: str, host: str, port: int) -> None:
    import uvicorn

    app = create_app(db_path)
    print(f"AgentMesh dashboard:   http://{host}:{port}")
    print(f"OTLP trace endpoint:   http://{host}:{port}/v1/traces  (OTEL_EXPORTER_OTLP_ENDPOINT=http://{host}:{port})")
    uvicorn.run(app, host=host, port=port)


def _run_traces(db_path: str, args: argparse.Namespace) -> None:
    store = create_store(db_path)
    if args.traces_command == "list":
        traces = store.list_observable_traces(args.limit) if hasattr(store, "list_observable_traces") else [trace.to_json() for trace in store.list_traces(args.limit)]
        print(json.dumps(traces, indent=2))
    elif args.traces_command == "show":
        trace = store.get_observable_trace(args.trace_id) if hasattr(store, "get_observable_trace") else store.get_trace(args.trace_id)
        events = store.list_events(args.trace_id)
        spans = store.list_spans(args.trace_id) if hasattr(store, "list_spans") else []
        print(json.dumps({"trace": trace, "spans": spans, "events": events}, indent=2))
    elif args.traces_command == "export":
        payload = _export_trace_payload(store, args.trace_id, args.format)
        rendered = json.dumps(payload, indent=2)
        if args.out:
            Path(args.out).write_text(rendered, encoding="utf-8")
            print(args.out)
        else:
            print(rendered)
    elif args.traces_command == "validate":
        from agentmesh.validation import validate_traces

        print(json.dumps(validate_traces(store, args.limit), indent=2))
    elif args.traces_command == "insights":
        from agentmesh.analysis import trace_insights

        result = trace_insights(store, args.trace_id)
        if not result.get("found"):
            raise SystemExit(f"Trace not found: {args.trace_id}")
        print(json.dumps(result, indent=2))
    elif args.traces_command == "prune":
        if not hasattr(store, "prune_traces"):
            raise SystemExit("Pruning requires an AgentMesh SQLite or PostgreSQL store")
        cutoff = (datetime.now(UTC) - parse_duration(args.older_than)).isoformat()
        print(json.dumps(store.prune_traces(cutoff, dry_run=args.dry_run, vacuum=args.vacuum), indent=2))


def parse_duration(value: str) -> timedelta:
    """Parse retention windows such as ``30d``, ``12h``, ``90m``, or ``2w``."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*", value.lower())
    if not match:
        raise SystemExit(f"Invalid duration {value!r}; use a number followed by s, m, h, d, or w (e.g. 30d)")
    amount = float(match.group(1))
    unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[match.group(2)]
    return timedelta(**{unit: amount})


def _run_pricing(args: argparse.Namespace) -> None:
    from agentmesh import pricing

    if args.pricing_command == "sync":
        try:
            result = pricing.sync_pricing(args.url or pricing.LITELLM_PRICES_URL, args.out)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"Pricing sync failed: {exc}") from exc
        print(json.dumps(result, indent=2))
    elif args.pricing_command == "show":
        rule = pricing.pricing_for(args.provider, args.model)
        print(
            json.dumps(
                {
                    "model": args.model,
                    "normalized_model": pricing.normalize_model_name(args.model),
                    "provider": args.provider,
                    "found": rule is not None,
                    "rule": rule.to_json() if rule else None,
                },
                indent=2,
            )
        )
    else:
        print(json.dumps(pricing.list_pricing_rules(), indent=2))


def _run_replay(
    db_path: str,
    trace_id: str,
    mode: str = "deterministic",
    from_span: str | None = None,
    allow_side_effects: bool = False,
) -> dict[str, object]:
    if mode == "live" and not allow_side_effects:
        raise SystemExit(
            "Live replay is non-deterministic and may call external providers/tools. "
            "Re-run with --allow-side-effects if you really want live replay."
        )
    store = create_store(db_path)
    result = TraceReplayer(store).replay(trace_id)
    result["mode"] = mode
    result["side_effects_disabled"] = mode != "live" or not allow_side_effects
    result["semantics"] = _replay_semantics(mode)
    if hasattr(store, "create_replay"):
        stored_mode = f"{mode}-from-span" if from_span else mode
        result = store.create_replay(trace_id, from_span, stored_mode, result)
        result["mode"] = stored_mode
    return result


def _replay_semantics(mode: str) -> str:
    if mode == "deterministic":
        return "uses recorded model outputs and recorded tool outputs; no external side effects are executed"
    if mode == "simulated":
        return "uses mock/simulated outputs; no external side effects are executed"
    return "calls live providers/tools and can differ from the original run"


def _run_checkpoints(db_path: str, args: argparse.Namespace) -> None:
    store = create_store(db_path)
    if args.checkpoints_command == "list":
        print(json.dumps(store.list_checkpoints(args.trace_id), indent=2))
    elif args.checkpoints_command == "show":
        print(json.dumps(TimeTravelDebugger(store).inspect(args.checkpoint_id), indent=2))
    elif args.checkpoints_command == "patch-memory":
        updates = json.loads(args.set)
        if not isinstance(updates, dict):
            raise SystemExit("--set must be a JSON object")
        fork_id = TimeTravelDebugger(store).patch_memory(args.checkpoint_id, updates)
        print(json.dumps({"checkpoint_id": fork_id}, indent=2))


def _export_trace_payload(store: object, trace_id: str, export_format: str) -> dict[str, object]:
    if export_format == "otel-json":
        from agentmesh import __version__
        from agentmesh.otel_export import export_otel_json

        payload = ReplayEngine(store).export_json(trace_id)
        if hasattr(store, "audit"):
            store.audit(trace_id, "system", "trace.exported", trace_id, {"format": "otel-json"})
        return export_otel_json(payload, version=__version__)
    return ReplayEngine(store).export_json(trace_id)


def _doctor(db_path: str) -> dict[str, object]:
    from agentmesh.dashboard import dashboard_dist_dir

    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "agentmesh_version": _version(),
        "database": db_path,
        "environment": {
            "AGENTMESH_DB_URL": bool(os.getenv("AGENTMESH_DB_URL")),
            "AGENTMESH_AUTH_MODE": os.getenv("AGENTMESH_AUTH_MODE", "none"),
            "AGENTMESH_API_KEY": bool(os.getenv("AGENTMESH_API_KEY")),
            "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
            "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
            "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
            "OLLAMA_HOST": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            "VLLM_BASE_URL": os.getenv("VLLM_BASE_URL"),
        },
        "optional_dependencies": {},
        "dashboard_built": dashboard_dist_dir() is not None,
        "dashboard_dir": str(dashboard_dist_dir() or "") or None,
    }
    from agentmesh.otlp import protobuf_available
    from agentmesh.pricing import pricing_file_path

    checks["otlp_protobuf_ingest"] = protobuf_available()
    checks["pricing_file"] = {"path": str(pricing_file_path()), "exists": pricing_file_path().exists()}
    for module in ["faiss", "numpy", "opentelemetry", "psycopg", "redis", "nats", "openai", "anthropic"]:
        try:
            __import__(module)
            checks["optional_dependencies"][module] = True
        except Exception:
            checks["optional_dependencies"][module] = False
    store = create_store(db_path)
    from agentmesh.validation import validate_traces

    checks["database_ok"] = True
    # Use list_traces(1) just to confirm the DB is readable; count from a summary
    # query instead of fetching all trace objects.
    try:
        if hasattr(store, "list_observable_traces"):
            sample = store.list_observable_traces(1)
        else:
            sample = store.list_traces(1)
        checks["database_readable"] = True
        # Get a lightweight count without loading all objects
        if hasattr(store, "_conn"):
            row = store._conn.execute("select count(*) as n from workflows").fetchone()
            checks["trace_count"] = int(row["n"]) if row else 0
        else:
            checks["trace_count"] = len(sample)
    except Exception as exc:
        checks["database_readable"] = False
        checks["database_error"] = str(exc)
        checks["trace_count"] = 0
    checks["trace_validation"] = validate_traces(store, 200)
    return checks


def _version() -> str:
    try:
        from agentmesh import __version__

        return __version__
    except Exception:
        pass
    try:
        return version("agentmesh-ai")
    except PackageNotFoundError:
        return "0.5.0"


if __name__ == "__main__":
    main()
