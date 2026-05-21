from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from agentmesh.storage import SQLiteStore
from agentmesh.tracing import TraceRecorder
from agentmesh.types import JsonObject


def seed_demo_data(db_path: str | Path = ".agentmesh/agentmesh.db", reset: bool = False) -> JsonObject:
    path = Path(db_path)
    reset_mode = "none"
    if reset and path.exists():
        try:
            path.unlink()
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = path.with_name(f"{path.name}{suffix}")
                if sidecar.exists():
                    try:
                        sidecar.unlink()
                    except PermissionError:
                        pass
            reset_mode = "file_deleted"
        except PermissionError:
            store = SQLiteStore(path)
            try:
                store.reset_local_data()
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower():
                    raise RuntimeError(
                        "AgentMesh cannot reset the SQLite database while another process is holding a write lock. "
                        "Stop the dashboard process using this database, then run `python -m agentmesh.cli demo seed --reset` again. "
                        "You can also run `python -m agentmesh.cli demo seed` without --reset to append demo traces."
                    ) from exc
                raise
            reset_mode = "in_place"
        else:
            store = SQLiteStore(path)
    else:
        store = SQLiteStore(path)
    recorder = TraceRecorder(store, logger=_quiet_logger())
    traces = [
        _seed_research_pipeline(store, recorder),
        _seed_rag_answer(store, recorder),
        _seed_tool_approval(store, recorder),
        _seed_provider_failure(store, recorder),
        _seed_cost_heavy_run(store, recorder),
        _seed_replay_run(store, recorder),
    ]
    return {
        "database": str(path),
        "demo": True,
        "reset": reset,
        "reset_mode": reset_mode,
        "traces_seeded": len(traces),
        "trace_ids": traces,
        "message": "Seeded realistic AgentMesh observability data.",
    }


def _quiet_logger() -> logging.Logger:
    logger = logging.getLogger("agentmesh.demo_seed")
    logger.disabled = True
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def _seed_research_pipeline(store: SQLiteStore, recorder: TraceRecorder) -> str:
    trace_id = recorder.start_workflow(
        "research-writer-reviewer",
        {"topic": "enterprise agent observability", "demo": True, "source": "agentmesh demo seed"},
    )
    previous: dict[str, str] = {}
    parent = None
    for agent, role, model, tokens, cost, latency in [
        ("researcher", "Research agent", "gpt-4.1-mini", (1240, 430), 0.018, 812),
        ("writer", "Technical writer", "gpt-4.1-mini", (930, 620), 0.021, 930),
        ("reviewer", "Quality reviewer", "gpt-4.1", (680, 220), 0.033, 1260),
    ]:
        task_id = f"{agent}-step"
        task_span = recorder.event(trace_id, "task.started", agent, {"task_id": task_id, "task": role, "input": previous}, parent)
        agent_span = recorder.event(trace_id, "agent.started", agent, {"role": role, "message": {"task_id": task_id}})
        prompt_id = store.save_prompt_version(
            trace_id,
            agent,
            task_id,
            f"You are the {role}. Produce concise production-grade output.",
            f"Previous context: {previous}. Continue the workflow.",
            {"demo": True, "owner": "system"},
        )
        recorder.event(
            trace_id,
            "model.call",
            agent,
            {
                "prompt_id": prompt_id,
                "prompt_version": prompt_id,
                "provider": "openai-compatible",
                "model": model,
                "system": f"You are the {role}.",
                "prompt": f"Continue workflow with previous={previous}",
                "temperature": 0.2,
                "top_p": 0.95,
                "max_tokens": 1200,
                "metadata": {"demo": True, "task_id": task_id},
            },
            parent_span_id=agent_span,
        )
        output = f"{role} completed: {agent} produced traceable output."
        recorder.event(
            trace_id,
            "model.response",
            agent,
            {
                "prompt_id": prompt_id,
                "prompt_version": prompt_id,
                "provider": "openai-compatible",
                "model": model,
                "output": output,
                "prompt_tokens": tokens[0],
                "completion_tokens": tokens[1],
                "cached_tokens": 120 if agent == "writer" else 0,
                "reasoning_tokens": 64 if agent == "reviewer" else 0,
                "total_tokens": tokens[0] + tokens[1],
                "estimated_cost": cost,
                "cost_usd": cost,
                "latency_ms": latency,
                "temperature": 0.2,
                "top_p": 0.95,
                "max_tokens": 1200,
                "metadata": {"demo": True, "task_id": task_id},
            },
            parent_span_id=agent_span,
        )
        recorder.event(trace_id, "agent.finished", agent, {"output": output}, parent_span_id=agent_span)
        recorder.event(trace_id, "task.succeeded", agent, {"task_id": task_id, "task": role, "output": output}, parent_span_id=task_span)
        checkpoint_id = store.save_checkpoint(trace_id, "after_step", {"agent": agent, "output": output, "demo": True}, task_id)
        recorder.event(trace_id, "checkpoint.saved", "workflow", {"checkpoint_id": checkpoint_id, "checkpoint_type": "after_step", "step_id": task_id})
        previous[agent] = output
        parent = task_span
    recorder.finish_workflow(trace_id, "succeeded", previous)
    store.save_evaluation(
        {
            "trace_id": trace_id,
            "workflow_name": "research-writer-reviewer",
            "agent_name": "reviewer",
            "evaluator": "keyword-expected-output",
            "evaluator_type": "keyword",
            "score": 0.92,
            "passed": True,
            "findings": [{"kind": "quality", "message": "All required sections present."}],
            "metadata": {"demo": True},
        }
    )
    return trace_id


