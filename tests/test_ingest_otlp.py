import gzip
import json
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agentmesh.dashboard import create_app
from agentmesh.otlp import decode_json, encode_json
from agentmesh.storage import SQLiteStore
from agentmesh.stores import create_store

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
ROOT = "b7ad6b7169203331"
LLM = "00f067aa0ba902b7"
TOOL = "1111111111111111"
BASE_NS = 1_760_000_000_000_000_000


def attr(key, value):
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    if isinstance(value, list):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": item} for item in value]}}}
    return {"key": key, "value": {"stringValue": value}}


def otlp(spans, service="support-bot", environment="production"):
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [attr("service.name", service), attr("deployment.environment.name", environment)]
                },
                "scopeSpans": [{"scope": {"name": "test"}, "spans": spans}],
            }
        ]
    }


def root_span():
    return {
        "traceId": TRACE_ID,
        "spanId": ROOT,
        "name": "invoke_agent researcher",
        "kind": 1,
        "startTimeUnixNano": str(BASE_NS),
        "endTimeUnixNano": str(BASE_NS + 3_000_000_000),
        "attributes": [
            attr("gen_ai.operation.name", "invoke_agent"),
            attr("gen_ai.agent.name", "researcher"),
            attr("gen_ai.conversation.id", "session-42"),
            attr("user.id", "user-7"),
            attr("input.value", "What changed in the Q3 report?"),
            attr("output.value", "Revenue grew 12%."),
        ],
        "status": {"code": 1},
    }


def llm_span():
    return {
        "traceId": TRACE_ID,
        "spanId": LLM,
        "parentSpanId": ROOT,
        "name": "chat claude-sonnet-5",
        "kind": 3,
        "startTimeUnixNano": str(BASE_NS + 1_000),
        "endTimeUnixNano": str(BASE_NS + 1_500_000_000),
        "attributes": [
            attr("gen_ai.operation.name", "chat"),
            attr("gen_ai.provider.name", "anthropic"),
            attr("gen_ai.request.model", "claude-sonnet-5"),
            attr("gen_ai.request.temperature", 0.2),
            attr("gen_ai.usage.input_tokens", 1_000_000),
            attr("gen_ai.usage.output_tokens", 100_000),
            attr("gen_ai.usage.cache_read.input_tokens", 500_000),
            attr("gen_ai.response.finish_reasons", ["end_turn"]),
            attr(
                "gen_ai.input.messages",
                json.dumps([{"role": "user", "parts": [{"type": "text", "content": "Summarize"}]}]),
            ),
            attr(
                "gen_ai.output.messages",
                json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": "Revenue grew"}]}]),
            ),
        ],
        "events": [
            {
                "name": "gen_ai.evaluation.result",
                "timeUnixNano": str(BASE_NS + 1_600_000_000),
                "attributes": [
                    attr("gen_ai.evaluation.name", "faithfulness"),
                    attr("gen_ai.evaluation.score.value", 0.9),
                    attr("gen_ai.evaluation.explanation", "Grounded in the report"),
                ],
            }
        ],
    }


def tool_span():
    return {
        "traceId": TRACE_ID,
        "spanId": TOOL,
        "parentSpanId": ROOT,
        "name": "execute_tool web_search",
        "startTimeUnixNano": str(BASE_NS + 1_600_000_000),
        "endTimeUnixNano": str(BASE_NS + 2_000_000_000),
        "attributes": [
            attr("gen_ai.operation.name", "execute_tool"),
            attr("gen_ai.tool.name", "web_search"),
            attr("gen_ai.tool.call.arguments", '{"q": "Q3 report"}'),
            attr("error.type", "TimeoutError"),
        ],
        "events": [
            {
                "name": "exception",
                "timeUnixNano": str(BASE_NS + 1_999_000_000),
                "attributes": [attr("exception.message", "search timed out")],
            }
        ],
        "status": {"code": 2},
    }


