from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from agentmesh.storage import SQLiteStore
from agentmesh.tracing import TraceRecorder
from agentmesh.types import JsonObject


def seed_demo_data(db_path: str | Path = ".agentmesh/agentmesh.db", reset: bool = False) -> JsonObject:
    reset_mode = "none"
    if str(db_path).startswith(("postgresql://", "postgres://")):
        from agentmesh.stores import create_store

        store = create_store(str(db_path))
        if reset:
            store.reset_local_data()
            reset_mode = "in_place"
        return _seed(store, str(db_path), reset, reset_mode)
    path = Path(str(db_path).removeprefix("sqlite:///"))
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
    return _seed(store, str(path), reset, reset_mode)


def _seed(store: SQLiteStore, database: str, reset: bool, reset_mode: str) -> JsonObject:
    recorder = TraceRecorder(store, logger=_quiet_logger())
    # Experiments first, so their traces sort below the headline demo traces.
    experiments = _seed_support_experiments(store)
    guarded_trace = _seed_guardrails(store)
    traces = [
        _seed_research_pipeline(store, recorder),
        _seed_rag_answer(store, recorder),
        _seed_tool_approval(store, recorder),
        _seed_provider_failure(store, recorder),
        _seed_cost_heavy_run(store, recorder),
        _seed_replay_run(store, recorder),
    ]
    session_traces = _seed_otel_support_session(store)
    traces.extend(session_traces)
    traces.append(guarded_trace)
    store.add_trace_to_dataset("support-answers", session_traces[1], metadata={"note": "approved answer from production"})
    alerts = _seed_alert_rules(store)
    store.close()
    return {
        "experiments": experiments,
        "alert_rules": alerts,
        "database": database,
        "demo": True,
        "reset": reset,
        "reset_mode": reset_mode,
        "traces_seeded": len(traces),
        "trace_ids": traces,
        "message": "Seeded realistic AgentMesh observability data.",
    }


def _seed_otel_support_session(store: SQLiteStore) -> list[str]:
    """A three-turn support chat as an external OpenTelemetry-instrumented app would send it.

    Turn 3 contains a tool loop so the insights engine has something to find.
    """
    import json
    import secrets
    from datetime import UTC, datetime, timedelta

    from agentmesh.ingest import SpanData

    resource = {"service.name": "support-chat", "deployment.environment.name": "demo", "telemetry.sdk.language": "python"}
    session = {"gen_ai.conversation.id": "demo-chat-1001", "user.id": "customer-88"}
    turns = [
        ("Where is my order A-1001?", "Your order shipped yesterday and arrives Friday.", 0),
        ("Can I change the delivery address?", "Yes. I updated the address to 42 Harbor Road.", 0),
        ("Refund the shipping fee please.", None, 4),
    ]
    start = datetime.now(UTC) - timedelta(minutes=30)
    trace_ids: list[str] = []
    for index, (question, answer, loop_calls) in enumerate(turns):
        trace_id = secrets.token_hex(16)
        trace_ids.append(trace_id)
        root_id = secrets.token_hex(8)
        cursor = start + timedelta(minutes=index * 5)

        def at(offset_ms: float, base: datetime = cursor) -> str:
            return (base + timedelta(milliseconds=offset_ms)).isoformat(timespec="microseconds")

        spans: list[SpanData] = []
        context_tokens = 3_000 + index * 4_000
        clock = 20.0
        llm_calls = 2 + loop_calls
        for call in range(llm_calls):
            prompt_tokens = context_tokens + call * 9_000
            spans.append(
                SpanData(
                    trace_id=trace_id,
                    span_id=secrets.token_hex(8),
                    parent_span_id=root_id,
                    name="chat claude-sonnet-5",
                    kind="CLIENT",
                    start_time=at(clock),
                    end_time=at(clock + 900 + call * 150),
                    status="ok",
                    attributes={
                        "gen_ai.operation.name": "chat",
                        "gen_ai.provider.name": "anthropic",
                        "gen_ai.request.model": "claude-sonnet-5",
                        "gen_ai.usage.input_tokens": prompt_tokens,
                        "gen_ai.usage.cache_read.input_tokens": 2_400 if index else 0,
                        "gen_ai.usage.output_tokens": 180 + call * 20,
                        "gen_ai.input.messages": json.dumps([{"role": "user", "parts": [{"type": "text", "content": question}]}]),
                        **session,
                    },
                    resource=resource,
                )
            )
            clock += 1_000 + call * 150
            if call < llm_calls - 1:
                failed = loop_calls and call >= 1
                spans.append(
                    SpanData(
                        trace_id=trace_id,
                        span_id=secrets.token_hex(8),
                        parent_span_id=root_id,
                        name="execute_tool issue_refund" if loop_calls else "execute_tool lookup_order",
                        start_time=at(clock),
                        end_time=at(clock + 350),
                        status="error" if failed else "ok",
                        status_message="Payments API returned 409: refund already pending" if failed else None,
                        attributes={
                            "gen_ai.operation.name": "execute_tool",
                            "gen_ai.tool.name": "issue_refund" if loop_calls else "lookup_order",
                            "gen_ai.tool.call.arguments": json.dumps({"order_id": "A-1001", "amount": 4.99} if loop_calls else {"order_id": "A-1001"}),
                            "gen_ai.tool.call.result": None if loop_calls else json.dumps({"status": "shipped", "eta": "Friday"}),
                            **({"error.type": "PaymentsConflict"} if failed else {}),
                            **session,
                        },
                        resource=resource,
                    )
                )
                clock += 400
        spans.append(
            SpanData(
                trace_id=trace_id,
                span_id=root_id,
                name="invoke_agent support_agent",
                start_time=at(0),
                end_time=at(clock + 50),
                status="error" if answer is None else "ok",
                status_message="Gave up after repeated refund failures" if answer is None else None,
                attributes={
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": "support_agent",
                    "input.value": question,
                    "output.value": answer,
                    "tag.tags": ["demo", "support"],
                    **session,
                },
                resource=resource,
            )
        )
        store.ingest_spans(spans, source="otlp")
        if answer is not None:
            store.save_score({"trace_id": trace_id, "name": "user_feedback", "value": True, "source": "feedback"})
        else:
            store.save_score({"trace_id": trace_id, "name": "user_feedback", "value": False, "comment": "Refund never happened", "source": "feedback"})
    return trace_ids


