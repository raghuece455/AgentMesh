import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import agentmesh
from agentmesh import Contains, ExactMatch, JSONValid, LLMJudge, RegexMatch, Similarity, evaluator
from agentmesh.dashboard import create_app
from agentmesh.evaluators import builtin_evaluator, run_evaluator
from agentmesh.stores import create_store

CAPITALS = [
    {"item_id": "fr", "input": {"country": "France"}, "expected": "Paris"},
    {"item_id": "jp", "input": {"country": "Japan"}, "expected": "Tokyo"},
    {"item_id": "pe", "input": {"country": "Peru"}, "expected": "Lima"},
]


@pytest.fixture
def local_sdk(db_url):
    agentmesh.init(db_path=db_url, service_name="experiments-test", flush_interval=0.05)
    store = create_store(db_url)
    yield store
    agentmesh.shutdown()
    store.close()


def _judge(prompt: str) -> str:
    actual = prompt.split("Actual output:", 1)[1]
    if "Paris" in actual or "Tokyo" in actual:
        return '{"score": 1, "reason": "matches the reference"}'
    return '```json\n{"score": 0.2, "reason": "wrong city"}\n```'


def test_run_experiment_scores_every_item_and_links_traces(local_sdk):
    store = local_sdk
    store.create_dataset("capitals", description="country -> capital")
    store.add_dataset_items("capitals", CAPITALS)

    def v1(input):
        with agentmesh.span("lookup", kind="tool", input=input):
            return {"France": "Paris", "Japan": "Kyoto", "Peru": "Lima"}[input["country"]]

    result = agentmesh.run_experiment(
        "capitals", v1, [ExactMatch(), LLMJudge("correctness", judge=_judge)], name="v1", max_concurrency=2
    )

    assert result.persisted
    assert result.summary["items"] == 3 and result.summary["errors"] == 0
    assert result.score("exact_match") == pytest.approx(2 / 3)
    assert result.summary["scores"]["correctness"]["pass_rate"] == pytest.approx(1 / 3)
    assert "exact_match" in result.format_summary()

    stored = store.get_experiment(result.experiment_id)
    assert stored["status"] == "completed" and stored["dataset_name"] == "capitals"
    by_item = {row["item_id"]: row for row in stored["results"]}
    assert by_item["jp"]["output"] == "Kyoto"
    japan_scores = {score["name"]: score for score in by_item["jp"]["scores"]}
    assert japan_scores["correctness"]["score"] == pytest.approx(0.2)
    assert japan_scores["correctness"]["comment"] == "wrong city"

    # Each item ran in its own trace, with the task's spans nested inside and scores attached.
    trace = store.get_observable_trace(by_item["jp"]["trace_id"])
    assert trace is not None and "experiment" in trace["tags"]
    assert {span["name"] for span in store.list_spans(trace["trace_id"])} >= {"experiment:v1", "lookup"}
    scores = {score["name"]: score for score in store.list_scores(trace_id=trace["trace_id"])}
    assert scores["exact_match"]["value"] == 0 and scores["exact_match"]["source"] == "experiment"
    assert scores["correctness"]["passed"] is False

    datasets = store.list_datasets()
    assert datasets[0]["item_count"] == 3 and datasets[0]["experiment_count"] == 1


def test_compare_experiments_finds_regressions_and_improvements(local_sdk):
    store = local_sdk
    store.create_dataset("capitals")
    store.add_dataset_items("capitals", CAPITALS)
    v1 = agentmesh.run_experiment(
        "capitals", lambda input: {"France": "Paris", "Japan": "Kyoto", "Peru": "Lima"}[input["country"]], [ExactMatch()], name="v1"
    )

    async def v2(input):
        await asyncio.sleep(0)
        if input["country"] == "Peru":
            raise TimeoutError("model timed out")
        return {"France": "Paris", "Japan": "Tokyo"}[input["country"]]

    v2_result = agentmesh.run_experiment("capitals", v2, [ExactMatch()], name="v2")
    assert v2_result.summary["errors"] == 1

    comparison = store.compare_experiments(v1.experiment_id, v2_result.experiment_id)
    assert comparison["counts"] == {"improved": 1, "regressed": 1, "unchanged": 1, "added": 0, "removed": 0}
    changes = {row["item_id"]: row["change"] for row in comparison["items"]}
    assert changes == {"jp": "improved", "pe": "regressed", "fr": "unchanged"}
    assert comparison["items"][0]["change"] == "regressed"
    assert comparison["items"][0]["candidate"]["error"] == "TimeoutError: model timed out"
    failed_trace = store.get_observable_trace(comparison["items"][0]["candidate"]["trace_id"])
    assert failed_trace["status"] == "failed"


