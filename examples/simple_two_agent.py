import asyncio

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow, WorkflowMode


async def main() -> None:
    store = SQLiteStore(".agentmesh/examples.db")
    provider = MockModelProvider(["Plan: define scope, build, verify.", "Final: the demo is ready to ship."])
    workflow = Workflow("simple-two-agent", WorkflowMode.SEQUENTIAL, store=store)
    workflow.add_agent(Agent("planner", "Planner", "Break the request into a short implementation plan.", provider))
    workflow.add_agent(Agent("writer", "Writer", "Turn the plan into a concise final update.", provider))
    workflow.add_step("planner", "Plan a one-day agent framework demo")
    workflow.add_step("writer", "Write the final update from the planner output")

    result = await workflow.run({"goal": "demo AgentMesh"})
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

