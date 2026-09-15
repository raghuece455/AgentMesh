import io
import json
import os
import subprocess
import sys

import pytest

from agentmesh import pricing
from agentmesh.mcp_server import AgentMeshMCPServer
from agentmesh.otlp import decode_json
from agentmesh.storage import SQLiteStore
from agentmesh.stores import create_store
from tests.test_ingest_otlp import TRACE_ID, llm_span, otlp, root_span, tool_span


def _rpc(server, method, params=None, request_id=1):
    return server.handle({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})


def _tool(server, name, arguments):
    response = _rpc(server, "tools/call", {"name": name, "arguments": arguments})
    result = response["result"]
    return result, json.loads(result["content"][0]["text"]) if not result["isError"] else result["content"][0]["text"]


@pytest.fixture
def seeded_store(db_url):
    store = create_store(db_url)
    store.ingest_spans(decode_json(otlp([root_span(), llm_span(), tool_span()])))
    return store


def test_mcp_handshake_and_tool_listing(seeded_store):
    server = AgentMeshMCPServer(seeded_store)
    init = _rpc(
        server,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    )
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["serverInfo"]["name"] == "agentmesh"
    assert _rpc(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-11-25"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert _rpc(server, "ping")["result"] == {}
    assert _rpc(server, "does/not/exist")["error"]["code"] == -32601

    tools = {tool["name"]: tool for tool in _rpc(server, "tools/list")["result"]["tools"]}
    assert {
        "list_traces",
        "get_trace",
        "get_span",
        "diagnose_trace",
        "search_spans",
        "cost_summary",
        "list_sessions",
        "get_session",
        "list_experiments",
        "compare_experiments",
        "list_alerts",
        "add_score",
    } <= set(tools)
    assert tools["get_trace"]["inputSchema"]["required"] == ["trace_id"]
    assert tools["list_traces"]["annotations"]["readOnlyHint"] is True


def test_mcp_tools_answer_debugging_questions(seeded_store):
    server = AgentMeshMCPServer(seeded_store)

    _, traces = _tool(server, "list_traces", {"limit": 5})
    assert traces["traces"][0]["trace_id"] == TRACE_ID

    _, trace = _tool(server, "get_trace", {"trace_id": TRACE_ID, "include_content": True})
    names = {span["name"]: span for span in trace["spans"]}
    assert names["execute_tool web_search"]["depth"] == 1
    assert names["execute_tool web_search"]["error_message"] == "search timed out"
    assert names["chat claude-sonnet-5"]["cost"] == pytest.approx(2.1)

    _, span = _tool(server, "get_span", {"trace_id": TRACE_ID, "span_id": "00f067aa0ba902b7"})
    assert span["model_call"]["cached_tokens"] == 500_000

    _, diagnosis = _tool(server, "diagnose_trace", {"trace_id": TRACE_ID})
    assert diagnosis["findings"][0]["kind"] == "root_cause"

    _, found = _tool(server, "search_spans", {"status": "failed"})
    assert found["spans"][0]["tool"] == "web_search"

    _, costs = _tool(server, "cost_summary", {"group_by": "model"})
    assert costs["breakdown"][0]["name"] == "claude-sonnet-5"

    _, session = _tool(server, "get_session", {"session_id": "session-42"})
    assert session["traces"][0]["trace_id"] == TRACE_ID

    result, _ = _tool(
        server,
        "add_score",
        {"trace_id": TRACE_ID, "name": "reviewer_verdict", "value": "tool timeout", "comment": "retry search"},
    )
    assert result["isError"] is False
    assert seeded_store.list_scores(trace_id=TRACE_ID, name="reviewer_verdict")[0]["label"] == "tool timeout"

    missing, message = _tool(server, "get_trace", {"trace_id": "nope"})
    assert missing["isError"] is True and "not found" in message

    seeded_store.create_dataset("qa")
    item = {"item_id": "q1", "input": "Q3 revenue?", "expected": "12%"}
    seeded_store.add_dataset_items("qa", [item])
    for experiment_id, output, score in (("exp_a", "12%", 1.0), ("exp_b", "no idea", 0.0)):
        seeded_store.save_experiment(
            {"experiment_id": experiment_id, "name": experiment_id, "dataset": "qa", "status": "completed",
             "results": [{**item, "output": output, "scores": [{"name": "exact_match", "score": score, "passed": bool(score)}]}]}
        )
    _, experiments = _tool(server, "list_experiments", {"dataset": "qa"})
    assert [row["name"] for row in experiments] and experiments[0]["summary"]["items"] == 1
    _, comparison = _tool(server, "compare_experiments", {"base": "exp_a", "candidate": "exp_b"})
    assert comparison["counts"]["regressed"] == 1
    assert comparison["changed_items"][0]["candidate"]["output"] == "no idea"
    seeded_store.create_alert_rule({"name": "failures", "kind": "failure_count", "threshold": 0, "window": "3650d"})
    seeded_store.check_alerts()
    _, alerts = _tool(server, "list_alerts", {})
    assert alerts["rules"][0]["state"] == "firing" and alerts["recent"][0]["rule_name"] == "failures"


def test_mcp_stdio_transport(seeded_store):
    server = AgentMeshMCPServer(seeded_store)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_traces", "arguments": {}}},
    ]
    stdin = io.BytesIO(("\n".join(json.dumps(item) for item in requests) + "\nnot-json\n").encode())
    stdout = io.BytesIO()
    server.serve_stdio(stdin, stdout)
    lines = [json.loads(line) for line in stdout.getvalue().decode().splitlines()]
    assert [line.get("id") for line in lines] == [1, 2, None]
    assert lines[2]["error"]["code"] == -32700


