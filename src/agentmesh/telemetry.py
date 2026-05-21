from __future__ import annotations

import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

from agentmesh.types import JsonObject, dumps_json, safe_json, utc_now


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: JsonObject = {
            "timestamp": utc_now(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "agentmesh", None)
        if extra is not None:
            payload["agentmesh"] = safe_json(extra)
        return dumps_json(payload)


def configure_json_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("agentmesh")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    return logger


@dataclass(slots=True)
class MetricsRegistry:
    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    histograms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def increment(self, name: str, amount: float = 1.0, labels: JsonObject | None = None) -> None:
        self.counters[self._key(name, labels)] += amount

    def observe(self, name: str, value: float, labels: JsonObject | None = None) -> None:
        self.histograms[self._key(name, labels)].append(value)

    def time(self) -> float:
        return time.perf_counter()

    def prometheus_text(self) -> str:
        lines: list[str] = []
        for name, value in sorted(self.counters.items()):
            lines.append(f"{name} {value}")
        for name, values in sorted(self.histograms.items()):
            if not values:
                continue
            base = name
            lines.append(f"{base}_count {len(values)}")
            lines.append(f"{base}_sum {sum(values)}")
            lines.append(f"{base}_avg {sum(values) / len(values)}")
        return "\n".join(lines) + "\n"

    def _key(self, name: str, labels: JsonObject | None) -> str:
        if not labels:
            return name
        label_text = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
        return f"{name}{{{label_text}}}"


DEFAULT_METRICS = MetricsRegistry()

