# Workflows

A workflow orchestrates agents and tasks. Every `workflow.run()` automatically creates a trace ID and records everything — you write the business logic, AgentMesh handles the observability.

---

## Basic Workflow

```python
import asyncio
from agentmesh import Agent, MockModelProvider, Workflow, WorkflowMode, SQLiteStore

async def main():
    store    = SQLiteStore()
    provider = MockModelProvider(["Plan done.", "Draft written.", "Review approved."])

    workflow = Workflow("research-report", mode=WorkflowMode.SEQUENTIAL, store=store)
    workflow.add_agent(Agent("planner",  "Planner",  "Make a structured plan.", provider))
    workflow.add_agent(Agent("writer",   "Writer",   "Write clearly.",          provider))
    workflow.add_agent(Agent("reviewer", "Reviewer", "Check for accuracy.",     provider))

    workflow.add_step("planner",  "Plan the report structure", step_id="plan")
    workflow.add_step("writer",   "Write the report",          step_id="write",  depends_on=("plan",))
    workflow.add_step("reviewer", "Review and approve",        step_id="review", depends_on=("write",))

    result = await workflow.run({"topic": "AI observability 2025"})
    print(f"trace_id : {result.trace_id}")
    print(f"status   : {result.status}")
    print(f"output   : {result.output}")

asyncio.run(main())
```

---

## Workflow Modes

### Sequential

Steps run one after another. Each step automatically receives the previous step's output.

```python
workflow = Workflow("pipeline", mode=WorkflowMode.SEQUENTIAL)
```

### Parallel

All steps run at the same time. Total time equals the longest step. Use when steps don't depend on each other.

```python
workflow = Workflow("parallel-analysis", mode=WorkflowMode.PARALLEL)
workflow.add_step("sentiment-agent", "Analyse sentiment")
workflow.add_step("entity-agent",    "Extract entities")
workflow.add_step("topic-agent",     "Classify topic")
# All three start simultaneously
```

### Hierarchical (DAG)

Steps run based on their `depends_on` graph. Independent steps run in parallel; dependent steps wait. This is the most flexible mode for complex pipelines.

```python
workflow = Workflow("etl", mode=WorkflowMode.HIERARCHICAL)
workflow.add_step("fetch",     "Fetch raw data",         step_id="f")
workflow.add_step("clean",     "Clean the data",         step_id="c",  depends_on=("f",))
workflow.add_step("analyse",   "Statistical analysis",   step_id="a",  depends_on=("c",))
workflow.add_step("visualise", "Generate charts",        step_id="v",  depends_on=("c",))
workflow.add_step("report",    "Combine into report",    step_id="r",  depends_on=("a", "v"))
```

`analyse` and `visualise` both run in parallel after `clean`. `report` waits for both.

### Event-Driven

Steps are triggered by named events. Useful for reactive pipelines and alert systems.

```python
from agentmesh import AsyncEventBus, Workflow, WorkflowMode

bus = AsyncEventBus()
workflow = Workflow("alerts", mode=WorkflowMode.EVENT_DRIVEN, event_bus=bus)
workflow.add_step("alert-agent", "Handle system alert", trigger="system.alert")

# Elsewhere:
await bus.publish("system.alert", {"severity": "critical", "message": "Memory spike"})
```

---

## Budget and Cost Control

Stop runaway workflows before they burn through your API budget.

```python
from agentmesh import BudgetLimiter, Workflow

budget = BudgetLimiter(
    max_cost_usd=2.00,         # hard stop at $2 total spend
    max_total_tokens=50_000,   # or 50k tokens — whichever comes first
)
workflow = Workflow("guarded-run", budget=budget)
```

When the budget is exceeded, `BudgetExceeded` is raised, the workflow stops, and the event is recorded in the trace.

---

## Retry Policy

Configure how AgentMesh retries failing steps. Uses exponential backoff with full jitter to avoid thundering-herd problems.

```python
from agentmesh import Task, RetryPolicy

task = Task(
    "Fetch and summarise data",
    retry_policy=RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=1.0,
        backoff_factor=2.0,
    ),
)
workflow.add_step("fetcher-agent", task)
```

---

## Resume from Checkpoint

If a long workflow fails halfway through, resume it from the last saved checkpoint — completed steps are not re-run.

```python
# Get checkpoint IDs from CLI or dashboard
result = await workflow.run_from_checkpoint("ckpt_abc123")
```

```bash
agentmesh checkpoints list <trace_id>
agentmesh checkpoints show <checkpoint_id>
```

---

## WorkflowResult Fields

```python
result = await workflow.run()

result.trace_id    # paste into the dashboard search to find this exact run
result.status      # "succeeded" or "failed"
result.output      # text output of the final step
result.outputs     # dict[step_id → AgentResult] for every step
result.events      # list of all recorded events (also queryable via CLI/dashboard)
```

---

## Running Examples

```bash
python examples/hello_agent.py
python examples/researcher_writer_reviewer.py
python examples/parallel_multi_agent.py
python examples/failed_run_debugging.py
python examples/cost_budget_workflow.py
python examples/human_approval_workflow.py
```
