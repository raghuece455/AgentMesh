import asyncio
import os

from agentmesh import (
    Agent,
    AgentMeshError,
    MockModelProvider,
    PermissionLevel,
    RetryPolicy,
    SQLiteStore,
    Task,
    ToolCallRequest,
    ToolRegistry,
    Workflow,
    tool,
)
from agentmesh.debug import FailedRunDiagnosis
from agentmesh.errors import ErrorKind


@tool("unstable_tool", "Always fail so retry and diagnosis paths are visible")
def unstable_tool(arguments, context):
    raise AgentMeshError("Intentional tool failure for debugging example", ErrorKind.TOOL, {"arguments": arguments}, retryable=True)


async def main() -> None:
    store = SQLiteStore(os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db"))
    agent = Agent(
        "debugger",
        "Debugging agent",
        "Try the tool and surface failures.",
        MockModelProvider(["This should not be reached because the tool fails first."]),
        ToolRegistry([unstable_tool]),
        {PermissionLevel.READ},
    )
    workflow = Workflow("failed-run-debugging-real", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "debugger",
        Task(
            "Trigger a controlled failure",
            tool_calls=[ToolCallRequest("unstable_tool", {"input": "boom"})],
            retry_policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0.0),
        ),
    )

    trace_id = ""
    try:
        await workflow.run({"environment": "local"})
    except AgentMeshError as exc:
        trace_id = str(exc.details.get("trace_id", ""))
        print(f"failed=true kind={exc.kind.value}")
    if not trace_id:
        traces = store.list_observable_traces(1, {"workflow": "failed-run-debugging-real"})
        trace_id = str(traces[0]["trace_id"])
    print(f"trace_id={trace_id}")
    print(FailedRunDiagnosis(store).diagnose(trace_id))


if __name__ == "__main__":
    asyncio.run(main())