def _seed_rag_answer(store: SQLiteStore, recorder: TraceRecorder) -> str:
    trace_id = recorder.start_workflow("rag-document-qa", {"question": "Which documents influenced this answer?", "demo": True})
    agent_span = recorder.event(trace_id, "agent.started", "rag_analyst", {"role": "RAG analyst"})
    documents = [
        {
            "document_id": "doc_policy_01",
            "id": "chunk_policy_01",
            "source": "docs/governance.md",
            "content": "Human approval is required for high-risk tool calls and all side effects are audit logged.",
            "metadata": {"section": "approval gates"},
            "score": 0.91,
        },
        {
            "document_id": "doc_trace_02",
            "id": "chunk_trace_02",
            "source": "docs/tracing.md",
            "content": "Each model call, tool call, memory access, and retrieval is attached to a trace and span.",
            "metadata": {"section": "trace model"},
            "score": 0.88,
        },
    ]
    recorder.event(
        trace_id,
        "rag.retrieval",
        "rag_analyst",
        {
            "query": "approval audit trace influence",
            "embedding_model": "hash-embedding-64",
            "vector_store": "sqlite-vector",
            "documents": documents,
            "used_in_answer": True,
            "citation_mapping": {"sentence_1": ["chunk_policy_01"], "sentence_2": ["chunk_trace_02"]},
            "metadata": {"demo": True},
        },
        parent_span_id=agent_span,
    )
    store.save_memory("rag_analyst", "workflow", "last_retrieval", {"chunks": ["chunk_policy_01", "chunk_trace_02"]}, trace_id)
    recorder.event(
        trace_id,
        "memory.write",
        "rag_analyst",
        {"memory_type": "workflow state", "operation": "write", "key": "last_retrieval", "value": {"chunks": ["chunk_policy_01", "chunk_trace_02"]}, "version": 1, "metadata": {"demo": True}},
        parent_span_id=agent_span,
    )
    prompt_id = store.save_prompt_version(trace_id, "rag_analyst", "answer-question", "Answer with citations.", "Use retrieved chunks to answer.", {"demo": True})
    recorder.event(
        trace_id,
        "model.response",
        "rag_analyst",
        {
            "prompt_id": prompt_id,
            "prompt_version": prompt_id,
            "provider": "ollama",
            "model": "llama3.1",
            "output": "The answer used governance and tracing chunks.",
            "prompt_tokens": 760,
            "completion_tokens": 140,
            "total_tokens": 900,
            "estimated_cost": 0.0,
            "latency_ms": 1840,
            "metadata": {"demo": True, "task_id": "answer-question"},
        },
        parent_span_id=agent_span,
    )
    recorder.event(trace_id, "agent.finished", "rag_analyst", {"output": "Answered with citations."}, parent_span_id=agent_span)
    recorder.finish_workflow(trace_id, "succeeded", {"answer": "The answer used governance and tracing chunks."})
    return trace_id


def _seed_tool_approval(store: SQLiteStore, recorder: TraceRecorder) -> str:
    trace_id = recorder.start_workflow("human-approval-release", {"ticket": "AM-124", "demo": True})
    agent_span = recorder.event(trace_id, "agent.started", "release_operator", {"role": "Release operator"})
    approval_id = store.create_approval(trace_id, "release_operator", "deploy_service", {"service": "agentmesh-api", "environment": "staging", "action": "deploy"})
    recorder.event(
        trace_id,
        "approval.requested",
        "release_operator",
        {"approval_id": approval_id, "tool": "deploy_service", "arguments": {"service": "agentmesh-api", "environment": "staging"}, "risk_level": "high"},
        parent_span_id=agent_span,
    )
    store.resolve_approval(approval_id, True, "Demo approval accepted.")
    recorder.event(trace_id, "approval.resolved", "release_operator", {"approval_id": approval_id, "approved": True, "tool": "deploy_service"}, parent_span_id=agent_span)
    tool_span = recorder.event(
        trace_id,
        "tool.started",
        "release_operator",
        {
            "tool": {"name": "deploy_service", "type": "api", "permission": "sensitive", "requires_approval": True},
            "arguments": {"service": "agentmesh-api", "environment": "staging"},
            "metadata": {"demo": True},
        },
        parent_span_id=agent_span,
    )
    recorder.event(
        trace_id,
        "tool.finished",
        "release_operator",
        {
            "tool": "deploy_service",
            "result": {"deployment_id": "dep_demo_001", "status": "queued"},
            "side_effects": [{"type": "api_called", "target": "deployment-api"}],
        },
        parent_span_id=tool_span,
    )
    recorder.finish_workflow(trace_id, "succeeded", {"deployment_id": "dep_demo_001"})
    return trace_id


