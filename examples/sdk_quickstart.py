"""Trace an ordinary Python agent with the AgentMesh SDK. Runs offline, no API keys.

    python examples/sdk_quickstart.py
    agentmesh dashboard          # then open http://127.0.0.1:8787 -> Sessions / Traces
"""

import asyncio
import random

import agentmesh

agentmesh.init(service_name="travel-assistant", environment="dev")


@agentmesh.observe(kind="tool")
def search_flights(origin: str, destination: str) -> list[dict]:
    return [{"flight": "AM101", "price": 420}, {"flight": "AM205", "price": 380}]


@agentmesh.observe(kind="tool")
def book_flight(flight: str) -> dict:
    if random.random() < 0.3:
        raise TimeoutError("booking provider did not respond")
    return {"flight": flight, "confirmation": "XK42"}


@agentmesh.observe(kind="llm", name="chat claude-haiku-4-5")
async def call_model(prompt: str) -> str:
    """Stand-in for a real model call: record the model and usage like an instrumented client would."""
    await asyncio.sleep(0.05)
    span = agentmesh.get_current_span()
    span.set_model("claude-haiku-4-5", provider="anthropic", temperature=0.2)
    span.set_usage(input_tokens=1_800 + len(prompt), output_tokens=120, cache_read_tokens=1_500)
    return "Book the cheapest flight."


@agentmesh.observe(kind="agent", name="travel_agent")
async def travel_agent(request: str) -> str:
    flights = search_flights("ICN", "SFO")
    plan = await call_model(f"User wants: {request}. Options: {flights}")
    cheapest = min(flights, key=lambda item: item["price"])
    try:
        booking = book_flight(cheapest["flight"])
    except TimeoutError:
        return f"{plan} Booking failed, please retry."
    return f"Booked {booking['flight']} (confirmation {booking['confirmation']})."


async def main() -> None:
    for turn, request in enumerate(["Find me a flight to San Francisco", "Book the cheapest one"], start=1):
        with agentmesh.trace(f"turn-{turn}", session_id="trip-planning-7", user_id="traveler-3", tags=["example"]) as root:
            answer = await travel_agent(request)
            root.set_output(answer)
            agentmesh.score("helpful", "failed" not in answer)
        print(f"turn {turn}: {answer}\n  trace_id={root.trace_id}")
    agentmesh.flush()
    print("\nOpen the dashboard with: agentmesh dashboard")


if __name__ == "__main__":
    asyncio.run(main())
