# Replay

Replay lets you re-examine any past workflow run without calling a live API. You can reproduce a bug exactly as it happened, test whether a prompt change would have fixed it, or inspect intermediate memory state at any step.

---

## How Replay Works

When a workflow runs, AgentMesh saves:
- The full prompt sent to the model at each step
- The model's response
- Every tool call (inputs and outputs)
- Memory state after each step (checkpoints)

Replay uses this recorded data to reconstruct the run without making new API calls.

---

## Three Replay Modes

| Mode | Uses live API? | Use case |
|---|---|---|
| `deterministic` | No | Exact reproduction — same prompts, same outputs |
| `simulated` | No | Shape testing — swap in mock outputs for "what if" analysis |
| `live` | Yes | Verify the current model's behaviour on the same prompts |

---

## Deterministic Replay

Replays the exact recorded prompts and model outputs. Ideal for debugging — you get the same run every time.

```bash
agentmesh replay <trace_id> --mode deterministic
```

```python
from agentmesh import SQLiteStore
from agentmesh.replay import ReplayEngine

store  = SQLiteStore()
engine = ReplayEngine(store)

result = await engine.replay(trace_id, mode="deterministic")
print(result["status"])     # "succeeded" or "failed"
print(result["events"])     # all replayed events
```

---

## Simulated Replay

Replays with mock outputs — useful for testing how your pipeline handles different model responses without calling an API.

```bash
agentmesh replay <trace_id> --mode simulated
```

---

## Live Replay

Sends the same recorded prompts to the live model. Use this to verify whether a prompt fix or a new model version changes the outcome. **This makes real API calls and may incur cost.**

```bash
agentmesh replay <trace_id> --mode live --allow-side-effects
```

The `--allow-side-effects` flag is required to prevent accidental live tool calls. Without it, tools are mocked even in live mode.

---

## Replay from a Specific Span

Start replay from the middle of a run. Steps before the selected span use recorded outputs; steps from that span onward are replayed.

```bash
agentmesh replay <trace_id> --from-span <span_id> --mode deterministic
```

---

## Time-Travel Debugging

Checkpoints capture the full workflow state (memory + completed step outputs) after each step. You can inspect any checkpoint or fork the memory to test "what if I had set this key differently?"

### List Checkpoints

```bash
agentmesh checkpoints list <trace_id>
```

### Inspect a Checkpoint

```bash
agentmesh checkpoints show <checkpoint_id>
```

### Patch Memory at a Checkpoint

```bash
agentmesh checkpoints patch-memory <checkpoint_id> \
  --set '{"topic": "different value", "max_results": 10}'
```

After patching, replay from that checkpoint to see how the rest of the workflow would have behaved with the modified memory.

---

## Replay Studio (Dashboard)

Open the **Replay Studio** page to:

1. Browse all checkpoints for any trace — shown in timeline order
2. Click any checkpoint to inspect the full memory state at that moment
3. Patch memory values inline
4. Launch a replay run from that checkpoint
5. Compare the original run and the replay run side by side

---

## Programmatic Replay

```python
import asyncio
from agentmesh import SQLiteStore
from agentmesh.replay import ReplayEngine

async def main():
    store  = SQLiteStore()
    engine = ReplayEngine(store)

    # Replay the trace
    result = await engine.replay("trc_abc123", mode="deterministic")

    for event in result["events"]:
        print(event["type"], event.get("data", {}).get("output", ""))

asyncio.run(main())
```

---

## Running the Example

```bash
python examples/time_travel_debugging.py
python examples/replay_from_checkpoint.py
```