SUPPORT_QUESTIONS = [
    ("How long do refunds take?", "Refunds reach your card within 5 business days."),
    ("Can I change my delivery address after ordering?", "Yes, until the order ships: open the order and choose Change address."),
    ("Do you ship to Canada?", "Yes, we ship to Canada in 4-7 business days."),
    ("How do I reset my password?", "Use Forgot password on the sign-in page to get a reset link."),
]


def _seed_support_experiments(store: SQLiteStore) -> list[str]:
    """Two prompt versions of a support bot run over the same dataset, scored by evaluators.

    Uses the real experiment runner (every item gets a trace), with deterministic stand-ins
    for the model and the LLM judge.
    """
    from agentmesh import sdk
    from agentmesh.evaluators import Contains, LLMJudge
    from agentmesh.experiments import run_experiment

    if store.get_dataset("support-answers", include_items=False) is None:
        store.create_dataset("support-answers", "Real customer questions with approved answers")
        store.add_dataset_items(
            "support-answers",
            [{"input": {"question": question}, "expected": answer, "metadata": {"source": "demo"}} for question, answer in SUPPORT_QUESTIONS],
        )

    class _StoreExporter(sdk.SpanExporter):
        def export(self, spans: list[object]) -> None:
            store.ingest_spans(spans, source="sdk")

        def send_score(self, payload: JsonObject) -> None:
            store.save_score(payload)

    answers = dict(SUPPORT_QUESTIONS)
    v1_answers = {
        "How long do refunds take?": "Refunds usually take a while depending on your bank.",
        "Do you ship to Canada?": "We ship to many countries.",
    }

    def prompt_v1(input: JsonObject) -> str:
        return v1_answers.get(str(input["question"]), answers[str(input["question"])])

    def prompt_v2(input: JsonObject) -> str:
        question = str(input["question"])
        if question.startswith("How do I reset"):
            raise TimeoutError("model call timed out after 30s")
        return answers[question]

    def demo_judge(prompt: str) -> str:
        output = prompt.split("Actual output:", 1)[1]
        grounded = any(marker in output for marker in ("5 business days", "4-7 business days", "Change address", "reset link"))
        return '{"score": 0.95, "reason": "Matches the approved answer"}' if grounded else '{"score": 0.3, "reason": "Vague; misses the specifics in the reference"}'

    evaluators = [Contains(name="has_key_facts"), LLMJudge("correctness", judge=demo_judge)]
    previous = sdk._client
    sdk._client = sdk.AgentMeshClient(sdk.AgentMeshConfig(service_name="support-bot-evals", environment="demo"), _StoreExporter())
    try:
        runs = [
            run_experiment("support-answers", prompt_v1, evaluators, name="support-bot prompt-v1", metadata={"model": "claude-haiku-4-5"}, store=store),
            run_experiment("support-answers", prompt_v2, evaluators, name="support-bot prompt-v2", metadata={"model": "claude-sonnet-5"}, store=store),
        ]
    finally:
        sdk._client.shutdown()
        sdk._client = previous
    return [run.experiment_id for run in runs]