def test_inline_items_and_add_trace_to_dataset(local_sdk):
    store = local_sdk
    with agentmesh.trace("support", input={"question": "reset password?"}) as root:
        root.set_output("Use the reset link on the sign-in page.")
    agentmesh.flush()

    store.create_dataset("support-regressions")
    item = store.add_trace_to_dataset("support-regressions", root.trace_id)
    assert item["input"] == {"question": "reset password?"}
    assert item["expected"] == "Use the reset link on the sign-in page."
    no_reference = store.add_trace_to_dataset("support-regressions", root.trace_id, expected=None)
    assert no_reference["expected"] is None
    dataset = store.get_dataset("support-regressions")
    assert dataset["items"][0]["source_trace_id"] == root.trace_id
    assert dataset["items"][0]["metadata"]["trace_name"] == "support"
    with pytest.raises(KeyError):
        store.add_trace_to_dataset("support-regressions", "0" * 32)

    # Plain dicts work without a stored dataset, and get stable ids so runs compare.
    first = agentmesh.run_experiment([{"input": "hello"}], lambda text, item: text.upper(), [Contains("HELLO", case_sensitive=True)], name="inline")
    second = agentmesh.run_experiment([{"input": "hello"}], str.lower, [Contains("HELLO", case_sensitive=True)], name="inline-2")
    assert first.results[0].item_id == second.results[0].item_id
    assert first.score("contains") == 1.0 and second.score("contains") == 0.0
    assert store.compare_experiments(first.experiment_id, second.experiment_id)["counts"]["regressed"] == 1


def test_builtin_evaluators_and_function_evaluators():
    def run(ev, **kwargs):
        return asyncio.run(run_evaluator(ev, input=kwargs.get("input"), output=kwargs.get("output"), expected=kwargs.get("expected")))

    assert run(ExactMatch(), output="  Paris ", expected="paris").passed is True
    assert run(ExactMatch(), output={"a": 1}, expected={"a": 1}).score == 1.0
    assert run(ExactMatch(), output="x", expected=None).label == "no_expected"
    partial = run(Contains(), output="Paris and Lyon", expected=["paris", "Nice"])
    assert partial.score == 0.5 and partial.passed is False and "Nice" in partial.comment
    assert run(RegexMatch(r"\bORD-\d+\b"), output="order ORD-42 shipped").passed is True
    assert run(JSONValid(required_keys=["id"]), output='```json\n{"id": 1}\n```').passed is True
    assert run(JSONValid(required_keys=["id"]), output='{"name": 1}').comment == "missing keys: id"
    assert run(JSONValid(), output="not json").passed is False
    assert run(Similarity(threshold=0.8), output="The capital is Paris", expected="the capital is paris.").passed is True

    @evaluator(name="short")
    def short(output):
        return len(output) < 10

    @evaluator
    async def graded(output, expected, **_):
        return {"score": 0.7, "label": "ok", "comment": f"{output} vs {expected}"}

    def broken(**_):
        raise RuntimeError("boom")

    assert run(short, output="tiny").passed is True
    assert run(graded, output="a", expected="b").to_json()["comment"] == "a vs b"
    failed = run(broken, output="x")
    assert failed.label == "error" and "boom" in failed.comment

    judge = LLMJudge("helpfulness", judge=lambda prompt: "Score: 4", scale=(1, 5), threshold=0.7)
    graded_by_judge = run(judge, input="q", output="a")
    assert graded_by_judge.name == "helpfulness"
    assert graded_by_judge.score == pytest.approx(0.75) and graded_by_judge.passed is True
    assert run(LLMJudge("Is it polite?", judge=lambda prompt: "no idea"), output="a").label == "unparseable"
    prompt = LLMJudge("correctness", judge=_judge).build_prompt(input={"q": "{output}"}, output="Paris", expected=None)
    assert "(none)" in prompt and '"score"' in prompt
    assert '{"q": "{output}"}' in prompt and prompt.rstrip().endswith('"reason": "<one short sentence>"}')
    assert prompt.count("Paris") == 1  # placeholders inside the inserted input are not substituted
    with pytest.raises(ValueError):
        LLMJudge("correctness")
    assert isinstance(builtin_evaluator("regex:^ok"), RegexMatch)
    assert builtin_evaluator("unknown") is None


