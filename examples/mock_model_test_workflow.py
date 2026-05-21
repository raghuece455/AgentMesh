import asyncio

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow


async def build_and_run() -> str:
    provider = MockModelProvider(["deterministic output"])
    workflow = Workflow("mock-test-workflow", store=SQLiteStore(".agentmesh/examples.db"))
    workflow.add_agent(Agent("tester", "Tester", "Return the deterministic test output.", provider))
    workflow.add_step("tester", "Run a deterministic model test")
    result = await workflow.run()
    return result.output


async def main() -> None:
    output = await build_and_run()
    assert output == "deterministic output"
    print(output)


if __name__ == "__main__":
    asyncio.run(main())

