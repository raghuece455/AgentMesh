import hashlib
import hmac
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import agentmesh
from agentmesh.alerts import _mask_url, parse_minutes, render_payload
from agentmesh.dashboard import create_app
from agentmesh.stores import create_store


@pytest.fixture
def webhook():
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            received.append({"path": self.path, "headers": {key.lower(): value for key, value in self.headers.items()}, "raw": body, "json": json.loads(body)})
            status = 500 if self.path == "/broken" else 204
            self.send_response(status)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def _record_activity(db_path):
    agentmesh.init(db_path=str(db_path), flush_interval=0.05)
    try:
        for index in range(6):
            try:
                with agentmesh.trace("checkout", tags=["alerts"]):
                    if index < 3:
                        raise RuntimeError("payment provider down")
            except RuntimeError:
                pass
        with agentmesh.trace("research") as root:
            with agentmesh.span("summarize", kind="llm") as llm:
                llm.set_model("claude-sonnet-4-5", "anthropic")
                llm.set_usage(input_tokens=1_000_000, output_tokens=1000)
        expensive_trace = root.trace_id
        with agentmesh.trace("looper") as looper:
            for _ in range(4):
                with agentmesh.span("search_docs", kind="tool", input={"q": "refund policy"}):
                    pass
        agentmesh.flush()
        return expensive_trace, looper.trace_id
    finally:
        agentmesh.shutdown()


def test_alert_rules_fire_once_resolve_and_sign_webhooks(db_url, webhook):
    url, received = webhook
    expensive_trace, loop_trace = _record_activity(db_url)
    store = create_store(db_url)

    store.create_alert_rule(
        {"name": "checkout failures", "kind": "failure_rate", "threshold": 0.4, "window": "15m",
         "filters": {"workflow": "checkout", "min_runs": 5}, "channel": {"url": f"{url}/generic", "secret": "s3cr3t"}}
    )
    store.create_alert_rule({"name": "failed runs", "kind": "failure_count", "threshold": 3, "channel": {"url": f"{url}/count"}})
    store.create_alert_rule({"name": "pricey trace", "kind": "trace_cost", "threshold": 1.0, "channel": {"url": f"{url}/slack", "format": "slack"}})
    store.create_alert_rule({"name": "tool loops", "kind": "loop_detected", "threshold": 3, "channel": {"url": f"{url}/discord", "format": "discord"}})
    store.create_alert_rule({"name": "daily spend", "kind": "cost", "threshold": 100, "window": "1d"})
    store.create_alert_rule({"name": "slow runs", "kind": "latency_p95", "threshold": 60_000, "filters": {"min_runs": 1}})
    store.create_alert_rule({"name": "failures today", "kind": "failure_count", "threshold": 1, "window": "1d"})
    with pytest.raises(ValueError):
        store.create_alert_rule({"name": "checkout failures", "kind": "cost", "threshold": 1})

    fired = store.check_alerts()
    assert {event["rule_name"] for event in fired} == {"checkout failures", "failed runs", "pricey trace", "tool loops", "failures today"}
    assert all(event["delivered"] for event in fired if event["rule_name"] != "failures today")
    assert len(received) == 4  # the rule without a webhook is recorded but not delivered
    by_rule = {event["rule_name"]: event for event in fired}
    assert by_rule["checkout failures"]["value"] == pytest.approx(0.5)
    assert "Failure rate 50% (3 of 6 runs)" in by_rule["checkout failures"]["message"]
    assert by_rule["pricey trace"]["details"]["traces"][0]["trace_id"] == expensive_trace
    assert by_rule["tool loops"]["details"]["traces"] == [{"trace_id": loop_trace, "tool_name": "search_docs", "repeats": 4}]

    posts = {post["path"]: post for post in received}
    generic = posts["/generic"]
    timestamp = generic["headers"]["x-agentmesh-timestamp"]
    expected = hmac.new(b"s3cr3t", timestamp.encode() + b"." + generic["raw"], hashlib.sha256).hexdigest()
    assert generic["headers"]["x-agentmesh-signature"] == f"sha256={expected}"
    assert generic["json"]["type"] == "agentmesh.alert" and generic["json"]["status"] == "firing"
    assert "x-agentmesh-signature" not in posts["/slack"]["headers"]
    assert posts["/slack"]["json"]["text"].startswith("*[AgentMesh] FIRING: pricey trace*")
    assert expensive_trace in posts["/slack"]["json"]["text"]
    assert posts["/discord"]["json"]["embeds"][0]["title"] == "[AgentMesh] FIRING: tool loops"

    # Still breached, inside the cooldown, and no new offending traces: nothing new.
    assert store.check_alerts() == []
    rules = {rule["name"]: rule for rule in store.list_alert_rules()}
    assert rules["checkout failures"]["state"] == "firing"
    assert rules["daily spend"]["state"] == "ok" and rules["daily spend"]["last_value"] == pytest.approx(3.015)
    assert rules["checkout failures"]["channel"]["secret"] == "***"
    assert "/***" in rules["checkout failures"]["channel"]["url"]

    # Later the failures age out of the 15m windows: aggregate rules send a resolved notification,
    # while the 1d rule is still breached and past its 30m cooldown, so it reminds again.
    later = datetime.now(UTC) + timedelta(minutes=45)
    changes = store.check_alerts(now=later)
    assert [(event["rule_name"], event["status"]) for event in changes] == [("failed runs", "resolved"), ("failures today", "firing")]
    assert received[-1]["json"]["status"] == "resolved"
    # failure_rate has too few runs in the new window to judge, so it keeps its state.
    assert store.get_alert_rule("checkout failures")["state"] == "firing"
    assert [event["status"] for event in store.list_alert_events(rule="failed runs")] == ["resolved", "firing"]
    assert [event["status"] for event in store.list_alert_events(rule="failures today")] == ["firing", "firing"]
    store.close()


