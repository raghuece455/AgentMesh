import asyncio
import os

from agentmesh import Agent, MockModelProvider, OllamaProvider, SQLiteStore, Workflow


async def main() -> None:
    model = os.getenv("OLLAMA_MODEL")
    base_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    provider = OllamaProvider(model, base_url) if model else MockModelProvider(["Set OLLAMA_MODEL to call a local Ollama model."])

    store = SQLiteStore(".agentmesh/examples.db")
    workflow = Workflow("ollama-local-model", store=store)
    workflow.add_agent(Agent("local_agent", "Local model agent", "Answer with local-model style brevity.", provider))
    workflow.add_step("local_agent", "Describe AgentMesh in one sentence")

    result = await workflow.run()
    print(f"trace_id={result.trace_id}")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

