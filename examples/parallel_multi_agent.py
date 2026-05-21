import asyncio

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow, WorkflowMode


async def main() -> None:
    store = SQLiteStore(".agentmesh/examples.db")
    provider = MockModelProvider(["Research ready", "Implementation ready", "Risk review ready"])
    workflow = Workflow("parallel-multi-agent", WorkflowMode.PARALLEL, store=store)
    workflow.add_agent(Agent("researcher", "Researcher", "Find context.", provider))
    workflow.add_agent(Agent("builder", "Builder", "Plan implementation.", provider))
    workflow.add_agent(Agent("reviewer", "Reviewer", "Assess risk.", provider))
    workflow.add_step("researcher", "Research observability gaps")
    workflow.add_step("builder", "Draft runtime implementation")
    workflow.add_step("reviewer", "Review production risks")

    result = await workflow.run({"topic": "agent observability"})
    print(f"trace_id={result.trace_id}")
    for step_id, output in result.outputs.items():
        print(step_id, output.output)


if __name__ == "__main__":
    asyncio.run(main())

