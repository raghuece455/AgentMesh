import asyncio

from agentmesh import Agent, MockModelProvider, PermissionLevel, SQLiteStore, Task, ToolCallRequest, ToolRegistry, Workflow, tool


@tool("calculator", "Add two numbers", {"a": "number", "b": "number"})
def calculator(arguments, context):
    return {"sum": float(arguments["a"]) + float(arguments["b"])}


async def main() -> None:
    provider = MockModelProvider(["The calculator returned 42, so the answer is 42."])
    agent = Agent(
        "analyst",
        "Analyst",
        "Use tools when useful, then explain the result.",
        provider,
        ToolRegistry([calculator]),
        {PermissionLevel.READ},
    )
    workflow = Workflow("tool-using-agent", store=SQLiteStore(".agentmesh/examples.db"))
    workflow.add_agent(agent)
    workflow.add_step("analyst", Task("Calculate the answer", tool_calls=[ToolCallRequest("calculator", {"a": 20, "b": 22})]))

    result = await workflow.run()
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

