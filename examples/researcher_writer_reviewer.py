import asyncio
import os

from agentmesh import Agent, MockModelProvider, SQLiteStore, Workflow, WorkflowMode


async def main() -> None:
    store = SQLiteStore(os.getenv("AGENTMESH_DB", ".agentmesh/agentmesh.db"))
    provider = MockModelProvider(
        [
            "Research: production teams need traces, retries, cost attribution, and replay.",
            "Draft: AgentMesh makes multi-agent runs inspectable from workflow to model call.",
            "Review: the draft is concise and includes observability value.",
        ]
    )
    workflow = Workflow("researcher-writer-reviewer-real", WorkflowMode.SEQUENTIAL, store=store)
    workflow.add_agent(Agent("researcher", "Researcher", "Find concrete facts.", provider, model="mock-researcher"))
    workflow.add_agent(Agent("writer", "Writer", "Write a short product note.", provider, model="mock-writer"))
    workflow.add_agent(Agent("reviewer", "Reviewer", "Review for correctness.", provider, model="mock-reviewer"))
    workflow.add_step("researcher", "Research why agent traceability matters", step_id="research")
    workflow.add_step("writer", "Write the note from research", depends_on=("research",), step_id="write")
    workflow.add_step("reviewer", "Review the note", depends_on=("write",), step_id="review")

    result = await workflow.run({"audience": "developers", "environment": "local"})
    print(f"trace_id={result.trace_id}")
    print(f"spans={len(store.list_spans(result.trace_id))}")
    print(f"model_calls={len(store.list_model_calls(result.trace_id))}")
    print(f"prompt_versions={len(store.list_prompt_versions(result.trace_id))}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
