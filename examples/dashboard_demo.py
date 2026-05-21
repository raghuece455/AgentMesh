import asyncio

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow, WorkflowMode


async def main() -> None:
    store = SQLiteStore(".agentmesh/agentmesh.db")
    provider = MockModelProvider(
        [
            "Market scan completed.",
            "Prototype plan completed.",
            "Risk review completed.",
        ]
    )
    workflow = Workflow("dashboard-demo", WorkflowMode.PARALLEL, store=store)
    workflow.add_agent(Agent("researcher", "Researcher", "Summarize market context.", provider))
    workflow.add_agent(Agent("builder", "Builder", "Draft an implementation plan.", provider))
    workflow.add_agent(Agent("reviewer", "Reviewer", "List delivery risks.", provider))
    workflow.add_step("researcher", "Research agent observability needs")
    workflow.add_step("builder", "Plan the AgentMesh MVP")
    workflow.add_step("reviewer", "Review reliability risks")

    result = await workflow.run({"demo": "dashboard"})
    print(f"trace_id={result.trace_id}")
    print("Run `agentmesh dashboard` and open http://127.0.0.1:8787")


if __name__ == "__main__":
    asyncio.run(main())

