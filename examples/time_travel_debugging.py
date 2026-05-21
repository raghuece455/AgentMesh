import asyncio

from agentmesh import Agent, MockModelProvider, SQLiteStore, TimeTravelDebugger, Workflow


async def main() -> None:
    store = SQLiteStore(".agentmesh/examples.db")
    provider = MockModelProvider(["first pass plan", "first pass final", "replayed final"])
    workflow = Workflow("time-travel-debugging", store=store)
    workflow.add_agent(Agent("planner", "Planner", "Plan.", provider))
    workflow.add_agent(Agent("writer", "Writer", "Write.", provider))
    workflow.add_step("planner", "Create a plan", step_id="plan")
    workflow.add_step("writer", "Write the final answer", step_id="write")

    result = await workflow.run({"topic": "observability"})
    checkpoints = store.list_checkpoints(result.trace_id)
    after_plan = next(
        checkpoint for checkpoint in checkpoints
        if checkpoint["checkpoint_type"] == "after_step" and checkpoint["step_id"] == "plan"
    )
    fork_id = TimeTravelDebugger(store).patch_memory(str(after_plan["checkpoint_id"]), {"topic": "cost governance"})
    replayed = await workflow.run_from_checkpoint(fork_id)

    print(f"original_trace_id={result.trace_id}")
    print(f"fork_checkpoint_id={fork_id}")
    print(f"replay_trace_id={replayed.trace_id}")
    print(replayed.output)


if __name__ == "__main__":
    asyncio.run(main())

