"""Turn traces into a regression dataset, run two versions of an agent over it, and compare.

Runs offline: the "model" and the LLM judge are deterministic stand-ins. Swap in real calls
(an OpenAI/Anthropic client, or any AgentMesh ModelProvider) to use it for real.

    python examples/datasets_experiments.py
    agentmesh dashboard      # then open Datasets & Evals
"""

from __future__ import annotations

import agentmesh
from agentmesh import Contains, ExactMatch, LLMJudge
from agentmesh.stores import create_store

DB = ".agentmesh/agentmesh.db"
KNOWLEDGE = {
    "refund": "Refunds reach your card within 5 business days.",
    "canada": "Yes, we ship to Canada in 4-7 business days.",
    "password": "Use Forgot password on the sign-in page to get a reset link.",
}


@agentmesh.observe(kind="retrieval")
def search_docs(question: str) -> str:
    return next((text for key, text in KNOWLEDGE.items() if key in question.lower()), "")


@agentmesh.observe(kind="agent")
def support_agent_v1(question: str) -> str:
    return "Please contact support." if "canada" in question.lower() else search_docs(question)


@agentmesh.observe(kind="agent")
def support_agent_v2(question: str) -> str:
    return search_docs(question) or "I don't know yet."


def judge(prompt: str) -> str:
    """Stand-in for a model call: return JSON like {"score": 0.9, "reason": "..."}."""
    answer = prompt.split("Actual output:", 1)[1]
    return '{"score": 1, "reason": "cites the policy"}' if "business days" in answer or "reset link" in answer else '{"score": 0.2, "reason": "does not answer"}'


def main() -> None:
    agentmesh.init(db_path=DB, service_name="support-bot")
    store = create_store(DB)

    # 1. Record a production-like trace, then keep its good answer as a test case.
    with agentmesh.trace("support", input="How long does a refund take?") as root:
        root.set_output(support_agent_v2("How long does a refund take?"))
    agentmesh.flush()
    store.delete_dataset("support-regressions")  # start fresh each time the example runs
    store.create_dataset("support-regressions", description="Questions with approved answers")
    store.add_trace_to_dataset("support-regressions", root.trace_id)
    store.add_dataset_items(
        "support-regressions",
        [
            {"item_id": "canada", "input": "Do you ship to Canada?", "expected": KNOWLEDGE["canada"]},
            {"item_id": "password", "input": "How do I reset my password?", "expected": KNOWLEDGE["password"]},
        ],
    )

    # 2. Run both versions over the dataset and score every answer.
    evaluators = [ExactMatch(), Contains(), LLMJudge("correctness", judge=judge)]
    v1 = agentmesh.run_experiment("support-regressions", support_agent_v1, evaluators, name="support v1")
    v2 = agentmesh.run_experiment("support-regressions", support_agent_v2, evaluators, name="support v2")
    print(v1.format_summary())
    print(v2.format_summary())

    # 3. Compare item by item before shipping v2.
    comparison = store.compare_experiments(v1.experiment_id, v2.experiment_id)
    print("\nv1 -> v2:", comparison["counts"])
    for item in comparison["items"]:
        if item["change"] != "unchanged":
            print(f"  {item['change']:>9}: {item['input']}")
    agentmesh.shutdown()


if __name__ == "__main__":
    main()
