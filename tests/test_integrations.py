import asyncio
import json

import pytest

import agentmesh
from agentmesh import InMemoryExporter

httpx2 = pytest.importorskip("httpx2")


@pytest.fixture
def memory():
    exporter = InMemoryExporter()
    agentmesh.init(exporter=exporter)
    yield exporter
    agentmesh.uninstrument_openai()
    agentmesh.uninstrument_anthropic()
    agentmesh.shutdown()


def _sse(events):
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

ANTHROPIC_MESSAGE = {
    "id": "msg_01",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5",
    "content": [{"type": "text", "text": "Paris."}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 0,
    },
}

ANTHROPIC_STREAM = [
    {
        "type": "message_start",
        "message": {
            **ANTHROPIC_MESSAGE,
            "content": [],
            "stop_reason": None,
            "usage": {
                "input_tokens": 50,
                "output_tokens": 1,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 200,
            },
        },
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 12},
    },
    {"type": "message_stop"},
]


def _anthropic_transport():
    def handler(request):
        body = json.loads(request.content)
        if body.get("stream"):
            return httpx2.Response(200, text=_sse(ANTHROPIC_STREAM), headers={"content-type": "text/event-stream"})
        if body.get("model") == "claude-broken":
            return httpx2.Response(
                529, json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
            )
        return httpx2.Response(200, json=ANTHROPIC_MESSAGE)

    return handler


def test_anthropic_create_stream_and_helper_are_traced(memory):
    anthropic = pytest.importorskip("anthropic")
    agentmesh.instrument_anthropic()
    client = anthropic.Anthropic(
        api_key="test", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(_anthropic_transport()))
    )

    with agentmesh.trace("anthropic-app"):
        message = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=100,
            system="Be terse.",
            messages=[{"role": "user", "content": "Capital of France?"}],
        )
        streamed = "".join(
            event.delta.text
            for event in client.messages.create(
                model="claude-sonnet-5", max_tokens=100, messages=[{"role": "user", "content": "hi"}], stream=True
            )
            if event.type == "content_block_delta"
        )
        with client.messages.stream(
            model="claude-sonnet-5", max_tokens=100, messages=[{"role": "user", "content": "hi"}]
        ) as stream:
            helper_text = stream.get_final_text()
        with pytest.raises(anthropic.APIStatusError):
            client.messages.create(model="claude-broken", max_tokens=10, messages=[{"role": "user", "content": "x"}])

    agentmesh.flush()
    assert message.content[0].text == "Paris." and streamed == "Hello" and helper_text == "Hello"
    llm_spans = [span for span in memory.spans if span.attributes.get("gen_ai.operation.name") == "chat"]
    assert len(llm_spans) == 4
    first, stream_span, helper_span, failed = llm_spans
    root = next(span for span in memory.spans if span.name == "anthropic-app")
    assert {span.parent_span_id for span in llm_spans} == {root.span_id}

    assert first.attributes["gen_ai.provider.name"] == "anthropic"
    assert first.attributes["gen_ai.usage.input_tokens"] == 1000  # 100 uncached + 900 cache reads
    assert first.attributes["gen_ai.usage.cache_read.input_tokens"] == 900
    assert first.attributes["gen_ai.response.finish_reasons"] == ["end_turn"]
    assert first.attributes["gen_ai.system_instructions"] == "Be terse."
    assert "Capital of France?" in first.attributes["gen_ai.input.messages"]

    for span in (stream_span, helper_span):
        assert span.attributes["gen_ai.usage.input_tokens"] == 250
        assert span.attributes["gen_ai.usage.cache_write.input_tokens"] == 200
        assert span.attributes["gen_ai.usage.output_tokens"] == 12
        assert "Hello" in span.attributes["gen_ai.output.messages"]
        assert span.end_time is not None

    assert failed.status == "error"
    assert failed.attributes["error.type"] == "InternalServerError" or "Error" in failed.attributes["error.type"]


def test_anthropic_async_client_instance_instrumentation(memory):
    anthropic = pytest.importorskip("anthropic")

    async def handler(request):
        return _anthropic_transport()(request)

    client = anthropic.AsyncAnthropic(
        api_key="test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    agentmesh.instrument_anthropic(client)
    agentmesh.instrument_anthropic(client)  # idempotent

    async def main():
        await client.messages.create(
            model="claude-sonnet-5", max_tokens=10, messages=[{"role": "user", "content": "hi"}]
        )
        stream = await client.messages.create(
            model="claude-sonnet-5", max_tokens=10, messages=[{"role": "user", "content": "hi"}], stream=True
        )
        async for _event in stream:
            pass

    asyncio.run(main())
    agentmesh.flush()
    assert [span.attributes["gen_ai.usage.output_tokens"] for span in memory.spans] == [20, 12]


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

CHAT_COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4.1-mini-2025-04-14",
    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "4"}}],
    "usage": {
        "prompt_tokens": 1000,
        "completion_tokens": 10,
        "total_tokens": 1010,
        "prompt_tokens_details": {"cached_tokens": 600},
        "completion_tokens_details": {"reasoning_tokens": 0},
    },
}


