from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from agentmesh.types import JsonObject, new_id, utc_now


@dataclass(slots=True)
class EventEnvelope:
    event_type: str
    payload: JsonObject
    trace_id: str = ""
    id: str = field(default_factory=lambda: new_id("bus"))
    created_at: str = field(default_factory=utc_now)

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at,
        }


EventHandler = Callable[[EventEnvelope], Awaitable[None] | None]


class AsyncEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        self.history: list[EventEnvelope] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event_type: str, payload: JsonObject, trace_id: str = "") -> EventEnvelope:
        event = EventEnvelope(event_type=event_type, payload=payload, trace_id=trace_id)
        self.history.append(event)
        await self._queue.put(event)
        for handler in [*self._subscribers.get(event_type, []), *self._subscribers.get("*", [])]:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result
        return event

    async def next_event(self) -> EventEnvelope:
        return await self._queue.get()

    def empty(self) -> bool:
        return self._queue.empty()

