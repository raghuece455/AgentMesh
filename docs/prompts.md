# Prompts

AgentMesh records every prompt sent to a model — the full system prompt, the rendered user prompt, and the model response. These records form a **Prompt Registry**: a versioned history of every prompt your agents have used.

---

## What Gets Recorded

Every `model.call` event stores:

| Field | Description |
|---|---|
| `prompt_hash` | SHA-256 of the rendered prompt — identifies when the prompt changed |
| `agent_name` | Which agent sent this prompt |
| `task_id` | Which step triggered the call |
| `system_prompt` | The agent's instructions (role definition) |
| `user_prompt` | The rendered task message including context from previous steps |
| `model` | Model name (e.g. `gpt-4o-mini`) |
| `temperature` | Sampling temperature |
| `trace_id` | The run this call belongs to |
| `response_text` | What the model returned |
| `prompt_tokens` | Input token count |
| `completion_tokens` | Output token count |
| `cost_usd` | Cost for this call |

---

## Viewing Prompts

### In the Dashboard

Navigate to **Trace Explorer** → open any trace → click any `model.call` span. The Span Detail panel shows:

- Full system prompt
- Full rendered user prompt
- Model response
- Token counts and cost

The **Prompt Registry** page (accessible via the Agents page) shows:

- Latest prompt version per agent
- Usage count — how many traces used this prompt
- Average cost per prompt call
- Version history with diff

### Via the API

```bash
# All prompts for a trace
curl http://127.0.0.1:8787/api/traces/<trace_id>/prompts

# All prompts (paginated, filterable by agent)
curl http://127.0.0.1:8787/api/prompts?agent_name=writer&limit=50
```

### Via the CLI

```bash
agentmesh traces show <trace_id>    # includes prompts in the detail output
```

---

## Prompt Versioning

The `prompt_hash` field tracks when a prompt changes. Every time an agent's system prompt or task description changes, a new version is recorded. You can see exactly which version was active for any given run.

This makes it easy to answer: *"Did the prompt change between the run that worked and the run that failed?"*

---

## Inspecting Prompts in a Workflow

```python
import asyncio
from agentmesh import Agent, MockModelProvider, Workflow, SQLiteStore

store    = SQLiteStore()
provider = MockModelProvider(["Research complete."])

workflow = Workflow("research", store=store)
workflow.add_agent(Agent(
    "researcher",
    "Research Analyst",
    "Find key facts and cite sources clearly.",   # this is the system prompt
    provider,
))
workflow.add_step("researcher", "Research AI trends in 2025")   # this becomes the user prompt

result = await asyncio.run(workflow.run({"topic": "AI 2025"}))

# Retrieve prompt records for this trace
prompts = store.list_prompts(result.trace_id)
for p in prompts:
    print(p["agent_name"])
    print(p["system_prompt"])
    print(p["user_prompt"])
    print(p["prompt_hash"])
```

---

## Planned Features

| Feature | Status |
|---|---|
| Prompt versioning and registry (current) | ✅ Implemented |
| Rollback to a previous prompt version | Planned — v0.4 |
| Saved-input prompt testing (replay a prompt with new inputs) | Planned — v0.4 |
| Side-by-side prompt diff with quality and cost deltas | Planned — v0.5 |
| Prompt template library | Planned — v0.5 |
