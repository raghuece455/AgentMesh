import asyncio
import os

from agentmesh import Agent, MockModelProvider, PermissionLevel, SQLiteStore, Task, ToolCallRequest, ToolRegistry, Workflow, tool


@tool(
    "send_release_notice",
    "Pretend to send a release notice",
    {"recipient": "string", "message": "string"},
    permission=PermissionLevel.SENSITIVE,
    requires_approval=True,
)
def send_release_notice(arguments, context):
    return {"sent": True, "recipient": arguments["recipient"], "side_effect": "simulated_email"}


async def approve_tool(definition, arguments, context) -> bool:
    print(f"approval_requested tool={definition.name} arguments={arguments}")
    await asyncio.sleep(0.1)
    return True


async def main() -> None:
    store = SQLiteStore(os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db"))
    agent = Agent(
        "release_operator",
        "Release operator",
        "Only perform sensitive actions after human approval.",
        MockModelProvider(["Approved release notice was sent and audited."]),
        ToolRegistry([send_release_notice]),
        {PermissionLevel.READ, PermissionLevel.SENSITIVE},
    )
    workflow = Workflow("human-approval-workflow-real", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "release_operator",
        Task(
            "Send release notice after approval",
            tool_calls=[ToolCallRequest("send_release_notice", {"recipient": "dev-team@example.com", "message": "AgentMesh alpha shipped"})],
        ),
    )

    result = await workflow.run({"environment": "local"}, approval_callback=approve_tool)
    print(f"trace_id={result.trace_id}")
    print(f"approvals={len(store.list_approvals(limit=10))}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