def _chat_chunks():
    base = {"id": "chatcmpl-2", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o-mini"}
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hi"}, "finish_reason": None}]},
        {
            **base,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"q":'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            **base,
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' "x"}'}}]},
                    "finish_reason": "tool_calls",
                }
            ],
        },
        {**base, "choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48}},
    ]
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


RESPONSE = {
    "id": "resp_1",
    "object": "response",
    "created_at": 1,
    "status": "completed",
    "model": "gpt-5",
    "output": [
        {
            "type": "message",
            "id": "m1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "done", "annotations": []}],
        }
    ],
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
    "usage": {
        "input_tokens": 500,
        "output_tokens": 300,
        "total_tokens": 800,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 250},
    },
}


def _openai_handler(request):
    path = request.url.path
    body = json.loads(request.content)
    if path.endswith("/chat/completions"):
        if body.get("stream"):
            return httpx2.Response(200, text=_chat_chunks(), headers={"content-type": "text/event-stream"})
        return httpx2.Response(200, json=CHAT_COMPLETION)
    if path.endswith("/responses"):
        return httpx2.Response(200, json=RESPONSE)
    if path.endswith("/embeddings"):
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            },
        )
    return httpx2.Response(404, json={"error": {"message": "not found"}})


def test_openai_chat_streaming_responses_and_embeddings(memory, tmp_path):
    openai = pytest.importorskip("openai")
    agentmesh.instrument_openai()
    agentmesh.instrument_openai()  # idempotent
    client = openai.OpenAI(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(_openai_handler)))

    with agentmesh.trace("openai-app") as root:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini", messages=[{"role": "user", "content": "2+2?"}], temperature=0
        )
        chunks = list(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
                stream_options={"include_usage": True},
            )
        )
        response = client.responses.create(model="gpt-5", input="Plan the migration", reasoning={"effort": "high"})
        client.embeddings.create(model="text-embedding-3-small", input="hello")

    agentmesh.flush()
    assert completion.choices[0].message.content == "4" and len(chunks) == 4 and response.output_text == "done"
    spans = [span for span in memory.spans if span.parent_span_id == root.span_id]
    chat, stream, responses, embeddings = spans

    assert chat.name == "chat gpt-4.1-mini"
    assert chat.attributes["gen_ai.response.model"] == "gpt-4.1-mini-2025-04-14"
    assert chat.attributes["gen_ai.usage.cache_read.input_tokens"] == 600
    assert chat.attributes["gen_ai.request.temperature"] == 0

    assert stream.attributes["gen_ai.usage.input_tokens"] == 40
    assert stream.attributes["gen_ai.response.finish_reasons"] == ["tool_calls"]
    output = json.loads(stream.attributes["gen_ai.output.messages"])
    assert output[0]["content"] == "Hi"
    assert output[0]["tool_calls"][0]["function"] == {"name": "lookup", "arguments": '{"q": "x"}'}

    assert responses.attributes["gen_ai.usage.reasoning.output_tokens"] == 250
    assert responses.attributes["gen_ai.request.reasoning.level"] == "high"
    assert embeddings.kind == "CLIENT" and embeddings.attributes["gen_ai.embeddings.dimension.count"] == 3

    # The spans land in the dashboard tables with correct costs.
    from agentmesh.storage import SQLiteStore

    store = SQLiteStore(tmp_path / "integration.db")
    store.ingest_spans(memory.spans, source="sdk")
    costs = {call["model"]: call["estimated_cost"] for call in store.list_model_calls(root.trace_id)}
    assert costs["gpt-4.1-mini-2025-04-14"] == pytest.approx((400 * 0.40 + 600 * 0.10 + 10 * 1.60) / 1_000_000)
    assert costs["gpt-5"] == pytest.approx((500 * 1.25 + 300 * 10) / 1_000_000)

    agentmesh.uninstrument_openai()
    client.chat.completions.create(model="gpt-4.1-mini", messages=[{"role": "user", "content": "untraced"}])
    agentmesh.flush()
    assert len(memory.spans) == 5
