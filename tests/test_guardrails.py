import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import agentmesh
from agentmesh import AgentHalted, ApprovalDenied, InMemoryExporter, PolicyViolation
from agentmesh.guardrails import Guardrails, HttpBackend, StoreBackend
from agentmesh.policy import ActionContext, Policy
from agentmesh.stores import create_store

GUARD = """
name: guard
limits: {max_repeated_calls: 2}
rules:
  - name: no-prod-deletes
    match: {tool: "delete_*", arguments: {env: production}}
    action: deny
    reason: Deleting production data needs a person.
  - name: refunds
    match: {tool: issue_refund}
    action: require_approval
approval: {timeout_seconds: 5}
"""


@pytest.fixture
def guarded(db_url, monkeypatch):
    """The SDK writing to a database, with guardrails reloading policies and halts on every call."""
    monkeypatch.setenv("AGENTMESH_GUARDRAILS_REFRESH_SECONDS", "0")
    client = agentmesh.init(db_path=db_url, service_name="support-bot", flush_interval=0.05)
    client.guardrails.approval_poll_seconds = 0.02
    store = create_store(db_url)
    yield store
    agentmesh.shutdown()
    store.close()


def _tools():
    calls = []

    @agentmesh.observe(kind="tool")
    def delete_user(user_id: str, env: str) -> str:
        calls.append(("delete_user", env))
        return "deleted"

    @agentmesh.observe(kind="tool")
    def search(q: str) -> list[str]:
        calls.append(("search", q))
        return [q]

    @agentmesh.observe(kind="tool")
    def issue_refund(amount: int) -> str:
        calls.append(("issue_refund", amount))
        return "refunded"

    return calls, delete_user, search, issue_refund


def _resolve_next_approval(store, approved, reason=None, delay=0.0):
    def worker():
        time.sleep(delay)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pending = store.list_approvals(status="pending")
            if pending:
                store.resolve_approval(pending[0]["approval_id"], approved, reason)
                return
            time.sleep(0.02)

    thread = threading.Thread(target=worker)
    thread.start()
    return thread


def test_sdk_blocks_denied_calls_and_breaks_loops(guarded):
    guarded.create_policy({"text": GUARD})
    calls, delete_user, search, _refund = _tools()

    with agentmesh.trace("ticket") as root:
        assert delete_user("u1", env="staging") == "deleted"
        with pytest.raises(PolicyViolation) as blocked:
            delete_user("u1", env="production")
        assert blocked.value.message == "Deleting production data needs a person."
        assert blocked.value.details["rule"] == "no-prod-deletes" and blocked.value.details["policy"] == "guard"
        search("same")
        search("same")
        with pytest.raises(PolicyViolation, match="likely loop"):
            search("same")
        search("different")

    assert calls == [("delete_user", "staging"), ("search", "same"), ("search", "same"), ("search", "different")]
    agentmesh.flush()
    decisions = guarded.list_policy_decisions(trace_id=root.trace_id)
    assert {(item["rule"], item["action"], item["enforced"]) for item in decisions} == {
        ("no-prod-deletes", "deny", True),
        ("limit:max_repeated_calls", "deny", True),
    }
    assert {item["service"] for item in decisions} == {"support-bot"}
    assert guarded.list_policy_decisions(action="blocked", trace_id=root.trace_id)[0]["target"].endswith(("delete_user", "search"))
    failed = [span["name"] for span in guarded.list_spans(root.trace_id) if span["status"] in {"failed", "error"}]
    assert sum(name.endswith("delete_user") for name in failed) == 1


def test_monitor_mode_records_would_block_without_stopping(guarded):
    guarded.create_policy({"text": GUARD.replace("name: guard", "name: guard\nmode: monitor")})
    calls, delete_user, _search, issue_refund = _tools()
    with agentmesh.trace("monitored") as root:
        delete_user("u1", env="production")
        issue_refund(10)
    assert [name for name, _ in calls] == ["delete_user", "issue_refund"]
    assert guarded.list_approvals(status="pending") == []
    agentmesh.flush()
    would_block = guarded.list_policy_decisions(action="would_block", trace_id=root.trace_id)
    assert {item["rule"] for item in would_block} == {"no-prod-deletes", "refunds"}
    assert guarded.policy_decision_summary("2000-01-01")["would_block"] == 2