def test_llm_judge_with_model_provider():
    provider = agentmesh.MockModelProvider(['{"score": 0.9, "reason": "grounded"}'])
    result = asyncio.run(
        run_evaluator(LLMJudge("faithfulness", provider=provider, model="mock-judge"), input="ctx", output="a", expected=None)
    )
    assert result.score == pytest.approx(0.9) and result.comment == "grounded"
    assert result.metadata["judge_model"] == "mock-judge"


def test_evaluate_traces_scores_recorded_traces(db_url):
    store = create_store(db_url)
    agentmesh.init(db_path=db_url, flush_interval=0.05)
    try:
        for answer in ["Refund issued.", "I cannot help with that."]:
            with agentmesh.trace("support", input="refund please") as root:
                root.set_output(answer)
        agentmesh.flush()
        scored = agentmesh.evaluate_traces([Contains("refund", name="mentions_refund")], store=store)
        assert len(scored) == 2
        values = sorted(item["scores"][0]["score"] for item in scored)
        assert values == [0.0, 1.0]
        assert agentmesh.evaluate_traces([Contains("refund", name="mentions_refund")], store=store) == []
    finally:
        agentmesh.shutdown()
        store.close()


def test_dataset_and_experiment_api(db_url):
    client = TestClient(create_app(db_url))
    created = client.post("/api/datasets", json={"name": "faq", "description": "FAQ answers"})
    assert created.status_code == 201
    assert client.post("/api/datasets", json={"name": "faq"}).status_code == 409
    items = client.post("/api/datasets/faq/items", json={"items": [{"input": "hours?", "expected": "9-5"}]})
    assert items.status_code == 201
    item_id = items.json()["items"][0]["item_id"]
    assert client.post("/api/datasets/faq/items", json={"items": [{"expected": "x"}]}).status_code == 422
    assert client.post("/api/datasets/missing/items", json={"items": [{"input": 1}]}).status_code == 404
    assert client.post("/api/datasets/faq/items", json={"trace_id": "f" * 32}).status_code == 404

    detail = client.get("/api/datasets/faq").json()
    assert detail["item_count"] == 1 and detail["items"][0]["expected"] == "9-5"
    client.post("/api/datasets/faq/items", json={"items": [{"input": "phone?", "expected": "555"}]})
    second_page = client.get("/api/datasets/faq", params={"limit": 1, "offset": 1}).json()
    assert second_page["item_count"] == 2 and [item["expected"] for item in second_page["items"]] == ["555"]
    slash = client.post("/api/datasets", json={"name": "team/support"})
    assert slash.status_code == 422 and "cannot contain '/'" in slash.json()["detail"]["message"]

    experiment = {
        "experiment_id": "exp_remote",
        "name": "remote-run",
        "dataset": "faq",
        "status": "completed",
        "evaluators": ["exact_match"],
        "results": [
            {"item_id": item_id, "input": "hours?", "expected": "9-5", "output": "9-5", "duration_ms": 12.5,
             "scores": [{"name": "exact_match", "score": 1.0, "passed": True}]}
        ],
    }
    saved = client.post("/api/experiments", json=experiment).json()
    assert saved["summary"]["scores"]["exact_match"]["mean"] == 1.0
    listed = client.get("/api/experiments", params={"dataset": "faq"}).json()
    assert [row["experiment_id"] for row in listed] == ["exp_remote"]
    assert client.get("/api/experiments/exp_remote").json()["results"][0]["output"] == "9-5"
    compare = client.get("/api/experiments/compare", params={"base": "exp_remote", "candidate": "exp_remote"})
    assert compare.json()["counts"]["unchanged"] == 1
    assert client.get("/api/experiments/compare", params={"base": "exp_remote", "candidate": "nope"}).status_code == 404

    assert client.delete(f"/api/datasets/faq/items/{item_id}").json() == {"deleted": True}
    assert client.delete("/api/datasets/faq").json() == {"deleted": True}
    assert client.get("/api/experiments/exp_remote").status_code == 404
    assert client.get("/api/datasets/faq").status_code == 404


