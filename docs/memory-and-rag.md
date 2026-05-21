# Memory and RAG

AgentMesh provides two types of memory and a retrieval-augmented generation (RAG) layer — all fully traced so you can see exactly what information influenced each agent's answer.

---

## Short-Term Memory (WorkflowMemory)

`WorkflowMemory` is a key-value store shared between all agents within a **single workflow run**. It is cleared at the end of the run.

Use it to pass intermediate results between steps without hard-coding data into the next step's task description.

```python
# Inside a tool or agent
context.workflow_memory.set("summary", "AI adoption is accelerating in 2025.")
context.workflow_memory.set("article_count", 42)

# Later, in another agent's tool
text = context.workflow_memory.get("summary")
```

Every read and write is recorded as a `memory.read` or `memory.write` span event in the trace.

---

## Long-Term Memory (SQLiteMemoryStore)

`SQLiteMemoryStore` persists key-value records across runs. Records are versioned — every update keeps the previous value in history so you have a full audit trail.

```python
from agentmesh import SQLiteStore, SQLiteMemoryStore

store = SQLiteStore()                      # opens .agentmesh/agentmesh.db
mem   = SQLiteMemoryStore(store)

# Write a record (agent_name, namespace, key, value)
mem.put("analyst", "profile", "last_topic", {"topic": "AI", "updated": "2025-05-01"})

# Read it back
record = mem.get("analyst", "profile", "last_topic")
print(record["value"])   # {"topic": "AI", "updated": "2025-05-01"}

# Read version history
history = mem.history("analyst", "profile", "last_topic")
for version in history:
    print(version["version"], version["value"])
```

---

## Using Memory in a Workflow

```python
import asyncio
from agentmesh import Agent, MockModelProvider, Workflow, tool, ToolRegistry, SQLiteStore, SQLiteMemoryStore

store = SQLiteStore()
mem   = SQLiteMemoryStore(store)

@tool("save_finding", "Save a research finding to long-term memory.", {"finding": "string"})
def save_finding(arguments: dict, context) -> dict:
    mem.put("researcher", "findings", "latest", {"text": arguments["finding"]})
    return {"saved": True}

provider = MockModelProvider(["Found: LLMs are growing fast.", "Report written."])

workflow = Workflow("research-loop", store=store)
workflow.add_agent(Agent(
    "researcher", "Researcher", "Find the latest AI facts.",
    provider,
    tools=ToolRegistry([save_finding]),
))
workflow.add_agent(Agent("writer", "Writer", "Summarise the findings.", provider))
workflow.add_step("researcher", "Research AI trends 2025", step_id="r")
workflow.add_step("writer",     "Write a summary report",  step_id="w", depends_on=("r",))

asyncio.run(workflow.run({"topic": "AI 2025"}))
```

---

## RAG (Retrieval-Augmented Generation)

RAG lets an agent search a document library before answering. Instead of relying on the model's training data, the agent retrieves the most relevant chunks from your documents and includes them in the prompt.

### Ingesting Documents

```python
from agentmesh import SQLiteStore
from agentmesh.memory import RetrievalEngine

store  = SQLiteStore()
engine = RetrievalEngine(store)

# Ingest a document — splits into chunks and indexes embeddings
engine.ingest(
    doc_id="report-2025",
    text=open("annual_report.txt").read(),
    metadata={"source": "annual_report.txt", "year": 2025},
)
```

### Retrieving Chunks

```python
chunks = engine.retrieve(
    query="What was the revenue growth in 2025?",
    top_k=5,
    min_score=0.7,
)

for chunk in chunks:
    print(chunk["text"])
    print(chunk["score"])   # cosine similarity score
    print(chunk["metadata"])
```

### Using RAG Inside an Agent Tool

```python
from agentmesh import tool, PermissionLevel
from agentmesh.memory import RetrievalEngine

engine = RetrievalEngine(SQLiteStore())

@tool("search_docs", "Search the document library.", {"query": "string"})
def search_docs(arguments: dict, context) -> dict:
    chunks = engine.retrieve(arguments["query"], top_k=3)
    return {"chunks": [{"text": c["text"], "score": c["score"]} for c in chunks]}
```

### What Gets Recorded per RAG Retrieval

Every `engine.retrieve()` call records a `rag.retrieval` span with:

| Field | Description |
|---|---|
| `query` | The search query sent to the vector store |
| `vector_store` | Which store was searched (SQLite or FAISS) |
| `embedding_model` | The model used to embed the query |
| `chunk_ids` | IDs of the returned chunks |
| `document_previews` | First 200 characters of each chunk |
| `scores` | Cosine similarity scores |
| `citation_metadata` | Source file, page, author, year — whatever was stored at ingest |

---

## Vector Store Options

| Store | When to use |
|---|---|
| SQLite (default) | Local development, small-to-medium document sets |
| FAISS | Large document sets, fast nearest-neighbour search |

Install the FAISS adapter:
```bash
pip install -e ".[faiss]"
```

---

## Dashboard: Memory & RAG Page

The **Memory & RAG** page answers: *which memory record or retrieved document influenced this answer?*

- **Memory operations** — every read/write with key, value, agent, and timestamp
- **Versioned records** — full version history for long-term memory keys
- **RAG retrievals** — query, returned chunks, similarity scores, source metadata

---

## Running the Example

```bash
python examples/rag_document_qa.py
```