def test_failed_delivery_is_recorded(db_url, webhook):
    url, received = webhook
    _record_activity(db_url)
    store = create_store(db_url)
    store.create_alert_rule({"name": "fails", "kind": "failure_count", "threshold": 1, "channel": {"url": f"{url}/broken"}})
    fired = store.check_alerts()
    assert fired[0]["delivered"] is False and fired[0]["delivery_error"] == "HTTP 500"
    assert len(received) == 2  # one retry on 5xx
    assert store.list_alert_events()[0]["delivery_error"] == "HTTP 500"
    store.close()


def test_alert_api_and_validation(db_url, webhook):
    url, received = webhook
    client = TestClient(create_app(db_url))
    assert "loop_detected" in client.get("/api/alerts/kinds").json()["kinds"]
    bad = client.post("/api/alerts/rules", json={"name": "x", "kind": "vibes", "threshold": 1})
    assert bad.status_code == 422 and "kind must be one of" in bad.json()["detail"]["message"]
    assert client.post("/api/alerts/rules", json={"name": "x", "kind": "failure_rate", "threshold": 5}).status_code == 422
    assert client.post("/api/alerts/rules", json={"name": "x", "kind": "cost", "threshold": 1, "channel": {"url": "file:///etc/passwd"}}).status_code == 422
    assert client.post("/api/alerts/rules", json={"name": "x", "kind": "cost", "threshold": 1, "filters": {"team": "a"}}).status_code == 422
    loop = client.post("/api/alerts/rules", json={"name": "x", "kind": "loop_detected", "threshold": 1})
    assert loop.status_code == 422 and "at least 2" in loop.json()["detail"]["message"]

    created = client.post(
        "/api/alerts/rules",
        json={"name": "spend", "kind": "cost", "threshold": 0, "window": "2h", "cooldown": "1d",
              "channel": {"url": f"{url}/hooks/secret-path", "secret": "abc"}},
    )
    assert created.status_code == 201
    rule = created.json()
    assert rule["window_minutes"] == 120 and rule["cooldown_minutes"] == 1440
    assert rule["channel"]["secret"] == "***" and "secret-path" not in rule["channel"]["url"]

    # Echoing the masked channel back keeps the stored URL and secret.
    patched = client.patch(f"/api/alerts/rules/{rule['rule_id']}", json={"enabled": False, "threshold": 2.5, "channel": rule["channel"]})
    assert patched.json()["enabled"] is False and patched.json()["threshold"] == 2.5
    tested = client.post("/api/alerts/rules/spend/test").json()
    assert tested == {"delivered": True, "error": None}
    assert received[-1]["path"] == "/hooks/secret-path" and received[-1]["json"]["status"] == "test"
    assert "x-agentmesh-signature" in received[-1]["headers"]

    assert client.post("/api/alerts/check").json() == {"fired": []}  # disabled
    client.patch("/api/alerts/rules/spend", json={"enabled": True, "threshold": 0})
    fired = client.post("/api/alerts/check", params={"deliver": "false"}).json()["fired"]
    assert fired[0]["rule_name"] == "spend" and fired[0]["delivered"] is False
    assert client.get("/api/alerts/events").json()[0]["delivery_error"] == "delivery skipped"
    assert client.patch("/api/alerts/rules/missing", json={"enabled": True}).status_code == 404
    assert client.delete("/api/alerts/rules/spend").json() == {"deleted": True}
    assert client.get("/api/alerts/rules").json() == []


def test_duration_parsing_and_payload_rendering():
    assert parse_minutes("90", 5) == 90
    assert parse_minutes("2h", 5) == 120
    assert parse_minutes(None, 15) == 15
    with pytest.raises(ValueError):
        parse_minutes("soon", 5)
    event = {"status": "firing", "rule_name": "r", "message": "m", "details": {"traces": [{"trace_id": "abc"}]}, "rule": {}}
    assert render_payload(event, "slack")["text"] == "*[AgentMesh] FIRING: r*\nm\nTraces: `abc`"
    assert render_payload(event, "json")["links"] == []


def test_webhook_changes_redetect_format_and_masking_hides_credentials(db_url):
    store = create_store(db_url)
    rule = store.create_alert_rule({"name": "hooks", "kind": "cost", "threshold": 1, "channel": {"url": "https://hooks.slack.com/services/T0/B0/abcdefgh"}})
    assert rule["channel"]["format"] == "slack"
    # Echoing the masked channel back changes nothing.
    assert store.update_alert_rule("hooks", {"channel": rule["channel"]})["channel"]["format"] == "slack"
    moved = store.update_alert_rule("hooks", {"channel": {"url": "https://discord.com/api/webhooks/1/abcdefgh"}})
    assert moved["channel"]["format"] == "discord"
    explicit = store.update_alert_rule("hooks", {"channel": {"url": "https://ops.example.com/hook/abcdefgh", "format": "slack"}})
    assert explicit["channel"]["format"] == "slack"
    store.close()

    assert _mask_url("https://alice:s3cret@hooks.example.com:8443/services/abcdefgh") == "https://hooks.example.com:8443/***efgh"
    assert _mask_url("http://[::1]:9000/hook/abcdefgh") == "http://[::1]:9000/***efgh"
    assert "s3cret" not in _mask_url("https://alice:s3cret@example.com/x")
