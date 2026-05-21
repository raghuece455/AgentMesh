import pytest

from agentmesh import (
    Agent,
    MockModelProvider,
    PermissionLevel,
    RetrievalEngine,
    SQLiteMemoryStore,
    SQLiteStore,
    SQLiteVectorStore,
    Task,
    ToolCallRequest,
    ToolRegistry,
    Workflow,
    tool,
)


@pytest.mark.asyncio
async def test_tool_execution_with_human_approval(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")

    @tool("sensitive_action", "Sensitive action", permission=PermissionLevel.SENSITIVE, requires_approval=True)
    def sensitive_action(arguments, context):
        return {"ok": True, "value": arguments["value"]}

    async def approve(definition, arguments, context):
        return definition.name == "sensitive_action" and arguments["value"] == "yes"

    provider = MockModelProvider(["tool completed"])
    agent = Agent(
        "operator",
        "Operator",
        "Run approved tools.",
        provider,
        ToolRegistry([sensitive_action]),
        {PermissionLevel.READ, PermissionLevel.SENSITIVE},
    )
    workflow = Workflow("test-tool-approval", store=store)
    workflow.add_agent(agent)
    workflow.add_step("operator", Task("run tool", tool_calls=[ToolCallRequest("sensitive_action", {"value": "yes"})]))

    result = await workflow.run(approval_callback=approve)

    assert result.output == "tool completed"
    assert any(event["event_type"] == "tool.finished" for event in store.list_events(result.trace_id))
    assert store.list_audit_logs(result.trace_id)


def test_memory_versions_are_audited(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    memory = SQLiteMemoryStore(store)

    first = memory.put("agent", "profile", "preference", {"tone": "brief"}, "trace_1")
    second = memory.put("agent", "profile", "preference", {"tone": "detailed"}, "trace_2")

    assert first == 1
    assert second == 2
    assert memory.get("agent", "profile", "preference") == {"tone": "detailed"}
    assert len(memory.versions("agent", "profile", "preference")) == 2
    assert len(store.list_audit_logs()) == 2


@pytest.mark.asyncio
async def test_sqlite_vector_retrieval_is_traced(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    retriever = RetrievalEngine(SQLiteVectorStore(store), top_k=1)
    await retriever.ingest({"doc.txt": "Tracing records model calls, tools, and retrieved documents."})

    @tool("retrieve", "Retrieve documents")
    async def retrieve(arguments, context):
        results = await retriever.retrieve(str(arguments["query"]), context)
        return [result.to_json() for result in results]

    provider = MockModelProvider(["answer with source"])
    agent = Agent("rag", "RAG", "Use retrieved sources.", provider, ToolRegistry([retrieve]), {PermissionLevel.READ})
    workflow = Workflow("test-rag", store=store)
    workflow.add_agent(agent)
    workflow.add_step("rag", Task("answer", tool_calls=[ToolCallRequest("retrieve", {"query": "retrieved documents"})]))

    result = await workflow.run()

    events = store.list_events(result.trace_id)
    assert result.output == "answer with source"
    assert any(event["event_type"] == "rag.retrieval" for event in events)