class _AgentMeshStub(BaseHTTPRequestHandler):
    """Minimal stand-in for a remote AgentMesh server."""

    posted: list[tuple[str, dict]] = []

    items = [{"item_id": "a", "input": 2, "expected": 4}, {"item_id": "b", "input": 3, "expected": 6}]
    pages: list[str] = []

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse

        url = urlparse(self.path)
        if url.path == "/api/datasets/remote%20set":
            type(self).pages.append(self.path)
            offset = int(parse_qs(url.query).get("offset", ["0"])[0])
            page = type(self).items[offset : offset + 1]
            self._send(200, {"dataset_id": "ds_1", "name": "remote set", "item_count": len(type(self).items), "items": page})
        else:
            self._send(404, {"error": "dataset_not_found"})

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).posted.append((self.path, payload))
        self._send(200, {"summary": {"items": len(payload.get("results") or []), "errors": 0, "scores": {}}} if self.path == "/api/experiments" else {})

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


def test_run_experiment_against_a_remote_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AgentMeshStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    agentmesh.init(endpoint=f"http://127.0.0.1:{server.server_port}", api_key="k", flush_interval=0.05)
    try:
        result = agentmesh.run_experiment("remote set", lambda value: value * 2, [ExactMatch()], name="remote")
        assert [item.output for item in result.results] == [4, 6] and result.results[0].scores[0].passed is True
        # The server returned one item per page; the SDK kept reading until it had item_count items.
        assert [path.rsplit("offset=", 1)[1] for path in _AgentMeshStub.pages] == ["0", "1"]
        assert result.url.endswith(f"experiment={result.experiment_id}")
        with pytest.raises(KeyError):
            agentmesh.run_experiment("missing", lambda value: value, [])
    finally:
        agentmesh.shutdown()
        server.shutdown()
    paths = [path for path, _ in _AgentMeshStub.posted]
    assert "/v1/traces" in paths and "/api/scores" in paths
    experiment_posts = [payload for path, payload in _AgentMeshStub.posted if path == "/api/experiments"]
    assert experiment_posts[0]["status"] == "running"
    assert experiment_posts[-1]["status"] == "completed" and experiment_posts[-1]["results"][0]["output"] == 4
    score_post = next(payload for path, payload in _AgentMeshStub.posted if path == "/api/scores")
    assert score_post["passed"] is True and score_post["metadata"]["item_id"] == "a"


