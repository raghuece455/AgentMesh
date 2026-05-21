from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from agentmesh.types import JsonObject


class ErrorKind(str, Enum):
    VALIDATION = "validation"
    WORKFLOW = "workflow"
    MODEL = "model"
    TOOL = "tool"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    BUDGET = "budget"
    STORAGE = "storage"
    SECURITY = "security"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class AgentMeshError(Exception):
    message: str
    kind: ErrorKind = ErrorKind.UNKNOWN
    details: JsonObject = field(default_factory=dict)
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.message}"

    def to_json(self) -> JsonObject:
        return {
            "message": self.message,
            "kind": self.kind.value,
            "details": self.details,
            "retryable": self.retryable,
        }


class PermissionDenied(AgentMeshError):
    def __init__(self, message: str, details: JsonObject | None = None) -> None:
        super().__init__(message, ErrorKind.PERMISSION, details or {}, retryable=False)


class BudgetExceeded(AgentMeshError):
    def __init__(self, message: str, details: JsonObject | None = None) -> None:
        super().__init__(message, ErrorKind.BUDGET, details or {}, retryable=False)


class WorkflowCancelled(AgentMeshError):
    def __init__(self, message: str = "Workflow was cancelled") -> None:
        super().__init__(message, ErrorKind.WORKFLOW, {}, retryable=False)


def classify_error(error: BaseException) -> AgentMeshError:
    if isinstance(error, AgentMeshError):
        return error
    if isinstance(error, TimeoutError):
        return AgentMeshError(str(error) or "Operation timed out", ErrorKind.TIMEOUT, {}, retryable=True)
    return AgentMeshError(str(error) or type(error).__name__, ErrorKind.UNKNOWN, {}, retryable=False)

