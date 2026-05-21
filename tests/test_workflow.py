import pytest

from agentmesh import Agent, MockModelProvider, RetryPolicy, SQLiteStore, Task, Workflow, WorkflowMode


@pytest.mark.asyncio
async def test_sequential_workflow_records_trace(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    provider = MockModelProvider(["first", "second"])
    workflow = Workflow("test-sequential", WorkflowMode.SEQUENTIAL, store=store)
    workflow.add_agent(Agent("a", "First", "Return first.", provider))
    workflow.add_agent(Agent("b", "Second", "Return second.", provider))
    workflow.add_step("a", "step one")
    workflow.add_step("b", "step two")

    result = await workflow.run({"goal": "test"})

    assert result.status == "succeeded"
    assert result.output == "second"
    events = store.list_events(result.trace_id)
    assert any(event["event_type"] == "model.call" for event in events)
    assert any(event["event_type"] == "workflow.finished" for event in events)


@pytest.mark.asyncio
async def test_parallel_workflow_runs_all_steps(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    provider = MockModelProvider(["left", "right"])
    workflow = Workflow("test-parallel", WorkflowMode.PARALLEL, store=store)
    workflow.add_agent(Agent("left", "Left", "Return left.", provider))
    workflow.add_agent(Agent("right", "Right", "Return right.", provider))
    workflow.add_step("left", "left step")
    workflow.add_step("right", "right step")

    result = await workflow.run()

    assert result.status == "succeeded"
    assert len(result.outputs) == 2


@pytest.mark.asyncio
async def test_retry_policy_retries_retryable_model_error(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    provider = MockModelProvider(["recovered"], fail_first=True)
    workflow = Workflow("test-retry", store=store)
    workflow.add_agent(Agent("worker", "Worker", "Recover.", provider))
    workflow.add_step("worker", Task("retry once", retry_policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0.0)))

    result = await workflow.run()

    assert result.output == "recovered"
    events = store.list_events(result.trace_id)
    assert any(event["event_type"] == "task.retry_scheduled" for event in events)


@pytest.mark.asyncio
async def test_event_driven_workflow(tmp_path):
    store = SQLiteStore(tmp_path / "agentmesh.db")
    provider = MockModelProvider(["handled start"])
    workflow = Workflow("test-events", WorkflowMode.EVENT_DRIVEN, store=store)
    workflow.add_agent(Agent("handler", "Handler", "Handle event.", provider))
    workflow.add_step("handler", "handle workflow start", trigger="workflow.start")

    result = await workflow.run({"event": "start"})

    assert result.output == "handled start"
    assert any(event["event_type"] == "event.received" for event in store.list_events(result.trace_id))

