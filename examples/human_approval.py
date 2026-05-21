import asyncio

from agentmesh import Agent, MockModelProvider, PermissionLevel, SQLiteStore, Task, ToolCallRequest, ToolRegistry, Workflow, tool


@tool(
    "archive_customer_record",
    "Archive a customer record",
    {"customer_id": "string"},
    permission=PermissionLevel.SENSITIVE,
    requires_approval=True,
)
def archive_customer_record(arguments, context):
    return {"archived": True, "customer_id": arguments["customer_id"]}


async def approve_tool(definition, arguments, context) -> bool:
    print(f"Approval requested for {definition.name}: {arguments}")
    return True


async def main() -> None:
    provider = MockModelProvider(["Approved action completed and audited."])
    agent = Agent(
        "operator",
        "Operations Agent",
        "Execute approved operational actions.",
        provider,
        ToolRegistry([archive_customer_record]),
        {PermissionLevel.READ, PermissionLevel.SENSITIVE},
    )
    workflow = Workflow("human-approval", store=SQLiteStore(".agentmesh/examples.db"))
    workflow.add_agent(agent)
    workflow.add_step(
        "operator",
        Task(
            "Archive the inactive customer record",
            tool_calls=[ToolCallRequest("archive_customer_record", {"customer_id": "cust_123"})],
        ),
    )

    result = await workflow.run(approval_callback=approve_tool)
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

