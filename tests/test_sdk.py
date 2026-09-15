import asyncio
import json

import pytest

import agentmesh
from agentmesh import InMemoryExporter
from agentmesh.storage import SQLiteStore


@pytest.fixture
def memory():
    exporter = InMemoryExporter()
    agentmesh.init(exporter=exporter, service_name="sdk-test")
    yield exporter
    agentmesh.shutdown()


def _by_name(exporter):
    agentmesh.flush()
    return {span.name: span for span in exporter.spans}


def test_observe_builds_a_nested_trace_with_session_and_errors(memory):
    @agentmesh.observe(kind="tool", name="lookup_order")
    def lookup_order(order_id: str) -> dict:
        return {"order_id": order_id, "status": "shipped"}

    @agentmesh.observe(kind="tool", name="refund")
    def refund(order_id: str) -> None:
        raise PermissionError("refunds need approval")

    @agentmesh.observe(kind="agent", name="support_agent")
    def support_agent(question: str) -> str:
        order = lookup_order("A-1")
        with pytest.raises(PermissionError):
            refund("A-1")
        return f"Order is {order['status']}"

    with agentmesh.trace("ticket", session_id="chat-1", user_id="u-1", tags=["beta"]) as root:
        answer = support_agent("where is my order?")
        root.set_output(answer)

    spans = _by_name(memory)
    assert set(spans) == {"ticket", "support_agent", "lookup_order", "refund"}
    tool = spans["lookup_order"]
    agent = spans["support_agent"]
    assert len({span.trace_id for span in spans.values()}) == 1
    assert spans["ticket"].parent_span_id is None
    assert agent.parent_span_id == spans["ticket"].span_id
    assert tool.parent_span_id == agent.span_id
    assert tool.attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool.attributes["input.value"] == "A-1"
    assert json.loads(tool.attributes["output.value"]) == {"order_id": "A-1", "status": "shipped"}
    assert agent.attributes["gen_ai.agent.name"] == "support_agent"
    assert all(span.attributes["gen_ai.conversation.id"] == "chat-1" for span in spans.values())
    assert spans["refund"].status == "error"
    assert spans["refund"].attributes["error.type"] == "PermissionError"
    assert spans["refund"].events[0]["name"] == "exception"
    assert spans["ticket"].resource["service.name"] == "sdk-test"


def test_async_concurrency_keeps_parents_straight(memory):
    @agentmesh.observe(kind="tool")
    async def fetch(source: str) -> str:
        await asyncio.sleep(0.01)
        return source.upper()

    @agentmesh.observe(kind="agent", name="researcher")
    async def researcher() -> list[str]:
        return list(await asyncio.gather(fetch("a"), fetch("b"), fetch("c")))

    async def main():
        async with agentmesh.trace("parallel-research"):
            return await asyncio.gather(researcher(), researcher())

    asyncio.run(main())
    agentmesh.flush()
    agents = [span for span in memory.spans if span.name == "researcher"]
    fetches = [span for span in memory.spans if span.name.endswith("fetch")]
    assert len(agents) == 2 and len(fetches) == 6
    agent_ids = {span.span_id for span in agents}
    assert {span.parent_span_id for span in fetches} == agent_ids
    assert sum(1 for span in fetches if span.parent_span_id == agents[0].span_id) == 3


def test_generators_manual_spans_usage_and_scores(memory):
    @agentmesh.observe(name="stream_tokens")
    def stream_tokens():
        with agentmesh.span("inner", kind="retrieval"):
            pass
        yield "hel"
        yield "lo"

    with agentmesh.trace("streaming") as root:
        assert "".join(stream_tokens()) == "hello"
        with agentmesh.span("chat claude-haiku-4-5", kind="llm") as llm:
            llm.set_model("claude-haiku-4-5", provider="anthropic", temperature=0.1)
            llm.set_usage(1200, 300, cache_read_tokens=1000)
        agentmesh.score("user_feedback", 1, comment="nice")
        trace_id = root.trace_id

    spans = _by_name(memory)
    assert json.loads(spans["stream_tokens"].attributes["output.value"]) == ["hel", "lo"]
    assert spans["inner"].parent_span_id == spans["stream_tokens"].span_id
    assert spans["chat claude-haiku-4-5"].attributes["gen_ai.usage.cache_read.input_tokens"] == 1000
    assert spans["chat claude-haiku-4-5"].kind == "CLIENT"
    assert memory.scores == [
        {
            "trace_id": trace_id,
            "span_id": None,
            "name": "user_feedback",
            "value": 1,
            "comment": "nice",
            "label": None,
            "source": "sdk",
        }
    ]