def _cli(*args, db):
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONPATH": os.path.abspath("src"), "AGENTMESH_ENDPOINT": ""}
    return subprocess.run(
        [sys.executable, "-m", "agentmesh.cli", "--db", str(db), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


TASK_MODULE = """
ANSWERS = {"France": "Paris", "Japan": "Kyoto", "Peru": "Lima", "Chile": "Santiago"}

def v1(input):
    return ANSWERS[input["country"]]

def v2(input):
    return {**ANSWERS, "Japan": "Tokyo", "Peru": "Cusco"}[input["country"]]

def mentions_city(output, expected):
    return expected.lower() in output.lower()
"""


def test_cli_datasets_experiments_and_alerts(tmp_path):
    db = tmp_path / "cli.db"
    items = tmp_path / "capitals.jsonl"
    items.write_text("".join(json.dumps(item) + "\n" for item in CAPITALS), encoding="utf-8")
    task_file = tmp_path / "capital_task.py"
    task_file.write_text(TASK_MODULE, encoding="utf-8")

    assert json.loads(_cli("datasets", "import", "capitals", str(items), db=db).stdout) == {"dataset": "capitals", "imported": 3}
    assert _cli("datasets", "add", "capitals", "--input", '{"country": "Chile"}', "--expected", "Santiago", db=db).returncode == 0
    assert json.loads(_cli("datasets", "list", db=db).stdout)[0]["item_count"] == 4
    exported = _cli("datasets", "export", "capitals", db=db).stdout.splitlines()
    assert [json.loads(line)["expected"] for line in exported] == ["Paris", "Tokyo", "Lima", "Santiago"]
    export_file = tmp_path / "capitals-export.jsonl"
    export_file.write_text("\n".join(exported) + "\n", encoding="utf-8")
    assert json.loads(_cli("datasets", "import", "capitals-copy", str(export_file), db=db).stdout)["imported"] == 4
    counts = {row["name"]: row["item_count"] for row in json.loads(_cli("datasets", "list", db=db).stdout)}
    assert counts == {"capitals": 4, "capitals-copy": 4}
    missing = _cli("datasets", "add", "nope", "--input", "x", db=db)
    assert missing.returncode == 1 and "dataset not found: nope" in missing.stderr

    evaluators = ["--evaluator", "exact_match", "--evaluator", f"{task_file}:mentions_city"]
    first = _cli("experiments", "run", "--dataset", "capitals", "--task", f"{task_file}:v1", *evaluators,
                 "--name", "v1", "--fail-under", "exact_match=0.9", "--json", db=db)
    assert first.returncode == 1, first.stderr
    v1 = json.loads(first.stdout)
    assert v1["summary"]["scores"]["exact_match"]["mean"] == 0.75
    assert v1["summary"]["scores"]["mentions_city"]["pass_rate"] == 0.75
    assert v1["failed_thresholds"] == [{"evaluator": "exact_match", "minimum": 0.9, "actual": 0.75}]

    second = _cli("experiments", "run", "--dataset", "capitals", "--task", f"{task_file}:v2", *evaluators,
                  "--name", "v2", "--baseline", v1["experiment_id"], "--fail-on-regression", db=db)
    assert second.returncode == 1, second.stderr
    assert "exact_match: 0.750" in second.stdout
    assert "1 improved, 1 regressed, 2 unchanged" in second.stdout

    third = _cli("experiments", "run", "--dataset", "capitals", "--task", f"{task_file}:v2", "--evaluator", "contains",
                 "--fail-under", "contains=0.7", db=db)
    assert third.returncode == 0, third.stderr
    listed = json.loads(_cli("experiments", "list", "--dataset", "capitals", db=db).stdout)
    assert len(listed) == 3 and {row["name"] for row in listed} >= {"v1", "v2"}
    comparison = json.loads(_cli("experiments", "compare", listed[2]["experiment_id"], listed[1]["experiment_id"], db=db).stdout)
    assert comparison["counts"]["regressed"] == 1

    created = json.loads(_cli("alerts", "add", "--name", "any-failure", "--kind", "failure_count", "--threshold", "0",
                              "--window", "1h", "--webhook", "https://hooks.slack.com/services/T0/B0/secret123", db=db).stdout)
    assert created["channel"]["format"] == "slack" and "secret123" not in created["channel"]["url"]
    fired = json.loads(_cli("alerts", "check", "--no-deliver", db=db).stdout)["fired"]
    assert fired[0]["rule_name"] == "any-failure" and fired[0]["delivery_error"] == "delivery skipped"
    assert len(json.loads(_cli("alerts", "history", "--rule", "any-failure", db=db).stdout)) == 1
    assert json.loads(_cli("alerts", "update", "any-failure", "--disable", db=db).stdout)["enabled"] is False
    invalid = _cli("alerts", "add", "--name", "bad", "--kind", "failure_rate", "--threshold", "3", db=db)
    assert invalid.returncode == 1 and "fraction between 0 and 1" in invalid.stderr
    assert json.loads(_cli("alerts", "remove", "any-failure", db=db).stdout) == {"deleted": "any-failure"}


def test_dataset_items_are_copied_between_datasets_and_paged(db_url):
    store = create_store(db_url)
    store.create_dataset("source")
    store.add_dataset_items("source", CAPITALS)
    exported = store.get_dataset("source", limit=None)["items"]
    store.create_dataset("copy")
    store.add_dataset_items("copy", exported)
    assert store.get_dataset("source")["item_count"] == 3 and store.get_dataset("copy")["item_count"] == 3
    copied_ids = {item["item_id"] for item in store.get_dataset("copy")["items"]}
    assert copied_ids.isdisjoint({"fr", "jp", "pe"})
    # Re-adding an item to its own dataset still updates it in place.
    store.add_dataset_items("source", [{"item_id": "fr", "input": {"country": "France"}, "expected": "Paris, France"}])
    source = store.get_dataset("source")
    assert source["item_count"] == 3 and {item["item_id"]: item["expected"] for item in source["items"]}["fr"] == "Paris, France"

    assert [item["item_id"] for item in store.get_dataset("source", limit=2)["items"]] == ["fr", "jp"]
    assert [item["item_id"] for item in store.get_dataset("source", limit=2, offset=2)["items"]] == ["pe"]
    assert len(store.get_dataset("source", limit=None, offset=1)["items"]) == 2
    with pytest.raises(ValueError):
        store.create_dataset("team/support")
    store.close()


def test_experiments_use_every_item_of_large_datasets(tmp_path):
    store = create_store(str(tmp_path / "large.db"))
    store.create_dataset("large")
    store.add_dataset_items("large", [{"input": index} for index in range(5003)])
    agentmesh.init(enabled=False)
    try:
        result = agentmesh.run_experiment("large", lambda value: value, [], name="all-items", max_concurrency=32, store=store)
    finally:
        agentmesh.shutdown()
    assert result.summary["items"] == 5003
    store.close()
