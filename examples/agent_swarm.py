"""Trace an agent swarm: a planner fans work out to researchers in other workers, they report to a
writer, and the writer hands off to a reviewer. Then open it as one run on the Swarms page.

Runs offline with stand-in tools and models. The workers are threads here, but they share nothing
except the JSON context passed with each task, exactly as separate processes or machines would.

    python examples/agent_swarm.py
    agentmesh dashboard      # then open Swarms
"""

from __future__ import annotations

import json
import queue
import random
import threading
import time

import agentmesh

DB = ".agentmesh/agentmesh.db"
RESEARCHERS = 12
TOPICS = ["hyperscaler capex", "cooling vendors", "power constraints", "chip supply", "pricing", "regulation"]


@agentmesh.observe(kind="tool")
def web_search(query: str) -> list[str]:
    time.sleep(random.uniform(0.01, 0.05))
    if "regulation" in query and random.random() < 0.5:
        raise TimeoutError("search provider timed out")
    return [f"https://example.com/{query.replace(' ', '-')}/{index}" for index in range(3)]


@agentmesh.observe(kind="llm", name="chat gpt-4.1-mini")
def summarize(sources: list[str]) -> str:
    span = agentmesh.get_current_span()
    span.set_model("gpt-4.1-mini", provider="openai")
    span.set_usage(input_tokens=2_000 + 400 * len(sources), output_tokens=300)
    return f"{len(sources)} sources agree"


@agentmesh.observe(kind="agent")
def researcher(topic: str) -> str:
    sources = web_search(f"{topic} 2027")
    notes = summarize(sources)
    agentmesh.send_message("writer", f"{topic}: {notes}")
    return notes


def worker(tasks: queue.Queue) -> None:
    """A worker process: it receives a task and the serialized swarm context, nothing else."""
    while True:
        message = tasks.get()
        if message is None:
            return
        task = json.loads(message)
        try:
            with agentmesh.trace(f"research {task['topic']}", spawned_by=task["context"]):
                researcher(task["topic"])
        except TimeoutError:
            pass  # recorded on the span; the swarm carries on without this topic
        finally:
            tasks.task_done()


@agentmesh.observe(kind="agent")
def planner(tasks: queue.Queue) -> None:
    context = agentmesh.swarm_context()  # the swarm plus this span, so workers link back to it
    for index in range(RESEARCHERS):
        tasks.put(json.dumps({"topic": TOPICS[index % len(TOPICS)], "context": context}))
    tasks.join()


@agentmesh.observe(kind="agent")
def writer() -> str:
    draft = summarize(["notes"] * RESEARCHERS)
    agentmesh.handoff("reviewer", "Draft ready for review")
    return draft


@agentmesh.observe(kind="agent")
def reviewer(draft: str) -> str:
    return f"approved: {draft}"


def main() -> None:
    agentmesh.init(db_path=DB, service_name="research-swarm")
    tasks: queue.Queue = queue.Queue()
    workers = [threading.Thread(target=worker, args=(tasks,), daemon=True) for _ in range(4)]
    for thread in workers:
        thread.start()

    with agentmesh.swarm("market research") as swarm, agentmesh.trace("market research", input="Size the liquid-cooling market") as run:
        planner(tasks)
        run.set_output(reviewer(writer()))

    for _ in workers:
        tasks.put(None)
    agentmesh.flush()

    from agentmesh.stores import create_store

    detail = create_store(DB).get_swarm(swarm.id)
    summary = detail["summary"]
    print(f"Swarm {swarm.id}: {summary['agents']} agents across {summary['traces']} traces, "
          f"max fan-out {summary['max_fan_out']}, {summary['failed_agents']} failed, {summary['messages']} messages")
    for insight in detail["insights"]:
        print(f"  - {insight['title']}")
    print("Open it with `agentmesh dashboard`, then Swarms.")
    agentmesh.shutdown()


if __name__ == "__main__":
    main()