def test_genai_semconv_spans_become_traces_model_calls_tools_and_scores(db_url):
    store = create_store(db_url)
    result = store.ingest_spans(decode_json(otlp([root_span(), llm_span(), tool_span()])))

    assert result == {"spans": 3, "traces": 1, "trace_ids": [TRACE_ID]}
    trace = store.get_observable_trace(TRACE_ID)
    assert trace["workflow_name"] == "researcher"
    assert trace["status"] == "succeeded"
    assert trace["session_id"] == "session-42"
    assert trace["user_id"] == "user-7"
    assert trace["environment"] == "production"
    assert trace["source"] == "otlp"
    assert trace["duration_ms"] == pytest.approx(3000.0)
    assert trace["input"] == "What changed in the Q3 report?"

    # Sonnet 5 list price: $2/MTok input, $0.20/MTok cache read, $10/MTok output.
    call = store.list_model_calls(TRACE_ID)[0]
    assert call["model"] == "claude-sonnet-5"
    assert call["agent_name"] == "researcher"  # inherited from the parent agent span
    assert call["cached_tokens"] == 500_000
    assert call["estimated_cost"] == pytest.approx(0.5 * 2 + 0.5 * 0.2 + 0.1 * 10)
    assert call["prompt"]["prompt"][0]["role"] == "user"

    tool = store.list_tool_calls(TRACE_ID)[0]
    assert tool["tool_name"] == "web_search"
    assert tool["status"] == "failed"
    assert tool["error_message"] == "search timed out"
    assert tool["input"] == {"q": "Q3 report"}

    scores = store.list_scores(trace_id=TRACE_ID)
    assert scores[0]["name"] == "faithfulness"
    assert scores[0]["value"] == pytest.approx(0.9)
    assert scores[0]["source"] == "otel"

    event_types = [event["event_type"] for event in store.list_events(TRACE_ID)]
    assert "model.call" in event_types and "model.response" in event_types and "tool.failed" in event_types
    assert store.export_trace(TRACE_ID)["found"] is True
    assert store.list_agents()[0]["agent_name"] == "researcher"


def test_ingestion_is_idempotent_and_handles_children_before_root(db_url):
    store = create_store(db_url)
    store.ingest_spans(decode_json(otlp([llm_span()])))
    partial = store.get_observable_trace(TRACE_ID)
    assert partial["status"] == "running"
    assert partial["workflow_name"] == "support-bot"

    store.ingest_spans(decode_json(otlp([tool_span(), root_span()])))
    store.ingest_spans(decode_json(otlp([root_span(), llm_span(), tool_span()])))

    trace = store.get_observable_trace(TRACE_ID)
    assert trace["workflow_name"] == "researcher"
    assert trace["status"] == "succeeded"
    assert trace["span_count"] == 3
    assert len(store.list_model_calls(TRACE_ID)) == 1
    assert trace["estimated_cost"] == pytest.approx(2.1)
    assert [workflow["workflow_name"] for workflow in store.list_workflows()] == ["researcher"]