def test_sdk_waits_for_approval(guarded):
    guarded.create_policy({"text": GUARD})
    calls, _delete, _search, issue_refund = _tools()

    with agentmesh.trace("refunds") as root:
        approver = _resolve_next_approval(guarded, approved=True)
        assert issue_refund(5) == "refunded"
        approver.join()
        approver = _resolve_next_approval(guarded, approved=False, reason="too large")
        with pytest.raises(ApprovalDenied, match="too large"):
            issue_refund(500)
        approver.join()

    assert calls == [("issue_refund", 5)]
    approvals = guarded.list_approvals()
    assert {item["status"] for item in approvals} == {"approved", "rejected"}
    assert all(item["arguments"]["_policy"]["rule"] == "refunds" for item in approvals)
    agentmesh.flush()
    outcomes = [item for item in guarded.list_policy_decisions(trace_id=root.trace_id) if item["details"].get("approval")]
    assert sorted(item["action"] for item in outcomes) == ["allow", "deny"]


def test_unanswered_approval_times_out(guarded):
    guarded.create_policy({"text": GUARD.replace("timeout_seconds: 5", "timeout_seconds: 0.2")})
    _calls, _delete, _search, issue_refund = _tools()
    with agentmesh.trace("slow reviewers"), pytest.raises(ApprovalDenied, match="No approval within"):
        issue_refund(5)


async def test_async_approval_does_not_block_the_event_loop(guarded):
    guarded.create_policy({"text": GUARD})

    @agentmesh.observe(kind="tool")
    async def issue_refund(amount: int) -> str:
        return "refunded"

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    beating = asyncio.create_task(heartbeat())
    approver = _resolve_next_approval(guarded, approved=True, delay=0.3)
    async with agentmesh.trace("async refunds"):
        assert await issue_refund(5) == "refunded"
    beating.cancel()
    await asyncio.to_thread(approver.join)
    assert ticks > 3


def test_halts_stop_services_agents_and_traces_until_released(guarded):
    _calls, _delete, search, _refund = _tools()

    @agentmesh.observe(kind="agent")
    def researcher(question: str) -> list[str]:
        return search(question)

    service_halt = guarded.create_halt({"scope": "service", "value": "support-bot", "reason": "incident 42"})
    with pytest.raises(AgentHalted, match="incident 42") as halted, agentmesh.trace("during incident"):
        search("x")  # a halt stops every span, so the trace itself does not start
    assert halted.value.details["halt_id"] == service_halt["halt_id"]
    guarded.release_halt(service_halt["halt_id"])
    with agentmesh.trace("after incident"):
        assert search("x") == ["x"]

    agent_halt = guarded.create_halt({"scope": "agent", "value": "researcher"})
    with agentmesh.trace("agent halted"), pytest.raises(AgentHalted):
        researcher("q")
    with agentmesh.trace("tools outside the agent still run"):
        assert search("q") == ["q"]
    guarded.release_halt(agent_halt["halt_id"])

    with agentmesh.trace("runaway") as runaway:
        assert search("a") == ["a"]
        guarded.create_halt({"scope": "trace", "value": runaway.trace_id})
        with pytest.raises(AgentHalted):
            search("b")
    with agentmesh.trace("other trace"):
        assert search("c") == ["c"]
    everything = guarded.create_halt({"scope": "all"})
    with pytest.raises(AgentHalted), agentmesh.trace("stop the world"):
        researcher("q")
    guarded.release_halt(everything["halt_id"])


def test_halt_validation(guarded):
    from agentmesh.policy import PolicyError

    with pytest.raises(PolicyError):
        guarded.create_halt({"scope": "galaxy"})
    with pytest.raises(PolicyError):
        guarded.create_halt({"scope": "trace"})
    assert guarded.release_halt("halt_missing") is None


def test_cost_limit_counts_llm_spend_and_disabled_policies_are_ignored(guarded):
    saved = guarded.create_policy({"spec": {"name": "budget", "limits": {"max_cost_usd": 1}}})

    def chat():
        with agentmesh.span("chat", kind="llm", attributes={"gen_ai.request.model": "gpt-4.1"}) as call:
            call.set_attribute("agentmesh.cost_usd", 0.6)

    with agentmesh.trace("expensive"):
        chat()
        chat()  # spend crosses $1 during this call, which completes
        with pytest.raises(PolicyViolation, match="limit"):
            chat()

    guarded.update_policy(saved["policy_id"], {"enabled": False})
    with agentmesh.trace("expensive again"):
        for _ in range(3):
            chat()


