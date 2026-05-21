# Evaluations

AgentMesh includes an evaluator interface for scoring agent outputs. Evaluation records are persisted alongside trace data so you can track output quality over time and catch regressions.

---

## What Evaluations Track

An evaluation record captures:

| Field | Description |
|---|---|
| `eval_id` | Unique evaluation identifier |
| `trace_id` | The workflow run being evaluated |
| `step_id` | Which step's output was evaluated |
| `evaluator` | The evaluator that produced the score |
| `score` | Numeric quality score (e.g. 0.0–1.0) |
| `label` | Categorical label (e.g. `pass`, `fail`, `flagged`) |
| `reason` | Human-readable explanation of the score |
| `metadata` | Any additional context (e.g. golden reference, threshold) |

---

## Built-in Evaluators

### Keyword Evaluator

Checks whether the agent's output contains expected keywords.

```python
from agentmesh.evaluators import KeywordEvaluator

evaluator = KeywordEvaluator(
    required_keywords=["summary", "conclusion"],
    forbidden_keywords=["I don't know", "unclear"],
)

record = evaluator.evaluate(
    output="Here is the summary and conclusion of the report.",
    trace_id="trc_abc123",
    step_id="write",
)
print(record["score"])   # 1.0 — all required keywords present, none forbidden
```

### Schema Evaluator

Checks whether the agent's output matches an expected JSON schema.

```python
from agentmesh.evaluators import SchemaEvaluator

evaluator = SchemaEvaluator(
    schema={"type": "object", "required": ["title", "points"]},
)

record = evaluator.evaluate(
    output='{"title": "AI Report", "points": ["fast", "cheap"]}',
    trace_id="trc_abc123",
    step_id="structure",
)
print(record["label"])   # "pass"
```

---

## Persisting Evaluation Records

```python
from agentmesh import SQLiteStore
from agentmesh.evaluators import KeywordEvaluator

store     = SQLiteStore()
evaluator = KeywordEvaluator(required_keywords=["revenue", "growth"])

# Evaluate and persist in one step
record = evaluator.evaluate_and_store(
    store=store,
    output=agent_result.output,
    trace_id=result.trace_id,
    step_id="report",
)
```

---

## Querying Evaluations via the API

```bash
# All evaluation records
curl http://127.0.0.1:8787/api/evaluations

# Records for a specific trace
curl http://127.0.0.1:8787/api/evaluations?trace_id=trc_abc123

# Summary statistics (pass rate, average score)
curl http://127.0.0.1:8787/api/evaluations/summary
```

---

## Dashboard: Quality Trends

The dashboard **Evaluations** section shows:

- Pass rate over time
- Average score by evaluator
- Step-level quality breakdown
- Flagged outputs that need review

---

## Planned Evaluators

| Evaluator | Status |
|---|---|
| Keyword / Schema (current) | ✅ Implemented |
| RAG faithfulness (answer grounded in retrieved chunks?) | Planned — v0.4 |
| Hallucination risk (output contradicts retrieved facts?) | Planned — v0.4 |
| Golden trace regression (output matches a reference trace?) | Planned — v0.4 |
| LLM-as-judge evaluator | Planned — v0.5 |
