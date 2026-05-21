import pytest

from agentmesh import (
    Agent,
    CostTracker,
    MockModelProvider,
    ModelRequest,
    ModelRouter,
    RouteRule,
    SQLiteStore,
    Task,
    TimeTravelDebugger,
    Workflow,
    WorkflowMode,
)


@pytest.mark.asyncio
async def test_parallel_scheduler_honors_dependencies_and_saves_checkpoints(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    planner_provider = MockModelProvider(["plan output"])
    writer_provider = MockModelProvider(["write output", "rerun write output"])
    workflow = Workflow("dependency-checkpoint", WorkflowMode.PARALLEL, store=store)
    workflow.add_agent(Agent("planner", "Planner", "Plan.", planner_provider))
    workflow.add_agent(Agent("writer", "Writer", "Write.", writer_provider))
    workflow.add_step("planner", Task("plan", id="plan"))
    workflow.add_step("writer", Task("write", id="write"), depends_on=("plan",))

    result = await workflow.run()
    checkpoints = store.list_checkpoints(result.trace_id)
    after_plan = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint["checkpoint_type"] == "after_step" and checkpoint["step_id"] == "plan"
    ][0]

    assert result.output == "write output"
    assert after_plan["state"]["completed_step_ids"] == ["plan"]

    replayed = await workflow.run_from_checkpoint(str(after_plan["checkpoint_id"]))

    assert replayed.output == "rerun write output"


def test_time_travel_patch_memory_forks_checkpoint(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    checkpoint_id = store.save_checkpoint(
        "trace_1",
        "after_step",
        {"workflow_memory": {"values": {"topic": "old"}}, "outputs": {}, "completed_step_ids": []},
        "step_1",
    )

    fork_id = TimeTravelDebugger(store).patch_memory(checkpoint_id, {"topic": "new"})
    forked = store.get_checkpoint(fork_id)

    assert forked is not None
    assert forked["checkpoint_type"] == "time_travel.patch"
    assert forked["state"]["workflow_memory"]["values"]["topic"] == "new"


@pytest.mark.asyncio
async def test_model_router_uses_task_metadata_route():
    cheap = MockModelProvider(["cheap"])
    reasoning = MockModelProvider(["reasoning"])
    router = ModelRouter(cheap, [RouteRule("reasoning", reasoning)])

    response = await router.generate(ModelRequest("solve", metadata={"model_class": "reasoning"}))

    assert response.text == "reasoning"
    assert response.raw["routed_provider"] == "mock"
    assert cheap.calls == 0
    assert reasoning.calls == 1


@pytest.mark.asyncio
async def test_cost_tracker_summarizes_model_usage(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    workflow = Workflow("costs", store=store)
    workflow.add_agent(Agent("agent", "Agent", "Return output.", MockModelProvider(["costed output"])))
    workflow.add_step("agent", "run")

    result = await workflow.run()
    summary = CostTracker(store).summarize(result.trace_id)

    assert summary.model_calls == 1
    assert summary.total_tokens > 0
    assert "agent" in summary.by_agent

