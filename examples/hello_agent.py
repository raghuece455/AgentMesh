import asyncio
import os

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow


async def main() -> None:
    store = SQLiteStore(os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db"))
    workflow = Workflow("hello-agent", store=store)
    workflow.add_agent(
        Agent("hello", "Helpful agent", "Return a friendly one-line response.", MockModelProvider(["Hello from AgentMesh."]))
    )
    workflow.add_step("hello", "Say hello")

    result = await workflow.run({"example": "hello", "environment": "local"})
    print(f"trace_id={result.trace_id}")
    print(result.output)
    print(f"model_calls={len(store.list_model_calls(result.trace_id))}")


if __name__ == "__main__":
    asyncio.run(main())