def test_policies_in_code_without_a_backend():
    exporter = InMemoryExporter()
    policy = {"name": "code", "rules": [{"name": "refunds", "match": {"tool": "issue_refund"}, "action": "require_approval"}, {"name": "warn-search", "match": {"tool": "search"}, "action": "warn"}]}
    agentmesh.init(exporter=exporter, policies=[policy])
    try:
        _calls, _delete, search, issue_refund = _tools()
        with agentmesh.trace("code policies"):
            assert search("x") == ["x"]
            with pytest.raises(ApprovalDenied, match="no AgentMesh server or database"):
                issue_refund(1)
        agentmesh.flush()
        spans = {span.name.rsplit(".", 1)[-1]: span for span in exporter.spans}
        warned = [event for event in spans["search"].events if event["name"] == "agentmesh.policy.decision"]
        assert warned[0]["attributes"]["agentmesh.policy.action"] == "warn"
        assert spans["issue_refund"].attributes["agentmesh.policy.blocked"] is True
    finally:
        agentmesh.shutdown()


def test_no_policies_means_no_guardrails_overhead():
    agentmesh.init(exporter=InMemoryExporter())
    try:
        assert agentmesh.get_client().guardrails is None
    finally:
        agentmesh.shutdown()
    agentmesh.init(exporter=InMemoryExporter(), policies=[{"name": "p", "limits": {"max_steps": 1}}], guardrails=False)
    try:
        assert agentmesh.get_client().guardrails is None
    finally:
        agentmesh.shutdown()


