import asyncio
import os

from agentmesh import Agent, MockModelProvider, SQLiteStore, TimeTravelDebugger, Workflow
from agentmesh.evaluation import RunComparator


async def main() -> None:
    store = SQLiteStore(os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db"))
    provider = MockModelProvider(["original plan", "original final", "replayed final"])
    workflow = Workflow("replay-from-checkpoint-real", store=store)
    workflow.add_agent(Agent("planner", "Planner", "Create a plan.", provider, model="mock-planner"))
    workflow.add_agent(Agent("writer", "Writer", "Write the final answer.", provider, model="mock-writer"))
    workflow.add_step("planner", "Create an observability plan", step_id="plan")
    workflow.add_step("writer", "Write from the plan", depends_on=("plan",), step_id="write")

    original = await workflow.run({"topic": "trace replay", "environment": "local"})
    checkpoints = store.list_checkpoints(original.trace_id)
    after_plan = next(item for item in checkpoints if item["checkpoint_type"] == "after_step" and item["step_id"] == "plan")
    fork_id = TimeTravelDebugger(store).patch_memory(str(after_plan["checkpoint_id"]), {"topic": "cost replay"})
    replayed = await workflow.run_from_checkpoint(fork_id)
    replay = store.create_replay(original.trace_id, "plan", "deterministic", {"replayed_trace_id": replayed.trace_id})
    comparison = RunComparator().compare(store.list_events(original.trace_id), store.list_events(replayed.trace_id))

    print(f"original_trace_id={original.trace_id}")
    print(f"checkpoint_id={fork_id}")
    print(f"replay_trace_id={replayed.trace_id}")
    print(f"replay_id={replay['replay_id']}")
    print(comparison)


if __name__ == "__main__":
    asyncio.run(main())