def test_pricing_normalization_and_cache_math():
    assert pricing.normalize_model_name("us.anthropic.claude-sonnet-4-5-20250929-v1:0") == "claude-sonnet-4-5"
    assert pricing.normalize_model_name("claude-opus-4-1@20250805") == "claude-opus-4-1"
    assert pricing.normalize_model_name("models/gemini-2.5-flash") == "gemini-2.5-flash"
    assert pricing.normalize_model_name("openai/gpt-4o-2024-08-06") == "gpt-4o"
    assert pricing.normalize_model_name("claude-opus-4.5") == "claude-opus-4-5"

    opus = pricing.estimate_model_cost(
        "anthropic", "claude-opus-5", 1_000_000, 1_000_000, cached_tokens=400_000, cache_write_tokens=100_000
    )
    assert opus.cost_usd == pytest.approx(500_000 * 5 / 1e6 + 400_000 * 0.5 / 1e6 + 100_000 * 6.25 / 1e6 + 25.0)
    fable = pricing.estimate_model_cost("anthropic", "claude-fable-5-1", 1_000_000, 0, cached_tokens=1_000_000)
    assert fable.cost_usd == pytest.approx(0.25)
    # Claude on Bedrock matches the same model rule; local providers are always free.
    assert pricing.pricing_for("aws.bedrock", "anthropic.claude-haiku-4-5-20251001-v1:0").input_per_mtok == 1.0
    assert pricing.estimate_model_cost("ollama", "gpt-oss:20b", 5000, 5000).status == "local/free"
    assert pricing.estimate_model_cost("openai", "gpt-4o-mini", 1_000_000, 0).cost_usd == pytest.approx(0.15)


