"""Guardrails for the AgentMesh runtime (``Workflow`` / ``Agent`` / ``ToolRegistry``).

Policies and halts come from the runtime's store, so a policy or halt saved in the dashboard
applies to workflows run with that database. Decisions are written to the store and recorded
as ``policy.decision`` events in the trace.
"""

from __future__ import annotations

from typing import Any

from agentmesh.guardrails import Guardrails, for_store
from agentmesh.policy import ActionContext, Decision


def runtime_guardrails(context: Any) -> Guardrails | None:
    """Guardrails for a workflow context, or ``None`` when its store cannot hold policies."""
    store = getattr(context, "store", None)
    if store is None or not hasattr(store, "policy_runtime_config"):
        return None
    guardrails = for_store(store)
    return guardrails if guardrails.active else None


def _recorder(context: Any, actor: str, parent_span_id: str | None) -> Any:
    def record(decision: Decision) -> None:
        recorder = getattr(context, "recorder", None)
        if recorder is not None:
            recorder.event(context.trace_id, "policy.decision", actor, decision.to_json(), parent_span_id=parent_span_id)

    return record


async def check_runtime_action(
    context: Any,
    *,
    kind: str,
    name: str,
    agent: str | None,
    parent_span_id: str | None,
    arguments: Any = None,
    model: str | None = None,
    provider: str | None = None,
) -> Guardrails | None:
    """Enforce policies for a runtime action. Returns the guardrails used, if any."""
    guardrails = runtime_guardrails(context)
    if guardrails is None:
        return None
    action = ActionContext(
        kind=kind,
        name=name,
        trace_id=context.trace_id,
        parent_span_id=parent_span_id,
        agent=agent,
        model=model,
        provider=provider,
        arguments=arguments,
    )
    await guardrails.acheck(action, _recorder(context, agent or name, parent_span_id))
    return guardrails
