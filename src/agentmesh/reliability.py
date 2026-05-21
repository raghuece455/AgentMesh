from __future__ import annotations

import asyncio
import random
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from agentmesh.errors import BudgetExceeded, ErrorKind, AgentMeshError
from agentmesh.types import JsonObject


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 2
    initial_delay_seconds: float = 0.1
    backoff_factor: float = 2.0
    retryable_kinds: tuple[ErrorKind, ...] = (
        ErrorKind.MODEL,
        ErrorKind.TOOL,
        ErrorKind.TIMEOUT,
        ErrorKind.RATE_LIMIT,
        ErrorKind.UNKNOWN,
    )

    def delay_for(self, attempt_index: int) -> float:
        base = self.initial_delay_seconds * (self.backoff_factor ** max(attempt_index - 1, 0))
        # Full-jitter: avoids thundering herd when many workflows retry simultaneously.
        return random.uniform(0, base)

    def can_retry(self, error: AgentMeshError, attempt: int) -> bool:
        return attempt < self.max_attempts and (error.retryable or error.kind in self.retryable_kinds)

    def to_json(self) -> JsonObject:
        return {
            "max_attempts": self.max_attempts,
            "initial_delay_seconds": self.initial_delay_seconds,
            "backoff_factor": self.backoff_factor,
            "retryable_kinds": [kind.value for kind in self.retryable_kinds],
        }


class BudgetLimiter:
    """Thread-safe budget enforcer shared across parallel agents in the same workflow run."""

    def __init__(
        self,
        max_prompt_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        max_total_tokens: int | None = None,
        max_cost_usd: float | None = None,
    ) -> None:
        self.max_prompt_tokens = max_prompt_tokens
        self.max_completion_tokens = max_completion_tokens
        self.max_total_tokens = max_total_tokens
        self.max_cost_usd = max_cost_usd
        self.used_prompt_tokens: int = 0
        self.used_completion_tokens: int = 0
        self.used_cost_usd: float = 0.0
        self._lock = threading.Lock()

    def reserve(self, prompt_tokens: int, completion_tokens: int, cost_usd: float) -> None:
        # Hold the lock for the full check-then-update so parallel agents can't
        # both pass the budget check and then overspend together.
        with self._lock:
            next_prompt = self.used_prompt_tokens + prompt_tokens
            next_completion = self.used_completion_tokens + completion_tokens
            next_total = next_prompt + next_completion
            next_cost = self.used_cost_usd + cost_usd
            if self.max_prompt_tokens is not None and next_prompt > self.max_prompt_tokens:
                raise BudgetExceeded("Prompt token budget exceeded", {"limit": self.max_prompt_tokens, "used": next_prompt})
            if self.max_completion_tokens is not None and next_completion > self.max_completion_tokens:
                raise BudgetExceeded(
                    "Completion token budget exceeded",
                    {"limit": self.max_completion_tokens, "used": next_completion},
                )
            if self.max_total_tokens is not None and next_total > self.max_total_tokens:
                raise BudgetExceeded("Total token budget exceeded", {"limit": self.max_total_tokens, "used": next_total})
            if self.max_cost_usd is not None and next_cost > self.max_cost_usd:
                raise BudgetExceeded("Cost budget exceeded", {"limit": self.max_cost_usd, "used": next_cost})
            self.used_prompt_tokens = next_prompt
            self.used_completion_tokens = next_completion
            self.used_cost_usd = next_cost

    def to_json(self) -> JsonObject:
        with self._lock:
            return {
                "max_prompt_tokens": self.max_prompt_tokens,
                "max_completion_tokens": self.max_completion_tokens,
                "max_total_tokens": self.max_total_tokens,
                "max_cost_usd": self.max_cost_usd,
                "used_prompt_tokens": self.used_prompt_tokens,
                "used_completion_tokens": self.used_completion_tokens,
                "used_cost_usd": self.used_cost_usd,
            }


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_at = 0.0
        self.state = CircuitState.CLOSED

    async def call(self, operation: Callable[[], Awaitable[object]]) -> object:
        if self.state == CircuitState.OPEN:
            if time.monotonic() - self.opened_at < self.reset_seconds:
                raise AgentMeshError("Circuit breaker is open", ErrorKind.RATE_LIMIT, retryable=True)
            self.state = CircuitState.HALF_OPEN
        try:
            result = await operation()
        except Exception:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()
            raise
        self.failures = 0
        self.state = CircuitState.CLOSED
        return result


class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._timestamps = [ts for ts in self._timestamps if now - ts < self.period_seconds]
            if len(self._timestamps) >= self.max_calls:
                sleep_for = self.period_seconds - (now - self._timestamps[0])
                await asyncio.sleep(max(sleep_for, 0.0))
            self._timestamps.append(time.monotonic())


class ResultCache:
    def __init__(self) -> None:
        self._values: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self._values.get(key)

    def set(self, key: str, value: object) -> None:
        self._values[key] = value

