from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentmesh.types import JsonObject


class Evaluator(Protocol):
    name: str

    def evaluate(self, expected: str, actual: str) -> JsonObject:
        raise NotImplementedError


@dataclass(slots=True)
class ContainsEvaluator:
    name: str = "contains"

    def evaluate(self, expected: str, actual: str) -> JsonObject:
        passed = expected.lower() in actual.lower()
        return {"name": self.name, "passed": passed, "expected": expected, "actual": actual}


class RunComparator:
    def compare(self, left_events: list[JsonObject], right_events: list[JsonObject]) -> JsonObject:
        left_types = [str(event.get("event_type", "")) for event in left_events]
        right_types = [str(event.get("event_type", "")) for event in right_events]
        return {
            "left_event_count": len(left_events),
            "right_event_count": len(right_events),
            "event_types_match": left_types == right_types,
            "left_event_types": left_types,
            "right_event_types": right_types,
        }

