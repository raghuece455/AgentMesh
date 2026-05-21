from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from agentmesh.types import JsonObject, new_id, utc_now


class MessageType(str, Enum):
    TASK = "task"
    RESULT = "result"
    EVENT = "event"
    DELEGATION = "delegation"
    APPROVAL = "approval"
    ERROR = "error"


@dataclass(slots=True)
class AgentMessage:
    sender: str
    recipient: str
    payload: JsonObject
    message_type: MessageType = MessageType.TASK
    trace_id: str = ""
    task_id: str = ""
    parent_id: str | None = None
    id: str = field(default_factory=lambda: new_id("msg"))
    created_at: str = field(default_factory=utc_now)

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "message_type": self.message_type.value,
            "payload": self.payload,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
        }

