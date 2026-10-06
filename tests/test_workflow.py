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



@pytest.mark.asyncio
async def test_finishing_a_run_supersedes_its_rows_instead_of_patching_them(tmp_path):
    """The runtime finished a run by rewriting a few columns, which a column store cannot take.

    SQLite only: the statements are read off sqlite3's trace callback.
    """
    store = SQLiteStore(tmp_path / "agentmesh.db")
    workflow = Workflow("test-append-only", WorkflowMode.SEQUENTIAL, store=store)
    workflow.add_agent(Agent("a", "First", "Return first.", MockModelProvider(["done"])))
    workflow.add_step("a", "step one")

    statements: list[str] = []
    store._conn.set_trace_callback(lambda sql: statements.append(" ".join(sql.split()).lower()))  # noqa: SLF001
    result = await workflow.run({"goal": "test"})
    store._conn.set_trace_callback(None)  # noqa: SLF001

    assert result.status == "succeeded"
    assert not [sql for sql in statements if sql.startswith("update ")], statements

    # The whole-row rewrite still settles the run, and keeps what it was started with.
    run = store._read(lambda conn: dict(conn.execute(  # noqa: SLF001
        "select status, ended_at, duration_ms, workflow_name, started_at from workflow_runs where trace_id = ?",
        (result.trace_id,),
    ).fetchone()))
    assert run["status"] == "succeeded" and run["ended_at"] and run["duration_ms"] is not None
    assert run["workflow_name"] == "test-append-only" and run["started_at"]
    trace = store.get_observable_trace(result.trace_id)
    assert trace["status"] == "succeeded" and trace["ended_at"]