def test_openinference_and_vercel_ai_sdk_attributes(db_url):
    store = create_store(db_url)
    trace_id = "1" * 32
    spans = [
        {
            "traceId": trace_id,
            "spanId": "a" * 16,
            "name": "ai.generateText",
            "startTimeUnixNano": str(BASE_NS),
            "endTimeUnixNano": str(BASE_NS + 900_000_000),
            "attributes": [
                attr("ai.operationId", "ai.generateText"),
                attr("ai.usage.promptTokens", 1000),
                attr("ai.usage.completionTokens", 50),
                attr("ai.telemetry.metadata.sessionId", "vercel-session"),
            ],
        },
        {
            "traceId": trace_id,
            "spanId": "b" * 16,
            "parentSpanId": "a" * 16,
            "name": "ai.generateText.doGenerate",
            "startTimeUnixNano": str(BASE_NS + 10),
            "endTimeUnixNano": str(BASE_NS + 800_000_000),
            "attributes": [
                attr("ai.operationId", "ai.generateText.doGenerate"),
                attr("ai.model.provider", "openai.chat"),
                attr("ai.model.id", "gpt-4o-mini"),
                attr("ai.usage.promptTokens", 1000),
                attr("ai.usage.completionTokens", 50),
                attr("ai.response.text", "hello"),
            ],
        },
        {
            "traceId": trace_id,
            "spanId": "c" * 16,
            "parentSpanId": "a" * 16,
            "name": "retriever",
            "startTimeUnixNano": str(BASE_NS + 20),
            "endTimeUnixNano": str(BASE_NS + 30_000_000),
            "attributes": [
                attr("openinference.span.kind", "RETRIEVER"),
                attr("input.value", "refund policy"),
                attr("retrieval.documents.0.document.id", "doc-1"),
                attr("retrieval.documents.0.document.content", "Refunds within 30 days"),
                attr("retrieval.documents.0.document.score", 0.87),
            ],
        },
        {
            "traceId": trace_id,
            "spanId": "d" * 16,
            "parentSpanId": "a" * 16,
            "name": "ChatOpenAI",
            "startTimeUnixNano": str(BASE_NS + 40),
            "endTimeUnixNano": str(BASE_NS + 50_000_000),
            "attributes": [
                attr("openinference.span.kind", "LLM"),
                attr("llm.model_name", "gpt-4.1-mini"),
                attr("llm.provider", "openai"),
                attr("llm.token_count.prompt", 2000),
                attr("llm.token_count.completion", 100),
                attr("llm.input_messages.0.message.role", "user"),
                attr("llm.input_messages.0.message.content", "hi"),
            ],
        },
    ]
    store.ingest_spans(decode_json(otlp(spans)))

    calls = {call["model"]: call for call in store.list_model_calls(trace_id)}
    assert set(calls) == {"gpt-4o-mini", "gpt-4.1-mini"}  # outer ai.generateText is not double-counted
    assert calls["gpt-4o-mini"]["provider"] == "openai"
    assert calls["gpt-4.1-mini"]["prompt"]["prompt"] == [{"role": "user", "content": "hi"}]
    retrieval = store.list_rag_retrievals(trace_id)[0]
    assert retrieval["query"] == "refund policy"
    assert retrieval["chunk_ids"] == ["doc-1"]
    assert store.get_observable_trace(trace_id)["session_id"] == "vercel-session"


def test_capture_content_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTMESH_CAPTURE_CONTENT", "false")
    store = SQLiteStore(tmp_path / "agentmesh.db")
    store.ingest_spans(decode_json(otlp([root_span(), llm_span()])))

    call = store.list_model_calls(TRACE_ID)[0]
    assert call["prompt"] == {"system": None, "prompt": None}
    assert call["output"] is None
    assert call["total_tokens"] == 1_100_000
    assert "gen_ai.input.messages" not in json.dumps(store.list_spans(TRACE_ID))


