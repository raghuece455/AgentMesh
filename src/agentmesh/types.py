from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "cookie",
    "cookies",
    "client_secret",
    "connection_string",
    "credential",
    "credentials",
    "database_url",
    "db_url",
    "password",
    "private_key",
    "secret",
    "set-cookie",
    "token",
    "access_token",
    "refresh_token",
    "webhook_secret",
    "x-api-key",
}

SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s]+@[^/\s]+", re.IGNORECASE),
    re.compile(r"(?i)(password|passwd|pwd|api_key|apikey|token|secret|webhook_secret)=([^&\s]+)"),
]

REDACTED = "[REDACTED]"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{utc_now()}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_json(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return safe_json(dataclasses.asdict(value))
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}
    if isinstance(value, dict):
        result: JsonObject = {}
        for key, item in value.items():
            result[str(key)] = safe_json(item)
        return result
    if isinstance(value, tuple | list | set):
        return [safe_json(item) for item in value]
    return str(value)


def redact_secrets(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        redacted: JsonObject = {}
        for key, item in value.items():
            lowered = key.lower()
            if _secret_key(lowered):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def has_redactions(value: JsonValue) -> bool:
    if value == REDACTED:
        return True
    if isinstance(value, dict):
        return any(has_redactions(item) for item in value.values())
    if isinstance(value, list):
        return any(has_redactions(item) for item in value)
    return False


def dumps_json(value: object) -> str:
    return json.dumps(redact_secrets(safe_json(value)), sort_keys=True)


def loads_json(value: str | None) -> JsonValue:
    if not value:
        return None
    decoded = json.loads(value)
    return safe_json(decoded)


def _secret_key(lowered: str) -> bool:
    return (
        lowered in SECRET_KEYS
        or lowered.endswith("_api_key")
        or lowered.endswith("_secret")
        or lowered.endswith("_token")
        or lowered.endswith("_password")
        or "authorization" in lowered
        or "cookie" in lowered
    )


def _redact_text(value: str) -> str:
    text = value
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}={REDACTED}" if pattern.pattern.startswith("(?i)") else REDACTED, text)
    return text
