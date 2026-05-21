import asyncio

from agentmesh import Agent, MockModelProvider, ModelRouter, RouteRule, SQLiteStore, Task, Workflow


async def main() -> None:
    cheap = MockModelProvider(["cheap model summary"])
    reasoning = MockModelProvider(["reasoning model plan"])
    router = ModelRouter(cheap, [RouteRule("reasoning", reasoning, "Use for planning and difficult synthesis")])

    workflow = Workflow("multi-model-routing", store=SQLiteStore(".agentmesh/examples.db"))
    workflow.add_agent(Agent("analyst", "Analyst", "Use the selected model route.", router))
    workflow.add_step("analyst", Task("Summarize incoming notes", metadata={"model_class": "cheap"}))
    workflow.add_step("analyst", Task("Create a careful launch plan", metadata={"model_class": "reasoning"}))

    result = await workflow.run()
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

