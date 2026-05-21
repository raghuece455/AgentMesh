import asyncio

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow, WorkflowMode


async def main() -> None:
    provider = MockModelProvider(
        [
            "Research: users need traceability, local runs, and safe tools.",
            "Draft: AgentMesh gives teams observable multi-agent workflows.",
            "Review: concise, accurate, and ready.",
        ]
    )
    workflow = Workflow("research-writer-reviewer", WorkflowMode.SEQUENTIAL, store=SQLiteStore(".agentmesh/examples.db"))
    workflow.add_agent(Agent("researcher", "Researcher", "Find the most relevant facts.", provider))
    workflow.add_agent(Agent("writer", "Writer", "Write a clear short draft.", provider))
    workflow.add_agent(Agent("reviewer", "Reviewer", "Check for correctness and gaps.", provider))
    workflow.add_step("researcher", "Research why traceability matters in agent frameworks")
    workflow.add_step("writer", "Write a product note using the research")
    workflow.add_step("reviewer", "Review the note and identify issues")

    result = await workflow.run({"audience": "developers"})
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

