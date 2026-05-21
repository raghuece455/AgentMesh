# Model Providers

AgentMesh ships with seven provider implementations. Every provider implements the same interface, so you can swap between them without changing your workflow code.

---

## Mock (Tests and CI)

Returns preset responses without making any API calls. Use this for all tests and CI pipelines — no API keys, no network.

```python
from agentmesh import Agent, MockModelProvider

provider = MockModelProvider([
    "First response",
    "Second response",
    # When the list runs out, returns "Mock response to: <prompt>" automatically
])

agent = Agent("tester", "Test Agent", "Run tests.", provider)
```

---

## OpenAI-Compatible

Works with OpenAI, Azure OpenAI, and any API that implements the `/v1/chat/completions` endpoint — including local proxies.

```python
import os
from agentmesh import Agent, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    api_key=os.environ["OPENAI_API_KEY"],
    model="gpt-4o-mini",
)

agent = Agent("analyst", "Analyst", "Analyse data.", provider)
```

**Azure OpenAI:**

```python
provider = OpenAICompatibleProvider(
    base_url="https://<your-resource>.openai.azure.com/openai/deployments/<deployment>",
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    model="gpt-4o",
)
```

---

## Anthropic

```python
import os
from agentmesh import Agent
from agentmesh.providers import AnthropicProvider

provider = AnthropicProvider(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    model="claude-3-5-sonnet-20241022",
)

agent = Agent("writer", "Writer", "Write clearly.", provider)
```

---

## Google Gemini

```python
import os
from agentmesh import Agent
from agentmesh.providers import GeminiProvider

provider = GeminiProvider(
    api_key=os.environ["GEMINI_API_KEY"],
    model="gemini-1.5-flash",
)

agent = Agent("researcher", "Researcher", "Find key facts.", provider)
```

---

## Ollama (Local Models)

Run models locally with [Ollama](https://ollama.com). No API key required.

```bash
# Install and pull a model
ollama pull llama3.2
```

```python
import os
from agentmesh import Agent
from agentmesh.providers import OllamaProvider

provider = OllamaProvider(
    host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    model="llama3.2",
)

agent = Agent("local-agent", "Local Agent", "Answer questions.", provider)
```

---

## vLLM (OpenAI-Compatible)

vLLM exposes an OpenAI-compatible API, so use `OpenAICompatibleProvider` pointed at your vLLM server.

```python
import os
from agentmesh import Agent, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
    api_key="not-required",       # vLLM doesn't require a key by default
    model="meta-llama/Llama-3.1-8B-Instruct",
)

agent = Agent("inference-agent", "Inference Agent", "Run fast inference.", provider)
```

---

## Model Router

Route requests to different providers based on the task type — use a cheap model for simple tasks and a powerful model for complex ones.

```python
from agentmesh.providers import ModelRouter, RoutingRule

router = ModelRouter(
    rules=[
        RoutingRule(tag="coding",  provider=openai_provider),
        RoutingRule(tag="summary", provider=ollama_provider),
    ],
    default=openai_provider,
)

agent = Agent("smart-agent", "Smart Agent", "Route tasks intelligently.", router)
```

---

## Custom Provider

Implement the `ModelProvider` protocol to add any provider:

```python
from agentmesh.providers import ModelProvider

class MyProvider(ModelProvider):
    async def complete(self, messages: list[dict], **kwargs) -> dict:
        # Call your API here
        return {
            "text": "Response from my API",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "cost_usd": 0.001,
            "cost_status": "estimated",
        }
```

---

## Environment Variables

| Variable | Provider | Description |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI | API key |
| `OPENAI_BASE_URL` | OpenAI-compatible | Override base URL (default: `https://api.openai.com/v1`) |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI | API key |
| `ANTHROPIC_API_KEY` | Anthropic | API key |
| `GEMINI_API_KEY` | Google Gemini | API key |
| `OLLAMA_HOST` | Ollama | Server URL (default: `http://localhost:11434`) |
| `VLLM_BASE_URL` | vLLM | Server URL (default: `http://localhost:8000/v1`) |

AgentMesh redacts all API keys before persisting trace data or exporting.

---

## What Gets Recorded per Provider Call

Every model call records a `model.call` and `model.response` (or `model.failed`) event:

| Field | Description |
|---|---|
| `provider` | Provider name (e.g. `openai`, `anthropic`) |
| `model` | Model name (e.g. `gpt-4o-mini`) |
| `prompt_text` | Full prompt sent to the model |
| `temperature` | Sampling temperature |
| `prompt_tokens` | Tokens used for input |
| `completion_tokens` | Tokens used for output |
| `cached_tokens` | Prompt-cache hits (where supported) |
| `cost_usd` | Estimated or exact cost |
| `latency_ms` | Round-trip time |
| `request_id` | Provider request ID (where available) |

---

## Running the Examples

```bash
python examples/openai_compatible_provider.py
python examples/ollama_local_model.py
python examples/multi_model_routing.py
```
