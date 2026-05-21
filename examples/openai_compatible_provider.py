import asyncio
import os

from agentmesh import Agent, MockModelProvider, OpenAICompatibleProvider, SQLiteStore, Workflow


async def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    provider = (
        OpenAICompatibleProvider(base_url, api_key, model)
        if api_key
        else MockModelProvider(["Set OPENAI_API_KEY to call a real OpenAI-compatible endpoint."])
    )

    store = SQLiteStore(".agentmesh/examples.db")
    workflow = Workflow("openai-compatible-provider", store=store)
    workflow.add_agent(Agent("assistant", "Assistant", "Answer concisely.", provider))
    workflow.add_step("assistant", "Explain why trace IDs matter")

    result = await workflow.run()
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
