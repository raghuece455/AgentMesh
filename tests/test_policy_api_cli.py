import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

import agentmesh
from agentmesh.dashboard import create_app

POLICY = """
name: support-guardrails
mode: monitor
limits:
  max_repeated_calls: 2
rules:
  - name: refunds-need-approval
    match: {tool: issue_refund}
    action: require_approval
"""


def _record_looping_trace(db, guardrails=False):
    agentmesh.init(db_path=str(db), service_name="support-bot", flush_interval=0.05, guardrails=guardrails)
    try:
        @agentmesh.observe(kind="tool", name="search")
        def search(q):
            return [q]

        @agentmesh.observe(kind="tool", name="issue_refund")
        def issue_refund(amount):
            return "ok"

        with agentmesh.trace("looping ticket") as root:
            for _ in range(4):
                search("same")
            issue_refund(5)
        with agentmesh.trace("healthy ticket"):
            search("once")
        agentmesh.flush()
        return root.trace_id
    finally:
        agentmesh.shutdown()


def test_policy_api_crud_validation_and_simulation(db_url):
    trace_id = _record_looping_trace(db_url)
    client = TestClient(create_app(db_url))

    invalid = client.post("/api/policies/validate", json={"text": "name: x\nmode: strict"})
    assert invalid.status_code == 200 and invalid.json()["valid"] is False
    assert any("mode must be one of" in error for error in invalid.json()["errors"])
    assert client.post("/api/policies/validate", json={"text": POLICY}).json()["valid"] is True

    rejected = client.post("/api/policies", json={"text": "name: x\nrules: nope"})
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["error"] == "invalid_policy" and rejected.json()["detail"]["errors"]

    created = client.post("/api/policies", json={"text": POLICY})
    assert created.status_code == 201
    policy = created.json()
    assert policy["name"] == "support-guardrails" and policy["mode"] == "monitor" and policy["enabled"]
    assert "refunds-need-approval" in policy["source_text"]
    assert client.post("/api/policies", json={"text": POLICY}).status_code == 422  # duplicate name

    assert client.get("/api/policies").json()[0]["policy_id"] == policy["policy_id"]
    assert client.get("/api/policies/support-guardrails").json()["policy_id"] == policy["policy_id"]
    assert client.get("/api/policies/missing").status_code == 404

    draft = client.post("/api/policies/simulate", json={"text": POLICY})
    assert draft.status_code == 200
    report = draft.json()
    assert report["traces_evaluated"] == 2 and report["traces_affected"] == 1
    assert report["blocked_calls"] == 2 and report["approval_calls"] == 1
    assert report["traces"][0]["trace_id"] == trace_id
    saved = client.post("/api/policies/simulate", json={"policy": "support-guardrails", "hours": 1}).json()
    assert saved["traces_affected"] == 1
    assert client.post("/api/policies/simulate", json={"policy": "missing"}).status_code == 404
    assert client.post("/api/policies/simulate", json={"spec": {"name": "bad"}}).status_code == 422
    assert client.post("/api/policies/simulate", json={"text": POLICY, "limit": "lots"}).status_code == 422
    assert client.post("/api/policies/simulate", json={"text": POLICY, "hours": "yesterday"}).status_code == 422

    runtime = client.get("/api/guardrails/runtime").json()
    assert [item["policy_id"] for item in runtime["policies"]] == [policy["policy_id"]]
    disabled = client.patch(f"/api/policies/{policy['policy_id']}", json={"enabled": False})
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    assert client.get("/api/guardrails/runtime").json()["policies"] == []
    enforcing = client.patch("/api/policies/support-guardrails", json={"text": POLICY.replace("mode: monitor", "mode: enforce"), "enabled": True})
    assert enforcing.json()["mode"] == "enforce"
    monitoring = client.patch("/api/policies/support-guardrails", json={"mode": "monitor"}).json()
    assert monitoring["mode"] == "monitor" and "mode: monitor" in monitoring["source_text"]
    assert "refunds-need-approval" in monitoring["source_text"]  # the saved YAML is kept, not regenerated
    client.patch("/api/policies/support-guardrails", json={"mode": "enforce"})
    assert client.patch("/api/policies/support-guardrails", json={"text": "name: renamed\nmode: nope"}).status_code == 422
    assert client.patch("/api/policies/missing", json={"enabled": True}).status_code == 404

    summary = client.get("/api/guardrails/summary").json()
    assert summary["policies"] == 1 and summary["enforcing_policies"] == 1 and summary["active_halts"] == 0

    assert client.delete("/api/policies/support-guardrails").json() == {"deleted": True}
    assert client.delete("/api/policies/support-guardrails").status_code == 404


