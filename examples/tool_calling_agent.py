import asyncio
import os
from pathlib import Path

from agentmesh import Agent, MockModelProvider, PermissionLevel, SQLiteStore, Task, ToolCallRequest, ToolRegistry, Workflow, tool


@tool("safe_file_summary", "Read a small local text file and return a summary", {"path": "string"})
def safe_file_summary(arguments, context):
    path = Path(str(arguments["path"]))
    text = path.read_text(encoding="utf-8")
    return {"path": str(path), "characters": len(text), "preview": text[:80]}


async def main() -> None:
    store = SQLiteStore(os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db"))
    sample = Path(".agentmesh/sample_tool_input.txt")
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text("AgentMesh traces safe local tool calls with input, output, duration, and status.", encoding="utf-8")
    provider = MockModelProvider(["The safe local tool read the file and returned a traceable summary."])
    agent = Agent(
        "tool_analyst",
        "Tool analyst",
        "Use the safe tool and explain the result.",
        provider,
        ToolRegistry([safe_file_summary]),
        {PermissionLevel.READ},
    )
    workflow = Workflow("tool-calling-agent-real", store=store)
    workflow.add_agent(agent)
    workflow.add_step(
        "tool_analyst",
        Task("Summarize a local file", tool_calls=[ToolCallRequest("safe_file_summary", {"path": str(sample)})]),
    )

    result = await workflow.run({"environment": "local"})
    print(f"trace_id={result.trace_id}")
    print(f"tool_calls={len(store.list_tool_calls(result.trace_id))}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