def test_otlp_http_endpoint_accepts_json_gzip_and_requires_auth(db_url, monkeypatch):
    db_path = db_url
    client = TestClient(create_app(db_path))
    body = json.dumps(otlp([root_span(), llm_span(), tool_span()])).encode()

    response = client.post(
        "/v1/traces",
        content=gzip.compress(body),
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.json() == {"partialSuccess": {}}
    assert client.get(f"/api/traces/{TRACE_ID}").json()["trace"]["workflow_name"] == "researcher"
    assert client.get("/api/traces", params={"session_id": "session-42"}).json()[0]["trace_id"] == TRACE_ID
    assert client.get("/api/sessions").json()[0]["session_id"] == "session-42"
    assert client.get("/api/sessions/session-42").json()["trace_count"] == 1
    insights = client.get(f"/api/traces/{TRACE_ID}/insights").json()
    assert insights["findings"][0]["kind"] == "root_cause"
    assert (
        client.post("/v1/traces", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 400
    )

    monkeypatch.setenv("AGENTMESH_AUTH_MODE", "api_key")
    monkeypatch.setenv("AGENTMESH_API_KEY", "secret-key")
    secured = TestClient(create_app(db_path))
    assert secured.post("/v1/traces", content=body, headers={"Content-Type": "application/json"}).status_code == 401
    assert (
        secured.post(
            "/v1/traces",
            content=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret-key"},
        ).status_code
        == 200
    )
    assert secured.get("/api/sessions", headers={"x-agentmesh-api-key": "secret-key"}).status_code == 200


def test_scores_api_round_trip(db_url):
    db_path = db_url
    create_store(db_path).ingest_spans(decode_json(otlp([root_span()])))
    client = TestClient(create_app(db_path))

    created = client.post(
        "/api/scores",
        json={"trace_id": TRACE_ID, "name": "thumbs", "value": True, "comment": "great", "source": "feedback"},
    )
    second = client.post("/api/scores", json={"trace_id": TRACE_ID, "name": "helpfulness", "value": 0.4})
    assert created.status_code == 200 and second.status_code == 200
    assert created.json()["score_id"] != second.json()["score_id"]

    scores = {score["name"]: score for score in client.get(f"/api/traces/{TRACE_ID}/scores").json()}
    assert scores["thumbs"]["value"] == 1.0 and scores["thumbs"]["passed"] is True
    assert scores["thumbs"]["comment"] == "great"
    assert scores["helpfulness"]["value"] == pytest.approx(0.4)
    assert client.post("/api/scores", json={"trace_id": TRACE_ID, "name": ""}).status_code == 422
    assert client.get(f"/api/traces/{TRACE_ID}").json()["scores"]


def test_encode_decode_round_trip():
    spans = decode_json(otlp([root_span(), llm_span(), tool_span()]))
    again = decode_json(encode_json(spans, spans[0].resource))
    assert [(span.span_id, span.parent_span_id, span.status, span.start_time, span.end_time) for span in again] == [
        (span.span_id, span.parent_span_id, span.status, span.start_time, span.end_time) for span in spans
    ]
    assert again[1].attributes["gen_ai.usage.input_tokens"] == 1_000_000
    assert again[1].attributes["gen_ai.response.finish_reasons"] == ["end_turn"]


def test_prune_removes_old_traces(db_url):
    store = create_store(db_url)
    store.ingest_spans(decode_json(otlp([root_span(), llm_span(), tool_span()])))
    dry = store.prune_traces("2099-01-01T00:00:00+00:00", dry_run=True)
    assert dry["traces"] == 1 and store.get_observable_trace(TRACE_ID) is not None
    none = store.prune_traces("2000-01-01T00:00:00+00:00")
    assert none["traces"] == 0
    pruned = store.prune_traces("2099-01-01T00:00:00+00:00")
    assert pruned["deleted_rows"]["spans"] == 3
    assert store.get_observable_trace(TRACE_ID) is None
    assert store.list_model_calls(TRACE_ID) == []
    assert store.list_events(TRACE_ID) == []


@pytest.fixture
def live_server(tmp_path):
    uvicorn = pytest.importorskip("uvicorn")
    db_path = tmp_path / "live.db"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(db_path), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}", db_path
    server.should_exit = True
    thread.join(timeout=10)


def test_real_opentelemetry_python_exporter_protobuf(live_server):
    pytest.importorskip("opentelemetry.proto")
    exporter_module = pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    base_url, db_path = live_server
    provider = TracerProvider(resource=Resource.create({"service.name": "otel-python-app"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter_module.OTLPSpanExporter(endpoint=f"{base_url}/v1/traces")))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span(
        "invoke_agent planner", attributes={"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "planner"}
    ) as root:
        with tracer.start_as_current_span(
            "chat gpt-4.1",
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": "openai",
                "gen_ai.request.model": "gpt-4.1",
                "gen_ai.usage.input_tokens": 10_000,
                "gen_ai.usage.output_tokens": 1_000,
            },
        ):
            pass
        with tracer.start_as_current_span(
            "execute_tool calculator",
            attributes={"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "calculator"},
        ) as tool:
            tool.set_status(Status(StatusCode.ERROR, "division by zero"))
        trace_id = format(root.get_span_context().trace_id, "032x")
    provider.force_flush()
    provider.shutdown()

    store = SQLiteStore(db_path)
    trace = store.get_observable_trace(trace_id)
    assert trace is not None and trace["workflow_name"] == "planner"
    assert trace["service_name"] == "otel-python-app"
    call = store.list_model_calls(trace_id)[0]
    assert call["estimated_cost"] == pytest.approx((10_000 * 2 + 1_000 * 8) / 1_000_000)
    assert store.list_tool_calls(trace_id)[0]["error_message"] == "division by zero"


def test_workflow_list_counts_runs_not_model_calls(db_url):
    store = create_store(db_url)
    second_llm = {**llm_span(), "spanId": "2222222222222222"}
    store.ingest_spans(decode_json(otlp([root_span(), llm_span(), second_llm, tool_span()])))

    workflow = store.list_workflows()[0]
    assert workflow["runs"] == 1
    assert workflow["failed_runs"] == 0
    assert workflow["total_cost"] == pytest.approx(4.2)
