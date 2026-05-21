from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from agentmesh.dependencies import optional_import
from agentmesh.storage import SQLiteStore
from agentmesh.types import JsonObject, JsonValue, stable_hash


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class HashEmbeddingProvider:
    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        vector = [0.0 for _ in range(self.dimensions)]
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        for token in tokens:
            index = int(stable_hash(token)[:8], 16) % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


@dataclass(slots=True)
class RetrievedDocument:
    document_id: str
    source: str
    content: str
    metadata: JsonObject
    score: float

    def to_json(self) -> JsonObject:
        return {
            "document_id": self.document_id,
            "source": self.source,
            "content": self.content,
            "metadata": self.metadata,
            "score": self.score,
        }


class SQLiteVectorStore:
    def __init__(self, store: SQLiteStore, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.store = store
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()

    async def add_text(self, source: str, content: str, metadata: JsonObject | None = None) -> str:
        document_id = stable_hash(f"{source}:{content}")[:24]
        embedding = await self.embedding_provider.embed(content)
        self.store.add_document(document_id, source, content, metadata or {}, embedding)
        return document_id

    async def search(self, query: str, top_k: int = 3) -> list[RetrievedDocument]:
        query_embedding = await self.embedding_provider.embed(query)
        scored: list[RetrievedDocument] = []
        for document in self.store.list_documents():
            embedding_value = document.get("embedding", [])
            embedding = [float(item) for item in embedding_value] if isinstance(embedding_value, list) else []
            score = cosine_similarity(query_embedding, embedding)
            metadata = document.get("metadata", {})
            scored.append(
                RetrievedDocument(
                    document_id=str(document["id"]),
                    source=str(document["source"]),
                    content=str(document["content"]),
                    metadata=metadata if isinstance(metadata, dict) else {},
                    score=score,
                )
            )
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]


class FAISSVectorStore:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        dimensions: int = 64,
        index_path: str | Path | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider or HashEmbeddingProvider(dimensions)
        self.dimensions = dimensions
        self.index_path = Path(index_path) if index_path is not None else None
        self._documents: list[JsonObject] = []
        self._faiss = optional_import("faiss", "faiss")
        self._np = optional_import("numpy", "faiss")
        self._index = self._faiss.IndexFlatIP(dimensions)
        if self.index_path is not None and self.index_path.exists():
            self.load(self.index_path)

    async def add_text(self, source: str, content: str, metadata: JsonObject | None = None) -> str:
        document_id = stable_hash(f"{source}:{content}")[:24]
        embedding = await self.embedding_provider.embed(content)
        vector = self._np.array([embedding], dtype="float32")
        self._index.add(vector)
        self._documents.append(
            {
                "id": document_id,
                "source": source,
                "content": content,
                "metadata": metadata or {},
            }
        )
        if self.index_path is not None:
            self.save(self.index_path)
        return document_id

    async def search(self, query: str, top_k: int = 3) -> list[RetrievedDocument]:
        if self._index.ntotal == 0:
            return []
        query_embedding = await self.embedding_provider.embed(query)
        vector = self._np.array([query_embedding], dtype="float32")
        scores, indices = self._index.search(vector, min(top_k, self._index.ntotal))
        results: list[RetrievedDocument] = []
        for score, index in zip(scores[0], indices[0], strict=True):
            if index < 0:
                continue
            document = self._documents[int(index)]
            metadata = document.get("metadata", {})
            results.append(
                RetrievedDocument(
                    document_id=str(document["id"]),
                    source=str(document["source"]),
                    content=str(document["content"]),
                    metadata=metadata if isinstance(metadata, dict) else {},
                    score=float(score),
                )
            )
        return results

    def save(self, index_path: str | Path) -> None:
        path = Path(index_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self._index, str(path))
        metadata_path = path.with_suffix(path.suffix + ".json")
        metadata_path.write_text(__import__("json").dumps(self._documents, indent=2), encoding="utf-8")

    def load(self, index_path: str | Path) -> None:
        path = Path(index_path)
        self._index = self._faiss.read_index(str(path))
        metadata_path = path.with_suffix(path.suffix + ".json")
        if metadata_path.exists():
            loaded = __import__("json").loads(metadata_path.read_text(encoding="utf-8"))
            self._documents = loaded if isinstance(loaded, list) else []


@dataclass(slots=True)
class RetrievalEngine:
    vector_store: SQLiteVectorStore | FAISSVectorStore
    top_k: int = 3

    async def ingest(self, documents: dict[str, str]) -> list[str]:
        ids: list[str] = []
        for source, content in documents.items():
            ids.append(await self.vector_store.add_text(source, content, {"source": source}))
        return ids

    async def retrieve(self, query: str, trace_context: object | None = None) -> list[RetrievedDocument]:
        results = await self.vector_store.search(query, self.top_k)
        if trace_context is not None:
            trace_context.recorder.event(
                trace_context.trace_id,
                "rag.retrieval",
                "retriever",
                {
                    "query": query,
                    "documents": [result.to_json() for result in results],
                },
                parent_span_id=(
                    getattr(trace_context, "active_agent_span_id", None)
                    or getattr(trace_context, "parent_span_id", None)
                    or getattr(trace_context, "root_span_id", None)
                ),
            )
        return results

    def context_text(self, results: list[RetrievedDocument]) -> str:
        return "\n\n".join(f"[{item.document_id}] {item.content}" for item in results)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    denominator = left_norm * right_norm
    if denominator == 0.0:
        return 0.0
    return numerator / denominator
