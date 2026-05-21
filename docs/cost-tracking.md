# Cost Tracking

AgentMesh tracks every token used and every dollar spent across all agents, models, and workflow runs. You see cost by workflow, agent, model, and provider — in real time.

---

## How Costs Are Calculated

AgentMesh estimates spend from token counts returned by the provider combined with a pricing table for each model.

Cost status labels tell you how reliable the cost figure is:

| Status | Meaning |
|---|---|
| `exact` | Cost supplied directly by the provider response |
| `estimated` | Calculated from the local pricing table |
| `local/free` | Local providers — Mock, Ollama, vLLM — where no API cost is incurred |
| `unknown` | No pricing rule is configured for this model |
| `unavailable` | No token usage data was available |

---

## Budget Limits

Use `BudgetLimiter` to stop a workflow before it burns through your API budget. The limit is checked before every model call — when exceeded, `BudgetExceeded` is raised and the workflow stops immediately.

```python
from agentmesh import BudgetLimiter, Workflow

budget = BudgetLimiter(
    max_cost_usd=2.00,          # hard stop at $2 total spend
    max_total_tokens=50_000,    # or 50k tokens — whichever comes first
)

workflow = Workflow("guarded-run", budget=budget)
```

You can also limit individual token pools:

```python
budget = BudgetLimiter(
    max_prompt_tokens=30_000,      # limit context tokens
    max_completion_tokens=10_000,  # limit output tokens
    max_total_tokens=40_000,
    max_cost_usd=1.50,
)
```

`BudgetLimiter` is thread-safe — parallel workflow steps cannot race past the limit.

---

## Overriding the Pricing Table

AgentMesh ships with built-in pricing for common models. Override it for custom deployments or new model versions with `AGENTMESH_PRICING_JSON`:

```bash
export AGENTMESH_PRICING_JSON='{"my-custom-model": {"prompt": 0.002, "completion": 0.006}}'
```

Units are USD per 1,000 tokens.

Or point to a JSON file:

```bash
export AGENTMESH_PRICING_JSON=/path/to/pricing.json
```

Format of the JSON file:

```json
{
  "gpt-4o": {"prompt": 0.005, "completion": 0.015},
  "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
  "claude-3-5-sonnet-20241022": {"prompt": 0.003, "completion": 0.015}
}
```

---

## Querying Costs via the CLI

```bash
# Total spend summary
agentmesh costs summary

# Break down by model
agentmesh costs summary --dimension model

# Break down by agent
agentmesh costs summary --dimension agent

# Break down by workflow
agentmesh costs summary --dimension workflow
```

---

## Querying Costs via the API

```bash
# Costs for a specific trace
curl http://127.0.0.1:8787/api/traces/<trace_id>/costs

# Aggregate cost analytics
curl http://127.0.0.1:8787/api/costs
```

---

## Dashboard: Cost Center

The **Costs** page shows:

- **Spend today / this week / this month**
- **Budget used vs remaining** — with a visual progress bar per budget
- **Cost by workflow** — which pipelines are most expensive
- **Cost by agent** — which agents spend the most
- **Cost by model / provider** — compare model costs at a glance
- **Failed-run waste** — money spent on runs that ultimately failed
- **Cache savings** — cost avoided by prompt caching (where supported)
- **Token split** — prompt vs completion token ratio

---

## Cost in Trace Events

Every `model.response` event records:

```python
{
    "provider": "openai",
    "model": "gpt-4o-mini",
    "prompt_tokens": 412,
    "completion_tokens": 87,
    "cached_tokens": 0,
    "cost_usd": 0.000114,
    "cost_status": "estimated",
    "latency_ms": 842,
}
```

---

## Running the Example

```bash
python examples/cost_budget_workflow.py
```
