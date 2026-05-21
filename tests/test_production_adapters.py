import pytest

from agentmesh import AsyncEventBus, TraceRecorder, create_store
from agentmesh.brokers import NATSEventBus, RedisEventBus
from agentmesh.dependencies import optional_import
from agentmesh.errors import AgentMeshError
from agentmesh.storage import SQLiteStore


@pytest.mark.asyncio
async def test_async_event_bus_still_supports_local_publish_subscribe():
    bus = AsyncEventBus()
    seen = []

    async def handler(event):
        seen.append(event.event_type)

    bus.subscribe("workflow.start", handler)
    event = await bus.publish("workflow.start", {"ok": True}, "trace_1")

    assert event.event_type == "workflow.start"
    assert seen == ["workflow.start"]
    assert (await bus.next_event()).payload == {"ok": True}


def test_optional_brokers_can_be_constructed_without_services():
    redis_bus = RedisEventBus("redis://localhost:6379/0")
    nats_bus = NATSEventBus(["nats://localhost:4222"])

    assert redis_bus.channel == "agentmesh.events"
    assert nats_bus.subject == "agentmesh.events"


def test_missing_optional_dependency_has_install_hint():
    with pytest.raises(AgentMeshError) as error:
        optional_import("agentmesh_definitely_missing_dependency", "example")

    assert "pip install -e '.[example]'" in str(error.value)


def test_create_store_uses_sqlite_for_paths(tmp_path):
    store = create_store(tmp_path / "agentmesh.db")

    assert isinstance(store, SQLiteStore)


def test_trace_recorder_forwards_events_to_otel_bridge(tmp_path):
    class FakeBridge:
        def __init__(self):
            self.events = []

        def record_event(self, **kwargs):
            self.events.append(kwargs)

    bridge = FakeBridge()
    store = SQLiteStore(tmp_path / "agentmesh.db")
    recorder = TraceRecorder(store, otel=bridge)

    trace_id = recorder.start_workflow("otel-test", {})

    assert trace_id
    assert bridge.events[0]["event_type"] == "workflow.started"
    assert bridge.events[0]["actor"] == "workflow"

