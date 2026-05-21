from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from agentmesh.errors import AgentMeshError, ErrorKind, PermissionDenied
from agentmesh.types import JsonObject


@dataclass(slots=True)
class SandboxPolicy:
    allowed_commands: set[str]
    cwd: str | Path | None = None
    timeout_seconds: float = 30.0
    env: dict[str, str] = field(default_factory=dict)


async def run_sandboxed_command(command: list[str], policy: SandboxPolicy) -> JsonObject:
    if not command:
        raise AgentMeshError("Sandbox command cannot be empty", ErrorKind.VALIDATION)
    executable = Path(command[0]).name
    if executable not in policy.allowed_commands:
        raise PermissionDenied(
            f"Command '{executable}' is not allowed by sandbox policy",
            {"command": executable, "allowed": sorted(policy.allowed_commands)},
        )
    env = {key: value for key, value in os.environ.items() if not _looks_secret(key)}
    env.update(policy.env)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(policy.cwd) if policy.cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=policy.timeout_seconds)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise AgentMeshError("Sandbox command timed out", ErrorKind.TIMEOUT, {"command": command}, retryable=True) from exc
    return {
        "command": command,
        "returncode": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return lowered in {"token", "password", "secret", "authorization"} or lowered.endswith("_key") or lowered.endswith("_secret")

