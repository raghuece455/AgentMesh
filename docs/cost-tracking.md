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

## Pricing Rules

Prices are USD per **million** tokens and distinguish uncached input, cache reads, cache writes,
and output. Token counts follow the OpenTelemetry GenAI conventions: input tokens include cached
tokens, output tokens include reasoning tokens.

```
cost = (input - cache_read - cache_write) x input_rate
     + cache_read  x cache_read_rate
     + cache_write x cache_write_rate
     + output      x output_rate
```

A model's price is resolved in this order:

1. **Overrides** from `AGENTMESH_PRICING_JSON`
2. **Local providers** (Ollama, vLLM, LM Studio, llama.cpp, mock): always `local/free`
3. **Synced community prices** from `agentmesh pricing sync` (`.agentmesh/pricing.json` or `AGENTMESH_PRICING_FILE`)
4. **Built-in table**: current Claude models (including Fable 5.1, Opus 5, Sonnet 5, Haiku 4.5 and prompt-cache rates), Gemini 2.5, and common OpenAI models

Model names are normalized before lookup, so dated snapshots and cloud-specific IDs resolve to the
same rule: `claude-sonnet-4-5-20250929`, `us.anthropic.claude-sonnet-4-5-20250929-v1:0` and
`claude-sonnet-4-5@20250929` all match `claude-sonnet-4-5`; `gpt-4o-2024-08-06` matches `gpt-4o`.

Built-in prices are list prices. Batch discounts, data-residency multipliers, regional cloud
endpoints and negotiated discounts are not applied, which is why the status is `estimated`.

```bash
agentmesh pricing show claude-sonnet-5          # which rule applies, and why
agentmesh pricing sync                          # download the LiteLLM community price list
agentmesh pricing list
```

### Overriding prices

`AGENTMESH_PRICING_JSON` takes inline JSON or a path to a JSON file:

```bash
export AGENTMESH_PRICING_JSON='[
  {"provider": "*", "model": "my-finetune", "input_per_mtok": 3.0, "output_per_mtok": 12.0, "cache_read_per_mtok": 0.3},
  {"provider": "openai", "model": "gpt-4o*", "input_per_mtok": 2.0, "output_per_mtok": 8.0, "status": "exact", "notes": "enterprise contract"}
]'
```

`model` accepts glob patterns and `provider` accepts `*`. The shorthand
`{"my-model": {"prompt": 0.002, "completion": 0.006}}` (USD per 1K tokens) is still accepted.

If your instrumentation already knows the exact cost, send it as the `agentmesh.cost_usd` span
attribute (or `span.set_usage(..., cost_usd=...)` in the SDK) and it is recorded with status `exact`.

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
