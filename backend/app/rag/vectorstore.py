"""
STEP 4: INDEX. Store the vectors on disk in Chroma so we can search them later.

What a vector store does:
  It keeps every chunk's vector, its text, and its metadata (source, page...),
  and answers one question very fast: "which stored vectors are closest to
  this query vector?" Chroma uses an HNSW graph index, so it does not have to
  compare the query against every single chunk.

Why persistence matters:
  Embedding is the slow part of the pipeline. With a persist directory, the
  index is written to data/collections/<id>/chroma/ and simply re-opened after
  a restart. Nothing is embedded twice.

Distance metric:
  We ask Chroma for COSINE distance = 1 - cosine similarity.
    0.0  -> same direction (same meaning)
    1.0  -> unrelated
    2.0  -> opposite
  Lower is better. The Pipeline Inspector shows these raw numbers.

Versioned collections:
  A re-index builds a NEW Chroma collection (chunks_v2, chunks_v3, ...) while
  the old one keeps answering questions, then switches over and deletes the
  old one. Chat keeps working during a re-index.
"""

from collections.abc import Callable
from pathlib import Path

import chromadb
import numpy as np
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

# Chunks written to Chroma per call.
INDEX_BATCH_SIZE = 256


def collection_name(version: int) -> str:
    """Chroma collection name for an index version: chunks_v1, chunks_v2, ..."""
    return f"chunks_v{version}"


class VectorIndex:
    """One version of a knowledge base's on-disk Chroma index."""

    def __init__(self, directory: Path, version: int, embeddings: Embeddings):
        """Open the persistent Chroma collection for this version, creating it if needed."""
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.version = version
        self.client = chromadb.PersistentClient(
            path=str(directory), settings=ChromaSettings(anonymized_telemetry=False)
        )
        # LangChain's wrapper, used for searching. "hnsw:space" selects cosine distance.
        self.store = Chroma(
            client=self.client,
            collection_name=collection_name(version),
            embedding_function=embeddings,
            collection_metadata={"hnsw:space": "cosine"},
        )
        # The raw Chroma collection, used for everything the wrapper does not expose.
        self._collection = self.client.get_collection(collection_name(version))

    def count(self) -> int:
        """Number of chunks stored."""
        return self._collection.count()

    def add(
        self,
        chunks: list[Document],
        vectors: list[list[float]],
        on_batch: Callable[[int, int], None] | None = None,
    ) -> None:
        """
        Write chunks with their PRE-COMPUTED vectors. We embedded them ourselves
        in step 3 (to report progress), so Chroma does not need to embed again.
        on_batch(done, total) is called after each batch.
        """
        for start in range(0, len(chunks), INDEX_BATCH_SIZE):
            batch = chunks[start : start + INDEX_BATCH_SIZE]
            # The chunk id is the key, so writing the same chunk twice replaces it.
            self._collection.upsert(
                ids=[str(c.metadata["chunk_id"]) for c in batch],
                embeddings=vectors[start : start + INDEX_BATCH_SIZE],
                documents=[c.page_content for c in batch],
                metadatas=[c.metadata for c in batch],
            )
            if on_batch:
                on_batch(min(start + INDEX_BATCH_SIZE, len(chunks)), len(chunks))

    def search(self, query_vector: list[float], k: int) -> list[tuple[Document, float]]:
        """Nearest-neighbour search: the k chunks closest to the query vector, with their distances."""
        if self.count() == 0:
            return []
        return self.store.similarity_search_by_vector_with_relevance_scores(query_vector, k=min(k, self.count()))

    def all_chunks(self) -> list[Document]:
        """Every stored chunk (used to build the keyword/BM25 index for hybrid search)."""
        data = self._collection.get(include=["documents", "metadatas"])
        return [Document(page_content=text, metadata=meta or {}) for text, meta in zip(data["documents"], data["metadatas"])]

    def all_chunks_with_vectors(self) -> tuple[list[Document], np.ndarray]:
        """Every stored chunk together with its vector (used to draw the vector map)."""
        data = self._collection.get(include=["documents", "metadatas", "embeddings"])
        chunks = [Document(page_content=text, metadata=meta or {}) for text, meta in zip(data["documents"], data["metadatas"])]
        vectors = np.asarray(data["embeddings"], dtype=float) if len(chunks) else np.zeros((0, 0))
        return chunks, vectors

    def distances_for(self, query_vector: list[float], chunk_ids: list[int]) -> dict[int, float]:
        """
        Cosine distance between the query and specific chunks. Hybrid search
        can surface a chunk via keywords that the vector search did not
        return; this gives it a comparable distance for display.
        """
        if not chunk_ids:
            return {}
        data = self._collection.get(ids=[str(i) for i in chunk_ids], include=["embeddings"])
        # Scale both vectors to length 1. Their dot product is then the cosine
        # similarity, and distance = 1 - similarity.
        query = np.asarray(query_vector, dtype=float)
        query = query / (np.linalg.norm(query) or 1.0)
        result = {}
        for chunk_id, vector in zip(data["ids"], data["embeddings"]):
            v = np.asarray(vector, dtype=float)
            result[int(chunk_id)] = float(1.0 - np.dot(query, v / (np.linalg.norm(v) or 1.0)))
        return result

    def drop_other_versions(self) -> None:
        """After a re-index switches over, delete the old versions' vectors."""
        for name in [c if isinstance(c, str) else c.name for c in self.client.list_collections()]:
            if name.startswith("chunks_v") and name != collection_name(self.version):
                self.client.delete_collection(name)

    def destroy(self) -> None:
        """Delete this version's vectors (used when a re-index fails half-way)."""
        self.client.delete_collection(collection_name(self.version))

    def close(self) -> None:
        """Release the on-disk files (Windows will not delete files that are still open)."""
        self.client.close()