def test_decisions_halts_and_approvals_api(db_url):
    client = TestClient(create_app(db_url))
    client.post("/api/policies", json={"text": POLICY.replace("mode: monitor", "mode: enforce")})

    agentmesh.init(db_path=str(db_url), service_name="support-bot", flush_interval=0.05)
    try:
        @agentmesh.observe(kind="tool", name="search")
        def search(q):
            return [q]

        with agentmesh.trace("blocked loop") as root:
            search("same")
            search("same")
            with pytest.raises(agentmesh.PolicyViolation):
                search("same")
        agentmesh.flush()
    finally:
        agentmesh.shutdown()

    decisions = client.get("/api/policy-decisions", params={"action": "blocked"}).json()
    assert len(decisions) == 1 and decisions[0]["rule"] == "limit:max_repeated_calls"
    assert decisions[0]["trace_id"] == root.trace_id and decisions[0]["service"] == "support-bot"
    assert client.get("/api/policy-decisions", params={"action": "nonsense"}).status_code == 422
    assert client.get("/api/policy-decisions", params={"trace_id": "0" * 32}).json() == []
    assert client.get("/api/guardrails/summary").json()["decisions"]["blocked"] == 1
    detail = client.get(f"/api/traces/{root.trace_id}").json()
    assert [item["rule"] for item in detail["policy_decisions"]] == ["limit:max_repeated_calls"]

    assert client.post("/api/halts", json={"scope": "planet"}).status_code == 422
    assert client.post("/api/halts", json={"scope": "agent"}).status_code == 422
    odd = client.post("/api/halts", json={"scope": "all", "reason": {"ticket": 42}})
    assert odd.status_code == 201 and "42" in odd.json()["reason"]
    client.post(f"/api/halts/{odd.json()['halt_id']}/release")
    halt = client.post("/api/halts", json={"scope": "service", "value": "support-bot", "reason": "incident"})
    assert halt.status_code == 201 and halt.json()["created_by"] == "dashboard"
    halt_id = halt.json()["halt_id"]
    assert [item["halt_id"] for item in client.get("/api/guardrails/runtime").json()["halts"]] == [halt_id]
    assert client.get("/api/guardrails/summary").json()["active_halts"] == 1
    released = client.post(f"/api/halts/{halt_id}/release")
    assert released.status_code == 200 and released.json()["released_by"] == "dashboard"
    assert client.get("/api/halts").json() == []
    assert halt_id in [item["halt_id"] for item in client.get("/api/halts", params={"active": False}).json()]
    assert client.post("/api/halts/halt_missing/release").status_code == 404
    actions = {entry["action"] for entry in client.get("/api/audit-logs").json()}
    assert {"guardrails.halt", "guardrails.release"} <= actions

    assert client.post("/api/approvals", json={"agent": "bot"}).status_code == 422
    approval = client.post("/api/approvals", json={"trace_id": root.trace_id, "agent": "bot", "tool": "issue_refund", "arguments": {"amount": 5}})
    assert approval.status_code == 201 and approval.json()["status"] == "pending"
    approval_id = approval.json()["approval_id"]
    assert client.get(f"/api/approvals/{approval_id}").json()["arguments"] == {"amount": 5}
    assert client.get("/api/approvals/approval_missing").status_code == 404


def test_guardrail_endpoints_require_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTMESH_AUTH_MODE", "api_key")
    monkeypatch.setenv("AGENTMESH_API_KEY", "secret")
    client = TestClient(create_app(tmp_path / "auth.db"))
    assert client.get("/api/guardrails/runtime").status_code == 401
    assert client.post("/api/halts", json={"scope": "all"}).status_code == 401
    assert client.get("/api/guardrails/runtime", headers={"Authorization": "Bearer secret"}).status_code == 200


def _cli(*args, db):
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}
    return subprocess.run([sys.executable, "-m", "agentmesh.cli", "--db", str(db), *args], capture_output=True, text=True, env=env, check=False)


def test_policy_and_halt_cli(tmp_path):
    db = tmp_path / "cli.db"
    _record_looping_trace(db)
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(POLICY, encoding="utf-8")
    broken_file = tmp_path / "broken.yaml"
    broken_file.write_text("name: broken\nlimits: {max_widgets: 1}\n", encoding="utf-8")

    valid = _cli("policy", "validate", str(policy_file), db=db)
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["valid"] is True
    invalid = _cli("policy", "validate", str(broken_file), db=db)
    assert invalid.returncode == 1 and "unknown limit 'max_widgets'" in invalid.stdout

    simulated = _cli("policy", "simulate", str(policy_file), db=db)
    assert simulated.returncode == 0, simulated.stderr
    assert json.loads(simulated.stdout)["traces_affected"] == 1

    applied = _cli("policy", "apply", str(policy_file), "--disabled", db=db)
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["enabled"] is False
    reapplied = json.loads(_cli("policy", "apply", str(policy_file), db=db).stdout)
    assert reapplied["enabled"] is True and reapplied["policy_id"] == json.loads(applied.stdout)["policy_id"]
    assert [item["name"] for item in json.loads(_cli("policy", "list", db=db).stdout)] == ["support-guardrails"]
    assert json.loads(_cli("policy", "simulate", "support-guardrails", "--hours", "1", db=db).stdout)["approval_calls"] == 1
    assert json.loads(_cli("policy", "disable", "support-guardrails", db=db).stdout)["enabled"] is False
    assert json.loads(_cli("policy", "show", "support-guardrails", db=db).stdout)["mode"] == "monitor"
    assert _cli("policy", "show", "missing", db=db).returncode != 0
    assert json.loads(_cli("policy", "decisions", "--action", "blocked", db=db).stdout) == []
    assert json.loads(_cli("policy", "remove", "support-guardrails", db=db).stdout) == {"deleted": True}

    halt = _cli("halt", "create", "--agent", "researcher", "--reason", "runaway", db=db)
    assert halt.returncode == 0, halt.stderr
    halt_id = json.loads(halt.stdout)["halt_id"]
    assert [item["halt_id"] for item in json.loads(_cli("halt", "list", db=db).stdout)] == [halt_id]
    everything = json.loads(_cli("halt", "create", "--all", db=db).stdout)
    assert everything["scope"] == "all" and everything["value"] is None
    assert json.loads(_cli("halt", "release", halt_id, db=db).stdout)["released_at"]
    assert [item["halt_id"] for item in json.loads(_cli("halt", "list", db=db).stdout)] == [everything["halt_id"]]
    assert len(json.loads(_cli("halt", "list", "--all", db=db).stdout)) == 2
    assert _cli("halt", "release", "halt_missing", db=db).returncode != 0
    assert _cli("halt", "create", db=db).returncode != 0  # a scope is required
