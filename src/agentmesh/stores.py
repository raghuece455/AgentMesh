from __future__ import annotations

from pathlib import Path

from agentmesh.postgres import PostgreSQLStore
from agentmesh.storage import SQLiteStore


def create_store(url_or_path: str | Path = ".agentmesh/agentmesh.db") -> SQLiteStore | PostgreSQLStore:
    value = str(url_or_path)
    if value.startswith(("postgresql://", "postgres://")):
        return PostgreSQLStore(value)
    if value.startswith("sqlite:///"):
        return SQLiteStore(value.removeprefix("sqlite:///"))
    return SQLiteStore(value)

