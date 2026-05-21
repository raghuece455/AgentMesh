from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agentmesh.storage import SQLiteStore
from agentmesh.types import JsonObject, JsonValue


@dataclass(slots=True)
class WorkflowMemory:
    values: dict[str, JsonValue] = field(default_factory=dict)

    def set(self, key: str, value: JsonValue) -> None:
        self.values[key] = value

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        return self.values.get(key, default)

    def to_json(self) -> JsonObject:
        return {"values": self.values}


class MemoryStore(Protocol):
    def put(self, agent: str, namespace: str, key: str, value: JsonValue, trace_id: str | None = None) -> int:
        raise NotImplementedError

    def get(
        self,
        agent: str,
        namespace: str,
        key: str,
        version: int | None = None,
        trace_id: str | None = None,
    ) -> JsonValue:
        raise NotImplementedError

    def versions(self, agent: str, namespace: str, key: str) -> list[JsonObject]:
        raise NotImplementedError


class SQLiteMemoryStore:
    def __init__(self, store: SQLiteStore, recorder: object | None = None) -> None:
        self.store = store
        self.recorder = recorder

    def put(self, agent: str, namespace: str, key: str, value: JsonValue, trace_id: str | None = None) -> int:
        version = self.store.save_memory(agent, namespace, key, value, trace_id)
        self.store.audit(trace_id, agent, "memory.put", f"{namespace}:{key}", {"version": version})
        if trace_id is not None and self.recorder is not None:
            self.recorder.event(
                trace_id,
                "memory.write",
                agent,
                {"namespace": namespace, "key": key, "version": version, "value": value},
            )
        return version

    def get(
        self,
        agent: str,
        namespace: str,
        key: str,
        version: int | None = None,
        trace_id: str | None = None,
    ) -> JsonValue:
        value = self.store.get_memory(agent, namespace, key, version)
        if trace_id is not None and self.recorder is not None:
            self.recorder.event(
                trace_id,
                "memory.read",
                agent,
                {"namespace": namespace, "key": key, "version": version, "value": value},
            )
        return value

    def versions(self, agent: str, namespace: str, key: str) -> list[JsonObject]:
        return self.store.list_memory_versions(agent, namespace, key)
