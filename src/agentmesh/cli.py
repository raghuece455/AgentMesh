from __future__ import annotations

import argparse
import json
import os
import platform
import runpy
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

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
    parser = argparse.ArgumentParser(prog="agentmesh", description="AgentMesh multi-agent framework CLI")
    parser.add_argument("--db", default=".agentmesh/agentmesh.db", help="SQLite trace database path")
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
    demo_seed.add_argument("--reset", action="store_true", help="Reset the configured SQLite DB before seeding")

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
    print(f"AgentMesh dashboard: http://{host}:{port}")
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
    from pathlib import Path as _Path

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
        "dashboard_built": (_Path(__file__).resolve().parents[2] / "dashboard" / "dist" / "index.html").exists(),
    }
    for module in ["faiss", "numpy", "opentelemetry", "psycopg", "redis", "nats"]:
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
        return version("agentmesh")
    except PackageNotFoundError:
        return "0.3.0-alpha"


if __name__ == "__main__":
    main()
