"""Stop a misbehaving agent while it runs: block a dangerous tool, break a loop, wait for approval, halt.

Runs offline with a local database and stand-in tools. With a real agent, the same policy applies to
@agentmesh.observe tools, instrumented OpenAI/Anthropic calls, and the AgentMesh runtime.

    python examples/guardrails.py
    agentmesh dashboard      # then open Guardrails and the "support ticket" trace
"""

from __future__ import annotations

import threading
import time

import agentmesh
from agentmesh import AgentHalted, ApprovalDenied, PolicyViolation
from agentmesh.stores import create_store

DB = ".agentmesh/agentmesh.db"
POLICY = """
name: guardrails-example
mode: enforce
limits:
  max_repeated_calls: 3
rules:
  - name: no-production-deletes
    match: {tool: "delete_*", arguments: {env: production}}
    action: deny
    reason: Deleting production data needs a person.
  - name: refunds-need-approval
    match: {tool: issue_refund}
    action: require_approval
approval:
  timeout_seconds: 30
"""


@agentmesh.observe(kind="tool")
def delete_customer(customer_id: str, env: str) -> str:
    return f"deleted {customer_id} in {env}"


@agentmesh.observe(kind="tool")
def search_orders(query: str) -> list[str]:
    return []  # never finds anything, so a naive agent keeps retrying


@agentmesh.observe(kind="tool")
def issue_refund(order_id: str, amount: float) -> str:
    return f"refunded ${amount} for {order_id}"


@agentmesh.observe(kind="agent")
def support_agent(request: str) -> list[str]:
    log = []
    try:
        delete_customer("c-19", env="production")
    except PolicyViolation as exc:
        log.append(f"blocked:  {exc.message}")

    for attempt in range(1, 6):
        try:
            search_orders("order 1042")
        except PolicyViolation as exc:
            log.append(f"stopped:  attempt {attempt}: {exc.message}")
            break

    log.append(f"approved: {issue_refund('1042', 25.0)}")
    try:
        issue_refund("1043", 900.0)
    except ApprovalDenied as exc:
        log.append(f"denied:   {exc.message}")
    return log


def reviewer(store, decisions: list[bool]) -> None:
    """Stands in for a person on the Approvals page: approve the first refund, reject the second."""
    for approved in decisions:
        while not (pending := store.list_approvals(status="pending")):
            time.sleep(0.1)
        store.resolve_approval(pending[0]["approval_id"], approved, None if approved else "Over the $500 limit")


def main() -> None:
    store = create_store(DB)
    if store.get_policy("guardrails-example"):
        store.delete_policy("guardrails-example")
    store.create_policy({"text": POLICY})

    agentmesh.init(db_path=DB, service_name="support-bot")
    agentmesh.get_client().guardrails.approval_poll_seconds = 0.2
    threading.Thread(target=reviewer, args=(store, [True, False]), daemon=True).start()

    with agentmesh.trace("support ticket") as ticket:
        for line in support_agent("Close my account and refund order 1042"):
            print(line)

    halt = store.create_halt({"scope": "service", "value": "support-bot", "reason": "Incident 7: pausing support-bot"})
    agentmesh.get_client().guardrails.refresh()  # running agents pick this up within a few seconds on their own
    try:
        with agentmesh.trace("next ticket"):
            support_agent("Where is my order?")
    except AgentHalted as exc:
        print(f"halted:   {exc.message}")
    store.release_halt(halt["halt_id"])

    agentmesh.flush()
    blocked = store.list_policy_decisions(trace_id=ticket.trace_id)
    print(f"\n{len(blocked)} guardrail decisions recorded on trace {ticket.trace_id}")
    print("Open the dashboard with `agentmesh dashboard` and go to Guardrails.")
    agentmesh.shutdown()


if __name__ == "__main__":
    main()
