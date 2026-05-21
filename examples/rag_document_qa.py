import asyncio
import os

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


def chunk_text(text: str, size: int = 140) -> list[str]:
    words = text.split()
    return [" ".join(words[index:index + size]) for index in range(0, len(words), size)]


async def main() -> None:
    store = SQLiteStore(os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db"))
    retriever = RetrievalEngine(SQLiteVectorStore(store), top_k=2)
    document = (
        "AgentMesh records traces, spans, model calls, tool calls, memory operations, "
        "and RAG retrievals. The dashboard can show which retrieved chunks influenced an answer. "
        "Human approval events and replay checkpoints are persisted with the same trace ID."
    )
    for index, chunk in enumerate(chunk_text(document, 18), start=1):
        await retriever.vector_store.add_text("docs/agentmesh-observability.md", chunk, {"chunk": index})

    @tool("retrieve_agentmesh_docs", "Retrieve AgentMesh documentation chunks", {"query": "string"})
    async def retrieve_agentmesh_docs(arguments, context):
        results = await retriever.retrieve(str(arguments.get("query", "")), context)
        return [result.to_json() for result in results]

    provider = MockModelProvider(["AgentMesh traces RAG by recording retrieved chunks and citations on the trace."])
    agent = Agent(
        "rag_researcher",
        "RAG researcher",
        "Answer from retrieved chunks only.",
        provider,
        ToolRegistry([retrieve_agentmesh_docs]),
        {PermissionLevel.READ},
    )
    workflow = Workflow("rag-document-qa-real", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "rag_researcher",
        Task(
            "Answer how AgentMesh traces RAG",
            {"question": "Which document chunks influenced this answer?"},
            [ToolCallRequest("retrieve_agentmesh_docs", {"query": "retrieved chunks influenced answer trace"})],
        ),
    )

    result = await workflow.run({"environment": "local"})
    print(f"trace_id={result.trace_id}")
    print(f"rag_retrievals={len(store.list_rag_retrievals(result.trace_id))}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
