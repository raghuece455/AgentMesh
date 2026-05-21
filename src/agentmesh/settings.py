from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentMeshSettings:
    db_url: str = ".agentmesh/agentmesh.db"
    host: str = "127.0.0.1"
    port: int = 8787
    auth_mode: str = "none"
    api_key: str | None = None
    log_level: str = "INFO"
    otel_enabled: bool = False

    @classmethod
    def from_env(cls) -> "AgentMeshSettings":
        return cls(
            db_url=os.getenv("AGENTMESH_DB_URL", os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db")),
            host=os.getenv("AGENTMESH_HOST", "127.0.0.1"),
            port=int(os.getenv("AGENTMESH_PORT", "8787")),
            auth_mode=os.getenv("AGENTMESH_AUTH_MODE", "none").lower(),
            api_key=os.getenv("AGENTMESH_API_KEY"),
            log_level=os.getenv("AGENTMESH_LOG_LEVEL", "INFO"),
            otel_enabled=os.getenv("AGENTMESH_OTEL_ENABLED", "false").lower() in {"1", "true", "yes"},
        )