def test_capture_content_off_and_disabled_tracing(tmp_path):
    exporter = InMemoryExporter()
    agentmesh.init(exporter=exporter, capture_content=False)

    @agentmesh.observe
    def secret(password: str) -> str:
        return "token"

    secret("hunter2")
    agentmesh.flush()
    assert "input.value" not in exporter.spans[0].attributes
    assert "output.value" not in exporter.spans[0].attributes

    disabled = InMemoryExporter()
    agentmesh.init(exporter=disabled, enabled=False)
    secret("x")
    agentmesh.flush()
    assert disabled.spans == []
    agentmesh.shutdown()


def test_local_store_exporter_writes_to_dashboard_tables(tmp_path):
    db_path = str(tmp_path / "sdk.db")
    agentmesh.init(db_path=db_path, service_name="local-app", environment="dev")

    @agentmesh.observe(kind="llm", name="chat gpt-4o")
    def call_model(prompt: str) -> str:
        current = agentmesh.get_current_span()
        current.set_model("gpt-4o", provider="openai")
        current.set_usage(2000, 500)
        return "answer"

    with agentmesh.trace("local-run", session_id="s-1") as root:
        call_model("hello")
        agentmesh.score("correct", True)
    assert agentmesh.flush()
    agentmesh.shutdown()

    store = SQLiteStore(db_path)
    trace = store.get_observable_trace(root.trace_id)
    assert trace["workflow_name"] == "local-run"
    assert trace["source"] == "sdk"
    assert trace["environment"] == "dev"
    assert trace["session_id"] == "s-1"
    call = store.list_model_calls(root.trace_id)[0]
    assert call["estimated_cost"] == pytest.approx((2000 * 2.5 + 500 * 10) / 1_000_000)
    assert store.list_scores(trace_id=root.trace_id)[0]["name"] == "correct"


@pytest.fixture
def server(tmp_path):
    import socket
    import threading
    import time

    uvicorn = pytest.importorskip("uvicorn")
    from agentmesh.dashboard import create_app

    db_path = tmp_path / "remote.db"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    instance = uvicorn.Server(uvicorn.Config(create_app(db_path), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not instance.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", db_path
    instance.should_exit = True
    thread.join(timeout=10)


def test_sdk_http_mode_round_trip(server):
    base_url, db_path = server
    agentmesh.init(endpoint=base_url, service_name="remote-app")

    @agentmesh.observe(kind="tool")
    def add(a: int, b: int) -> int:
        return a + b

    with agentmesh.trace("remote-trace", user_id="u-9") as root:
        add(2, 3)
        agentmesh.score("quality", 0.75, comment="ok")
    assert agentmesh.flush()
    agentmesh.shutdown()

    store = SQLiteStore(db_path)
    trace = store.get_observable_trace(root.trace_id)
    assert trace["workflow_name"] == "remote-trace"
    assert trace["user_id"] == "u-9"
    assert trace["service_name"] == "remote-app"
    assert store.list_tool_calls(root.trace_id)[0]["input"] == {"a": 2, "b": 3}
    assert store.list_scores(trace_id=root.trace_id)[0]["value"] == pytest.approx(0.75)


def test_export_failures_never_raise(caplog):
    agentmesh.init(endpoint="http://127.0.0.1:9", service_name="offline")

    @agentmesh.observe
    def work() -> int:
        return 42

    assert work() == 42
    assert agentmesh.flush(timeout=30)
    agentmesh.shutdown()
