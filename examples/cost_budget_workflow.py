import asyncio

from agentmesh import Agent, BudgetExceeded, BudgetLimiter, MockModelProvider, SQLiteStore, Workflow


async def main() -> None:
    store = SQLiteStore(".agentmesh/examples.db")
    workflow = Workflow("cost-budget-demo", store=store, budget=BudgetLimiter(max_total_tokens=10))
    workflow.add_agent(Agent("writer", "Writer", "Return a long answer.", MockModelProvider(["This response intentionally exceeds the tiny token budget."])))
    workflow.add_step("writer", "Write a detailed production launch plan")

    try:
        await workflow.run()
    except BudgetExceeded as exc:
        print("budget_exceeded=true")
        print(exc.to_json())


if __name__ == "__main__":
    asyncio.run(main())

