# Evaluations and Scores

An **evaluation** (or **score**) is a quality judgment attached to a trace or a span: user feedback, an automated check, an LLM-as-judge verdict, or a reviewer's label. AgentMesh stores them next to the trace, shows them on the trace, in its session, and on the **Evaluations** page, and aggregates them per experiment.

- To **run evaluators** over a dataset or over recorded traces, see [datasets-and-experiments.md](datasets-and-experiments.md).
- This page covers the score record, every way to create one, and how to query them.

---

## The score record

| Field | Description |
|---|---|
| `score_id` | Unique id |
| `trace_id` / `span_id` | What was judged |
| `name` | Evaluator or metric name, e.g. `correctness`, `thumbs_up`, `json_valid` |
| `value` | Number (usually 0..1), or the numeric form of a boolean (1/0) |
| `label` | Categorical result, e.g. `pass`, `refund_missing` (string values are stored here) |
| `passed` | Explicit pass/fail, when the evaluator gives one |
| `comment` | Explanation, e.g. the judge's reason |
| `source` | Where it came from: `sdk`, `api`, `dashboard`, `feedback`, `otel`, `mcp`, `experiment`, `evaluator` |
| `metadata` | Extra context, e.g. `experiment_id`, `item_id`, the judge's raw score |

---

## Create scores from anywhere

| Source | How |
|---|---|
| Python SDK | `agentmesh.score("helpfulness", 0.8, comment="...")` inside a trace, or pass `trace_id=` later |
| TypeScript SDK | `score("helpfulness", 0.8, { comment: "..." })` or `span.score(...)` |
| Experiments | Every evaluator result in `run_experiment` / `runExperiment` is attached to the item's trace (`source="experiment"`) |
| Online evaluation | `agentmesh.evaluate_traces([...evaluators], store=store)` scores recorded traces (`source="evaluator"`) |
| REST API | `POST /api/scores {"trace_id": "...", "name": "thumbs", "value": true, "passed": true, "comment": "..."}` |
| Dashboard | Thumbs up/down on the Insights & Scores panel |
| OpenTelemetry | `gen_ai.evaluation.result` span events (`gen_ai.evaluation.name`, `gen_ai.evaluation.score.value`, `...score.label`, `...explanation`) |
| MCP | `add_score` tool, e.g. after your coding agent reviews a trace |

Values can be numbers, booleans, or labels. Booleans become `value` 1/0 with `passed` set.

```python
import agentmesh

agentmesh.init()

with agentmesh.trace("support-turn", session_id="chat-42") as root:
    answer = support_agent("Where is my order?")
    agentmesh.score("resolved", True)

# Later, e.g. from a feedback webhook:
agentmesh.score("user_rating", 4, trace_id=root.trace_id, label="helpful", source="feedback")
```

---

## Query scores

```bash
curl http://127.0.0.1:8787/api/evaluations                       # all evaluation and score records
curl "http://127.0.0.1:8787/api/scores?trace_id=<trace_id>"       # scores for one trace
curl "http://127.0.0.1:8787/api/scores?name=correctness&limit=100"
curl http://127.0.0.1:8787/api/evaluations/summary               # average 0-1 score, pass rate, quality by workflow/agent
```

From Python: `store.list_scores(trace_id=..., name=...)` on a `SQLiteStore` or `PostgreSQLStore`.

The summary's task-success average only includes values between 0 and 1, and the pass rate only counts records with an explicit pass/fail.

---

## Dashboard

- **Evaluations** — headline metrics (task success, pass rate) and a table of every evaluation and score with evaluator, type, value, pass/fail, and time.
- **Trace detail → Insights & Scores** — the trace's scores, plus thumbs up/down.
- **Sessions** — each turn's scores next to its input and output.
- **Datasets & Evals** — mean score and pass rate per evaluator for each experiment, and item-by-item comparisons.

---

## Runtime evaluators

The AgentMesh runtime also ships `ContainsEvaluator` and `RunComparator` (`agentmesh.evaluation`) for simple checks inside workflows, and `POST /api/evaluations/run` records an evaluation with an explicit payload. For new code, prefer the evaluators in `agentmesh.evaluators` (`ExactMatch`, `Contains`, `RegexMatch`, `JSONValid`, `Similarity`, `LLMJudge`, `@evaluator`), which work with experiments and online evaluation.

---

## Status

| Capability | Status |
|---|---|
| Scores API, SDKs, dashboard feedback, OTel evaluation events | ✅ v0.4 |
| Datasets, experiments, and comparisons | ✅ v0.4 |
| Built-in evaluators and LLM-as-judge (correctness, helpfulness, conciseness, faithfulness, harmlessness presets) | ✅ v0.4 |
| Online evaluation of recorded traces | ✅ v0.4 (`evaluate_traces`) |
| Scheduled online evaluation from the server | Planned |
| RAG-specific evaluators using retrieved chunks | Planned |