def _seed_provider_failure(store: SQLiteStore, recorder: TraceRecorder) -> str:
    trace_id = recorder.start_workflow("provider-timeout-debug", {"demo": True, "task": "summarize incident"})
    agent_span = recorder.event(trace_id, "agent.started", "incident_summarizer", {"role": "Incident summarizer"})
    prompt_id = store.save_prompt_version(trace_id, "incident_summarizer", "summarize", "Summarize incident.", "Summarize provider error.", {"demo": True})
    recorder.event(trace_id, "model.call", "incident_summarizer", {"prompt_id": prompt_id, "provider": "openai-compatible", "model": "gpt-4.1", "prompt": "Summarize incident", "temperature": 0.1, "metadata": {"demo": True, "task_id": "summarize"}}, parent_span_id=agent_span)
    recorder.event(
        trace_id,
        "model.failed",
        "incident_summarizer",
        {
            "prompt_id": prompt_id,
            "provider": "openai-compatible",
            "model": "gpt-4.1",
            "latency_ms": 30000,
            "error": {"kind": "timeout_error", "message": "Provider request exceeded 30s timeout", "retryable": True},
            "metadata": {"demo": True, "task_id": "summarize"},
        },
        parent_span_id=agent_span,
    )
    recorder.event(trace_id, "task.retry_scheduled", "incident_summarizer", {"task_id": "summarize", "attempt": 1, "delay_seconds": 2})
    checkpoint_id = store.save_checkpoint(trace_id, "failed_step", {"error": "timeout", "demo": True}, "summarize")
    recorder.event(trace_id, "checkpoint.saved", "workflow", {"checkpoint_id": checkpoint_id, "checkpoint_type": "failed_step", "step_id": "summarize"})
    recorder.finish_workflow(trace_id, "failed", None, {"kind": "timeout_error", "message": "Provider request exceeded 30s timeout"})
    return trace_id


def _seed_cost_heavy_run(store: SQLiteStore, recorder: TraceRecorder) -> str:
    trace_id = recorder.start_workflow("cost-heavy-agent-loop", {"demo": True, "budget": 3.0})
    agent_span = recorder.event(trace_id, "agent.started", "planner", {"role": "Planner"})
    for index in range(3):
        prompt_id = store.save_prompt_version(trace_id, "planner", f"loop-{index}", "Plan carefully.", f"Loop iteration {index}", {"demo": True})
        recorder.event(
            trace_id,
            "model.response",
            "planner",
            {
                "prompt_id": prompt_id,
                "provider": "openai-compatible",
                "model": "gpt-4.1",
                "output": f"Loop output {index}",
                "prompt_tokens": 5400,
                "completion_tokens": 1600,
                "reasoning_tokens": 800,
                "total_tokens": 7800,
                "estimated_cost": 1.42,
                "latency_ms": 4200 + index * 600,
                "metadata": {"demo": True, "task_id": f"loop-{index}"},
            },
            parent_span_id=agent_span,
        )
    recorder.event(trace_id, "workflow.failed", "workflow", {"error": {"kind": "budget_exceeded", "message": "Run exceeded max_cost_per_run budget."}})
    recorder.finish_workflow(trace_id, "failed", None, {"kind": "budget_exceeded", "message": "Run exceeded max_cost_per_run budget."})
    return trace_id


def _seed_replay_run(store: SQLiteStore, recorder: TraceRecorder) -> str:
    trace_id = recorder.start_workflow("replay-regression-demo", {"demo": True, "mode": "deterministic"})
    agent_span = recorder.event(trace_id, "agent.started", "regression_agent", {"role": "Regression tester"})
    checkpoint_id = store.save_checkpoint(trace_id, "before_step", {"workflow_memory": {"values": {"version": "v1"}}, "demo": True}, "regression-step")
    recorder.event(trace_id, "checkpoint.saved", "workflow", {"checkpoint_id": checkpoint_id, "checkpoint_type": "before_step", "step_id": "regression-step"}, parent_span_id=agent_span)
    recorder.event(trace_id, "model.response", "regression_agent", {"provider": "mock", "model": "mock-model", "output": "Deterministic replay output", "prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50, "estimated_cost": 0, "latency_ms": 12, "metadata": {"demo": True, "task_id": "regression-step"}}, parent_span_id=agent_span)
    recorder.finish_workflow(trace_id, "succeeded", {"output": "Deterministic replay output"})
    replay = recorder.store.export_trace(trace_id)
    store.create_replay(trace_id, None, "deterministic", replay)
    return trace_id
