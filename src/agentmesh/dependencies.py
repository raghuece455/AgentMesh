from __future__ import annotations

from importlib import import_module

from agentmesh.errors import AgentMeshError, ErrorKind


def optional_import(module_name: str, extra: str) -> object:
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AgentMeshError(
            f"Optional dependency '{module_name}' is required. Install it with: pip install -e '.[{extra}]'",
            ErrorKind.VALIDATION,
            {"module": module_name, "extra": extra},
        ) from exc