def test_pricing_overrides_and_litellm_sync_format(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTMESH_PRICING_FILE", str(tmp_path / "pricing.json"))
    monkeypatch.setenv(
        "AGENTMESH_PRICING_JSON",
        json.dumps(
            [{"provider": "openai", "model": "gpt-4o", "input_per_mtok": 1, "output_per_mtok": 1, "status": "exact"}]
        ),
    )
    assert pricing.estimate_model_cost("openai", "gpt-4o", 1_000_000, 1_000_000).cost_usd == pytest.approx(2.0)
    assert pricing.estimate_model_cost("openai", "gpt-4o", 1_000_000, 0).status == "exact"
    monkeypatch.setenv(
        "AGENTMESH_PRICING_JSON",
        json.dumps(
            [{"provider": "mistral", "model": "mistral-large*", "prompt_per_1k": 0.002, "completion_per_1k": 0.006}]
        ),
    )
    assert pricing.estimate_model_cost("mistral", "mistral-large-2411", 1000, 1000).cost_usd == pytest.approx(0.008)

    rules = pricing.convert_litellm_prices(
        {
            "sample_spec": {"mode": "chat"},
            "deepseek/deepseek-chat": {
                "mode": "chat",
                "input_cost_per_token": 2.7e-07,
                "output_cost_per_token": 1.1e-06,
                "cache_read_input_token_cost": 7e-08,
                "litellm_provider": "deepseek",
            },
            "text-embedding-3-large": {"mode": "embedding", "input_cost_per_token": 1.3e-07},
        }
    )
    assert rules == [
        {
            "provider": "*",
            "model": "deepseek-chat",
            "input_per_mtok": 0.27,
            "output_per_mtok": 1.1,
            "status": "estimated",
            "notes": "LiteLLM community price list (deepseek)",
            "source": "litellm",
            "cache_read_per_mtok": 0.07,
        }
    ]
    (tmp_path / "pricing.json").write_text(json.dumps({"rules": rules}), encoding="utf-8")
    assert pricing.estimate_model_cost("deepseek", "deepseek-chat", 1_000_000, 0).cost_usd == pytest.approx(0.27)
    assert pricing.estimate_model_cost("deepseek", "deepseek-chat", 0, 0).source == "pricing:litellm"


def _cli(*args, db):
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}
    return subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_cli_ingest_sessions_insights_pricing_and_prune(tmp_path):
    db = tmp_path / "cli.db"
    trace_file = tmp_path / "trace.otlp.json"
    trace_file.write_text(json.dumps(otlp([root_span(), llm_span(), tool_span()])), encoding="utf-8")

    ingested = _cli("ingest", str(trace_file), db=db)
    assert ingested.returncode == 0, ingested.stderr
    assert json.loads(ingested.stdout)["spans"] == 3
    assert json.loads(_cli("sessions", "list", db=db).stdout)[0]["session_id"] == "session-42"
    assert json.loads(_cli("sessions", "show", "session-42", db=db).stdout)["trace_count"] == 1
    insights = json.loads(_cli("traces", "insights", TRACE_ID, db=db).stdout)
    assert insights["stats"]["llm_calls"] == 1
    shown = json.loads(_cli("pricing", "show", "claude-sonnet-5", db=db).stdout)
    assert shown["rule"]["input_per_mtok"] == 2.0
    assert json.loads(_cli("traces", "prune", "--older-than", "1d", "--dry-run", db=db).stdout)["traces"] == 1
    assert _cli("traces", "prune", "--older-than", "soon", db=db).returncode != 0
    assert json.loads(_cli("traces", "prune", "--older-than", "1d", db=db).stdout)["traces"] == 1
    assert json.loads(_cli("sessions", "list", db=db).stdout) == []


def test_cli_mcp_server_speaks_json_rpc_over_stdio(tmp_path):
    db = tmp_path / "mcp.db"
    SQLiteStore(db).ingest_spans(decode_json(otlp([root_span()])))
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_traces", "arguments": {"limit": 1}},
        },
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db), "mcp"],
        input="\n".join(json.dumps(message) for message in messages) + "\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    lines = [json.loads(line) for line in completed.stdout.splitlines()]
    assert len(lines) == 2, completed.stdout + completed.stderr
    assert json.loads(lines[1]["result"]["content"][0]["text"])["traces"][0]["trace_id"] == TRACE_ID
