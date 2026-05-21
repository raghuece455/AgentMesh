from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from agentmesh.dependencies import optional_import
from agentmesh.event_bus import AsyncEventBus, EventEnvelope, EventHandler
from agentmesh.types import JsonObject, dumps_json, loads_json


class RedisEventBus(AsyncEventBus):
    def __init__(self, url: str = "redis://localhost:6379/0", channel: str = "agentmesh.events") -> None:
        super().__init__()
        self.url = url
        self.channel = channel
        self._redis: object | None = None
        self._listener_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        redis_module = optional_import("redis.asyncio", "redis")
        self._redis = redis_module.from_url(self.url)

    async def close(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
        if self._redis is not None:
            await self._redis.aclose()

    async def publish(self, event_type: str, payload: JsonObject, trace_id: str = "") -> EventEnvelope:
        event = await super().publish(event_type, payload, trace_id)
        if self._redis is None:
            await self.connect()
        await self._redis.publish(self.channel, dumps_json(event.to_json()))
        return event

    def start_listener(self) -> None:
        if self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        if self._redis is None:
            await self.connect()
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self.channel)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            payload = loads_json(message.get("data").decode("utf-8"))
            if isinstance(payload, dict):
                event = EventEnvelope(
                    event_type=str(payload["event_type"]),
                    payload=payload.get("payload", {}) if isinstance(payload.get("payload", {}), dict) else {},
                    trace_id=str(payload.get("trace_id", "")),
                    id=str(payload.get("id", "")),
                    created_at=str(payload.get("created_at", "")),
                )
                self.history.append(event)
                await self._queue.put(event)


class NATSEventBus(AsyncEventBus):
    def __init__(self, servers: list[str] | None = None, subject: str = "agentmesh.events") -> None:
        super().__init__()
        self.servers = servers or ["nats://localhost:4222"]
        self.subject = subject
        self._client: object | None = None

    async def connect(self) -> None:
        nats_module = optional_import("nats", "nats")
        self._client = await nats_module.connect(servers=self.servers)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def publish(self, event_type: str, payload: JsonObject, trace_id: str = "") -> EventEnvelope:
        event = await super().publish(event_type, payload, trace_id)
        if self._client is None:
            await self.connect()
        await self._client.publish(self.subject, dumps_json(event.to_json()).encode("utf-8"))
        return event

    async def subscribe_remote(self, handler: EventHandler | None = None) -> None:
        if self._client is None:
            await self.connect()

        async def callback(message: object) -> None:
            decoded = loads_json(message.data.decode("utf-8"))
            if not isinstance(decoded, dict):
                return
            event = EventEnvelope(
                event_type=str(decoded["event_type"]),
                payload=decoded.get("payload", {}) if isinstance(decoded.get("payload", {}), dict) else {},
                trace_id=str(decoded.get("trace_id", "")),
                id=str(decoded.get("id", "")),
                created_at=str(decoded.get("created_at", "")),
            )
            self.history.append(event)
            await self._queue.put(event)
            if handler is not None:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result

        await self._client.subscribe(self.subject, cb=callback)