def test_policy_file_from_environment(tmp_path, monkeypatch):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text("name: from-file\nrules:\n  - {name: no-shell, match: {tool: shell}, action: deny}\n", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_POLICY_FILE", str(policy_file))
    agentmesh.init(exporter=InMemoryExporter())
    try:
        @agentmesh.observe(kind="tool")
        def shell(command: str) -> str:
            return "ran"

        with agentmesh.trace("file"), pytest.raises(PolicyViolation):
            shell("rm -rf /")
    finally:
        agentmesh.shutdown()


def test_openai_call_is_blocked_before_the_request():
    openai = pytest.importorskip("openai")
    httpx2 = pytest.importorskip("httpx2")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(500, json={"error": {"message": "should not be called"}})

    policy = {"name": "models", "rules": [{"name": "approved-models", "match": {"kind": "llm"}, "except": {"model": "gpt-4.1*"}, "action": "deny"}]}
    agentmesh.init(exporter=InMemoryExporter(), policies=[policy])
    agentmesh.instrument_openai()
    try:
        client = openai.OpenAI(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_retries=0)
        with agentmesh.trace("openai"), pytest.raises(PolicyViolation, match="approved-models"):
            client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": "hi"}])
        assert requests == []
    finally:
        agentmesh.uninstrument_openai()
        agentmesh.shutdown()


class _FailingBackend:
    def runtime_config(self):
        raise ConnectionError("server down")


def test_fail_open_by_default_and_fail_closed_when_asked():
    context = ActionContext(kind="tool", name="search", trace_id="t1")
    open_guardrails = Guardrails(_FailingBackend(), fail_closed=False)
    assert not open_guardrails.active
    assert open_guardrails.check(context) == []

    closed = Guardrails(_FailingBackend(), fail_closed=True)
    assert closed.active
    with pytest.raises(PolicyViolation, match="could not be loaded"):
        closed.check(ActionContext(kind="tool", name="search", trace_id="t1"))


def test_last_loaded_policies_survive_a_backend_outage():
    class Flaky:
        healthy = True

        def runtime_config(self):
            if not self.healthy:
                raise ConnectionError("down")
            return {"policies": [{"policy_id": "p1", "spec": {"name": "p", "rules": [{"name": "no-shell", "match": {"tool": "shell"}, "action": "deny"}]}}], "halts": []}

    backend = Flaky()
    guardrails = Guardrails(backend, refresh_seconds=0)
    context = ActionContext(kind="tool", name="shell", trace_id="t1")
    with pytest.raises(PolicyViolation):
        guardrails.check(context)
    backend.healthy = False
    with pytest.raises(PolicyViolation):
        guardrails.check(ActionContext(kind="tool", name="shell", trace_id="t1"))


def test_invalid_remote_policies_are_skipped():
    class Backend:
        def runtime_config(self):
            return {"policies": [{"policy_id": "bad", "spec": {"name": "bad", "mode": "strict"}}], "halts": []}

    guardrails = Guardrails(Backend(), policies=[Policy.from_spec({"name": "local", "limits": {"max_steps": 1}})])
    guardrails.check(ActionContext(kind="tool", name="a", trace_id="t1"))
    with pytest.raises(PolicyViolation, match="limit of 1 steps"):
        guardrails.check(ActionContext(kind="tool", name="b", trace_id="t1"))


async def test_runtime_tool_calls_and_agents_are_guarded(tmp_path, monkeypatch):
    from agentmesh import (
        Agent,
        MockModelProvider,
        PermissionLevel,
        SQLiteStore,
        Task,
        ToolCallRequest,
        ToolRegistry,
        Workflow,
        tool,
    )
    from agentmesh.errors import AgentMeshError

    monkeypatch.setenv("AGENTMESH_GUARDRAILS_REFRESH_SECONDS", "0")
    store = SQLiteStore(tmp_path / "runtime.db")
    store.create_policy({"spec": {"name": "runtime", "rules": [{"name": "no-wire", "match": {"tool": "wire_money"}, "action": "deny"}]}})
    ran = []

    @tool("wire_money", "Send money")
    def wire_money(arguments, context):
        ran.append(arguments)
        return {"sent": True}

    def workflow(name):
        agent = Agent("treasurer", "Treasurer", "Move money.", MockModelProvider(["done"]), ToolRegistry([wire_money]), {PermissionLevel.READ})
        flow = Workflow(name, store=store)
        flow.add_agent(agent)
        flow.add_step("treasurer", Task("pay", tool_calls=[ToolCallRequest("wire_money", {"amount": 100})]))
        return flow

    with pytest.raises(AgentMeshError) as blocked:
        await workflow("blocked-wire").run()
    assert isinstance(blocked.value, PolicyViolation)
    assert ran == []
    decisions = store.list_policy_decisions(action="blocked")
    assert decisions[0]["rule"] == "no-wire" and decisions[0]["agent"] == "treasurer"
    trace_id = decisions[0]["trace_id"]
    assert any(event["event_type"] == "policy.decision" for event in store.list_events(trace_id))

    halt = store.create_halt({"scope": "agent", "value": "treasurer"})
    with pytest.raises(AgentHalted):
        await workflow("halted-agent").run()
    store.release_halt(halt["halt_id"])
    store.delete_policy("runtime")
    assert (await workflow("allowed").run()).status == "succeeded"
    assert ran == [{"amount": 100}]


class _Server(BaseHTTPRequestHandler):
    approvals: dict = {}
    supported = True

    def log_message(self, *_args):
        return None

    def _send(self, status, payload=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/guardrails/runtime":
            if not self.supported:
                return self._send(404, {"detail": "Not Found"})
            assert self.headers["Authorization"] == "Bearer secret"
            spec = {"name": "remote", "rules": [{"name": "refunds", "match": {"tool": "issue_refund"}, "action": "require_approval"}], "approval": {"timeout_seconds": 5}}
            return self._send(200, {"policies": [{"policy_id": "p1", "spec": spec}], "halts": []})
        if self.path.startswith("/api/approvals/"):
            approval = self.approvals.get(self.path.rsplit("/", 1)[1])
            return self._send(200, approval) if approval else self._send(404, {"detail": "missing"})
        return self._send(404, {"detail": "Not Found"})

    def do_POST(self):  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        approval_id = f"approval_{len(self.approvals) + 1}"
        # the reviewer approves instantly
        self.approvals[approval_id] = {"approval_id": approval_id, "status": "approved", "tool": payload["tool"]}
        return self._send(201, {"approval_id": approval_id, "status": "pending"})


@pytest.fixture
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Server.approvals = {}
    _Server.supported = True
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_http_backend_loads_policies_and_requests_approvals(stub_server):
    guardrails = Guardrails(HttpBackend(stub_server, api_key="secret"), approval_poll_seconds=0.01)
    assert guardrails.active
    decisions = guardrails.check(ActionContext(kind="tool", name="issue_refund", trace_id="t1", arguments={"amount": 3}))
    assert decisions[0].action == "require_approval"
    assert _Server.approvals["approval_1"]["tool"] == "issue_refund"
    assert HttpBackend(stub_server).get_approval("approval_404") is None


def test_http_backend_treats_an_old_server_as_nothing_to_enforce(stub_server):
    _Server.supported = False
    guardrails = Guardrails(HttpBackend(stub_server), fail_closed=True)
    assert not guardrails.active
    assert guardrails.check(ActionContext(kind="tool", name="anything", trace_id="t1")) == []


def test_store_backend_reads_saved_policies(tmp_path):
    from agentmesh import SQLiteStore

    store = SQLiteStore(tmp_path / "backend.db")
    store.create_policy({"text": GUARD})
    store.create_policy({"text": "name: disabled-policy\nrules: [{name: all, match: {kind: any}, action: deny}]", "enabled": False})
    config = StoreBackend(store).runtime_config()
    assert [item["spec"]["name"] for item in config["policies"]] == ["guard"]


def test_remote_policies_refresh_in_the_background():
    class SlowServer:
        remote = True

        def __init__(self):
            self.calls = 0
            self.rule = "first"

        def runtime_config(self):
            self.calls += 1
            if self.calls > 1:
                time.sleep(0.5)  # a slow server
            spec = {"name": "p", "rules": [{"name": self.rule, "match": {"tool": "shell"}, "action": "deny"}]}
            return {"policies": [{"policy_id": "p1", "spec": spec}], "halts": []}

    server = SlowServer()
    guardrails = Guardrails(server, refresh_seconds=0)
    with pytest.raises(PolicyViolation, match="first"):
        guardrails.check(ActionContext(kind="tool", name="shell", trace_id="t1"))  # the first load waits
    server.rule = "second"
    started = time.monotonic()
    with pytest.raises(PolicyViolation, match="first"):
        guardrails.check(ActionContext(kind="tool", name="shell", trace_id="t1"))  # stale policies, no waiting
    assert time.monotonic() - started < 0.3
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        decisions, _verdict = guardrails.evaluate(ActionContext(kind="tool", name="shell", trace_id="t2"))
        if decisions and decisions[0].rule == "second":
            break
        time.sleep(0.05)
    assert decisions[0].rule == "second"


def test_load_failures_warn_once(caplog):
    guardrails = Guardrails(_FailingBackend(), refresh_seconds=0)
    with caplog.at_level("DEBUG", logger="agentmesh.guardrails"):
        for _ in range(4):
            guardrails.refresh()
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1


def test_approval_requests_respect_content_capture():
    class Recorder:
        def __init__(self):
            self.requests = []

        def runtime_config(self):
            spec = {"name": "p", "rules": [{"name": "refunds", "match": {"tool": "issue_refund"}, "action": "require_approval"}], "approval": {"timeout_seconds": 0.05}}
            return {"policies": [{"policy_id": "p1", "spec": spec}], "halts": []}

        def create_approval(self, trace_id, agent, target, arguments):
            self.requests.append(arguments)
            return "approval_1"

        def get_approval(self, approval_id):
            return {"status": "approved"}

    captured, private = Recorder(), Recorder()
    Guardrails(captured, approval_poll_seconds=0.01).check(ActionContext(kind="tool", name="issue_refund", trace_id="t1", arguments={"card": "4242", "amount": 5}))
    Guardrails(private, approval_poll_seconds=0.01, capture_content=False).check(ActionContext(kind="tool", name="issue_refund", trace_id="t1", arguments={"card": "4242", "amount": 5}))
    assert captured.requests[0]["card"] == "4242"
    assert private.requests[0]["argument_names"] == ["amount", "card"] and "4242" not in json.dumps(private.requests[0])


def test_missing_policy_file_has_a_clear_error(tmp_path):
    from agentmesh.policy import PolicyError

    with pytest.raises(PolicyError, match="policy file not found"):
        Guardrails(policies=[str(tmp_path / "missing.yaml")])
    broken = tmp_path / "broken.yaml"
    broken.write_text("name: broken\nlimits: {max_widgets: 1}\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="broken.yaml: unknown limit"):
        Guardrails(policies=[str(broken)])