DEMO_POLICIES = [
    """name: production-safety
description: Destructive and money-moving tools need a person.
mode: enforce
rules:
  - name: no-production-deletes
    match: {tool: ["delete_*", "drop_*"], arguments: {env: production}}
    action: deny
    reason: Deleting production data needs a person.
  - name: refunds-need-approval
    match: {tool: issue_refund}
    action: require_approval
""",
    """name: runaway-agents
description: Stop agents that loop, fan out, or overspend.
mode: enforce
limits:
  max_repeated_calls: 3
  max_cost_usd: 5
  max_agent_depth: 4
  max_child_agents: 10
""",
    """name: approved-models
description: Trying out an approved-model list before enforcing it.
mode: monitor
rules:
  - name: approved-models-only
    match: {kind: llm}
    except: {model: ["gpt-4.1*", "claude-*"]}
    action: deny
""",
]


def _seed_guardrails(store: SQLiteStore) -> str:
    """Policies, a trace they stopped calls in, and a released halt, for the Guardrails page."""
    from agentmesh import sdk
    from agentmesh.errors import PolicyViolation
    from agentmesh.guardrails import Guardrails, StoreBackend
    from agentmesh.policy import Policy

    for text in DEMO_POLICIES:
        if store.get_policy(Policy.from_spec(text).name) is None:
            store.create_policy({"text": text})

    class _StoreExporter(sdk.SpanExporter):
        def export(self, spans: list[object]) -> None:
            store.ingest_spans(spans, source="sdk")

    @sdk.observe(kind="tool", name="delete_account")
    def delete_account(customer_id: str, env: str) -> str:
        return "deleted"

    @sdk.observe(kind="tool", name="lookup_invoice")
    def lookup_invoice(invoice_id: str) -> None:
        return None  # never found, so the agent keeps retrying

    @sdk.observe(kind="agent", name="billing_agent")
    def billing_agent(request: str) -> str:
        try:
            delete_account("cus_1042", env="production")
        except PolicyViolation:
            pass
        for _ in range(5):
            try:
                lookup_invoice("INV-2291")
            except PolicyViolation:
                break
        with sdk.span("chat gpt-4o-mini", kind="llm", attributes={"gen_ai.request.model": "gpt-4o-mini", "gen_ai.provider.name": "openai"}) as call:
            call.set_attribute("gen_ai.usage.input_tokens", 840)
            call.set_attribute("gen_ai.usage.output_tokens", 96)
            call.set_output("I can't close the account myself; a teammate will confirm the deletion.")
        return "Escalated: account deletion needs a person; invoice INV-2291 not found."

    previous = sdk._client
    client = sdk.AgentMeshClient(sdk.AgentMeshConfig(service_name="billing-bot", environment="demo"), _StoreExporter())
    backend = StoreBackend(store)
    client.guardrails = Guardrails(backend, service="billing-bot", environment="demo")
    sdk._client = client
    try:
        with sdk.trace("billing-request (guarded)", tags=["guardrails"], input="Close my account and resend invoice INV-2291") as root:
            root.set_output(billing_agent("Close my account and resend invoice INV-2291"))
        trace_id = root.trace_id
    finally:
        client.shutdown()
        sdk._client = previous
    halt = store.create_halt({"scope": "agent", "value": "research_swarm", "reason": "Fan-out spiked to 40 sub-agents in two minutes", "created_by": "demo"})
    store.release_halt(halt["halt_id"], "demo")
    return trace_id


def _seed_alert_rules(store: SQLiteStore) -> list[str]:
    rules = [
        {"name": "Any failed run", "kind": "failure_count", "threshold": 1, "window": "1d", "cooldown": "1h"},
        {"name": "Expensive trace", "kind": "trace_cost", "threshold": 0.05, "window": "1d"},
        {"name": "Agent tool loops", "kind": "loop_detected", "threshold": 3, "window": "1d"},
        {"name": "Hourly spend", "kind": "cost", "threshold": 25, "window": "1h"},
    ]
    existing = {rule["name"] for rule in store.list_alert_rules()}
    for rule in rules:
        if rule["name"] not in existing:
            store.create_alert_rule(rule)
    store.check_alerts(deliver=False)
    return [rule["name"] for rule in rules]


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
    recorder.event(trace_id, "model.response", "regression_agent", {"provider": "mock", "model": "mock-model", "output": "Deterministic replay output", "prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50, "estimated_cost": 0, "cost_status": "local/free", "latency_ms": 12, "metadata": {"demo": True, "task_id": "regression-step"}}, parent_span_id=agent_span)
    recorder.finish_workflow(trace_id, "succeeded", {"output": "Deterministic replay output"})
    replay = recorder.store.export_trace(trace_id)
    store.create_replay(trace_id, None, "deterministic", replay)
    return trace_id
