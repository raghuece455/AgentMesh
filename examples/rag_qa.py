import asyncio

from agentmesh import (
    Agent,
    MockModelProvider,
    PermissionLevel,
    RetrievalEngine,
    SQLiteStore,
    SQLiteVectorStore,
    Task,
    ToolCallRequest,
    ToolRegistry,
    Workflow,
    tool,
)


async def main() -> None:
    store = SQLiteStore(".agentmesh/examples.db")
    retriever = RetrievalEngine(SQLiteVectorStore(store))
    await retriever.ingest(
        {
            "architecture.md": "AgentMesh records every workflow, agent, model, tool, and RAG event in SQLite.",
            "security.md": "Sensitive tools can require human approval and write audit logs.",
            "dashboard.md": "The local dashboard shows traces, task graphs, model usage, retries, and errors.",
        }
    )

    @tool("retrieve_docs", "Retrieve relevant local documents", {"query": "string"})
    async def retrieve_docs(arguments, context):
        query = str(arguments.get("query", ""))
        results = await retriever.retrieve(query, context)
        return [result.to_json() for result in results]

    provider = MockModelProvider(["Answer: AgentMesh uses SQLite traces and shows the retrieved sources in the run timeline."])
    tools = ToolRegistry([retrieve_docs])
    agent = Agent("rag_agent", "RAG Q&A Agent", "Answer using retrieved context only.", provider, tools, {PermissionLevel.READ})
    workflow = Workflow("rag-qa", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "rag_agent",
        Task(
            "Answer the user's question with retrieved sources",
            {"question": "How does AgentMesh trace RAG?"},
            [ToolCallRequest("retrieve_docs", {"query": "trace RAG documents"})],
        ),
    )

    result = await workflow.run()
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

