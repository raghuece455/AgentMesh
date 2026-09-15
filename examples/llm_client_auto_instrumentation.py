"""Auto-instrument the official OpenAI and Anthropic Python clients.

    pip install openai anthropic
    export ANTHROPIC_API_KEY=...   # and/or OPENAI_API_KEY=...
    python examples/llm_client_auto_instrumentation.py
    agentmesh dashboard

Every call records model, parameters, messages, output, tool calls, finish reason, and token usage
(including prompt-cache and reasoning tokens) with an estimated cost. Streaming works too.
"""

import os

import agentmesh

agentmesh.init(service_name="client-instrumentation-example")
agentmesh.instrument_anthropic()
agentmesh.instrument_openai()


def ask_claude(question: str) -> str:
    from anthropic import Anthropic

    client = Anthropic()
    with client.messages.stream(model="claude-haiku-4-5", max_tokens=300, messages=[{"role": "user", "content": question}]) as stream:
        return stream.get_final_text()


def ask_openai(question: str) -> str:
    from openai import OpenAI

    response = OpenAI().responses.create(model="gpt-5-mini", input=question)
    return response.output_text


with agentmesh.trace("compare-models", session_id="model-comparison", tags=["example"]):
    question = "In one sentence: why do AI agents need observability?"
    if os.getenv("ANTHROPIC_API_KEY"):
        print("Claude:", ask_claude(question))
    if os.getenv("OPENAI_API_KEY"):
        print("OpenAI:", ask_openai(question))
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print("Set ANTHROPIC_API_KEY and/or OPENAI_API_KEY to run this example.")

agentmesh.flush()
