"""
The two RAG flows, written as plain, explicit steps.

  build_index()  Indexing, run once per document (or again after a re-index):
                 SPLIT -> EMBED -> INDEX.
                 Step 1 (LOAD) runs just before this, once per source, so that
                 one broken file does not stop the others (see app/jobs/ingest.py).

  answer()       Question time, run for every question:
                 (REWRITE) -> RETRIEVE -> PROMPT -> GENERATE.
                 It yields events as it goes, so the UI can show every
                 intermediate result in the Pipeline Inspector.

Both are deliberately plain function calls instead of a LangChain "chain".
You can put a breakpoint on any line and inspect what flows to the next step.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from .chunking import split_pages
from .embedding import embed_in_batches
from .generation import rewrite_query, stream_answer
from .loading import Page
from .prompting import NO_CONTEXT_ANSWER, NO_RELEVANT_ANSWER, build_messages, render_prompt, role_of
from .retrieval import RRF_MAX, Reranker, RetrievedChunk, retrieve
from .vectorstore import VectorIndex

SAMPLE_CHUNKS = 5        # how many chunks the UI previews after splitting
SAMPLE_CHARS = 200       # ...and how much of each
SNIPPET_CHARS = 240      # preview length in the sources list

# on_progress(stage, message, **stats). The job turns these calls into SSE events.
ProgressFn = Callable[..., None]


@dataclass
class LoadedSource:
    """A source after step 1 (LOAD): its id, display name and extracted pages."""

    source_id: str
    name: str
    pages: list[Page]


@dataclass
class BuildResult:
    """Outcome of build_index(): total chunks, and chunks per source."""

    chunk_count: int
    chunks_per_source: dict[str, int]


def build_index(
    sources: list[LoadedSource],
    *,
    index: VectorIndex,
    embeddings: Embeddings,
    chunk_size: int,
    chunk_overlap: int,
    heading_aware: bool,
    first_chunk_id: int,
    on_progress: ProgressFn,
) -> BuildResult:
    """Indexing flow: split the pages into chunks, embed them, store them in the index."""
    # STEP 2: SPLIT every source's pages into chunks.
    on_progress("splitting", "Splitting pages into chunks")
    chunks: list[Document] = []
    per_source: dict[str, int] = {}
    for source in sources:
        source_chunks = split_pages(
            source.pages,
            source_id=source.source_id,
            source_name=source.name,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            heading_aware=heading_aware,
            first_chunk_id=first_chunk_id + len(chunks),  # ids continue across sources
        )
        per_source[source.source_id] = len(source_chunks)
        chunks.extend(source_chunks)
    on_progress(
        "splitting",
        f"Created {len(chunks)} chunks",
        chunks=len(chunks),
        chunks_per_source=per_source,
        sample_chunks=[sample_of(c) for c in chunks[:SAMPLE_CHUNKS]],
    )

    # STEP 3: EMBED every chunk (in batches, so we can report progress).
    on_progress("embedding", f"Embedding {len(chunks)} chunks", embedded=0)
    vectors = embed_in_batches(
        embeddings,
        [c.page_content for c in chunks],
        on_batch=lambda done, total: on_progress("embedding", f"Embedded {done}/{total} chunks", embedded=done),
    )

    # STEP 4: INDEX: store chunks + vectors in Chroma (on disk).
    on_progress("indexing", "Writing vectors to the index", indexed=0)
    index.add(
        chunks,
        vectors,
        on_batch=lambda done, total: on_progress("indexing", f"Indexed {done}/{total} chunks", indexed=done),
    )
    return BuildResult(chunk_count=len(chunks), chunks_per_source=per_source)


async def answer(
    question: str,
    history: list[dict],
    *,
    index: VectorIndex,
    embeddings: Embeddings,
    llm: BaseChatModel,
    k: int,
    hybrid: bool,
    reranker: Reranker | None,
    query_rewrite: bool,
    min_relevance: float = 0.0,
) -> AsyncIterator[tuple[str, dict]]:
    """
    Question flow: (rewrite) -> retrieve -> prompt -> generate.

    Yields (event_type, data) pairs in pipeline order: "rewrite" (only when it
    runs), "sources", "prompt", one "token" per piece of the answer, then
    "timings" and "done". The API layer forwards them to the browser as they
    are produced.
    """
    started = time.perf_counter()
    timings: dict[str, float] = {}

    # (Optional) REWRITE a follow-up question into a standalone search query.
    # Without history there is nothing to resolve, so the question is used as it is.
    search_query = question
    if query_rewrite and history:
        t = time.perf_counter()
        search_query = await rewrite_query(llm, question, history)
        timings["rewrite_ms"] = _ms_since(t)
        yield "rewrite", {"original": question, "rewritten": search_query, "ms": timings["rewrite_ms"]}

    # STEP 5: RETRIEVE, exactly once. The same `retrieved` list feeds both
    # the sources shown to the user AND the prompt below. The search is
    # CPU-bound, so it runs in a worker thread to keep the server responsive.
    retrieved = await asyncio.to_thread(
        retrieve, search_query, index=index, embeddings=embeddings, k=k, hybrid=hybrid, reranker=reranker, min_relevance=min_relevance
    )
    timings.update(retrieved.timings_ms)
    yield "sources", {
        "query": search_query,
        "mode": retrieved.mode,
        "dropped": retrieved.dropped,
        "chunks": [serialize_chunk(c) for c in retrieved.chunks],
    }

    # STEP 6: PROMPT, built from those same chunks. Note that it asks the
    # user's ORIGINAL question; the rewritten one was only for searching.
    messages = build_messages(question, retrieved.chunks, history)
    yield "prompt", {
        "messages": [{"role": role_of(m), "content": m.content} for m in messages],
        "text": render_prompt(messages),
    }

    # STEP 7: GENERATE, streamed token by token.
    parts: list[str] = []
    generation_started = time.perf_counter()
    if not retrieved.chunks:
        # Either the index is empty, or every candidate scored below min_relevance.
        # With no context to answer from, reply with a fixed message and skip the LLM.
        reply = NO_RELEVANT_ANSWER if retrieved.dropped else NO_CONTEXT_ANSWER
        parts.append(reply)
        yield "token", {"text": reply}
        finish_reason = "no_relevant_context" if retrieved.dropped else "no_context"
    else:
        async for token in stream_answer(llm, messages):
            if not parts:
                timings["ttft_ms"] = _ms_since(generation_started)  # time to first token
            parts.append(token)
            yield "token", {"text": token}
        finish_reason = "stop"
    timings["generation_ms"] = _ms_since(generation_started)
    timings["total_ms"] = _ms_since(started)
    yield "timings", timings
    yield "done", {"answer": "".join(parts), "finish_reason": finish_reason}


def serialize_chunk(chunk: RetrievedChunk) -> dict:
    """Convert a retrieved chunk to a JSON-friendly dict for the UI."""
    meta = chunk.document.metadata
    text = chunk.document.page_content
    return {
        "rank": chunk.rank,
        "chunk_id": meta.get("chunk_id"),
        "source_id": meta.get("source_id"),
        "source_name": meta.get("source_name"),
        "page": meta.get("page"),
        "location": meta.get("location"),
        "heading": meta.get("heading"),
        "distance": None if chunk.distance is None else round(chunk.distance, 4),
        # A friendlier 0..1 "how close" number for the score bar (1 = identical meaning).
        "relevance": None if chunk.distance is None else round(max(0.0, min(1.0, 1.0 - chunk.distance)), 4),
        "vector_rank": chunk.vector_rank,
        "bm25_rank": chunk.bm25_rank,
        "rerank_score": None if chunk.rerank_score is None else round(chunk.rerank_score, 4),
        # 0..1 versions of the hybrid and reranker scores for the score bars (None when that stage was off).
        "hybrid_score": None if chunk.rrf_score is None else round(chunk.rrf_score / RRF_MAX, 4),
        "rerank_relevance": None if chunk.rerank_relevance is None else round(chunk.rerank_relevance, 4),
        "chars": len(text),
        "snippet": text[:SNIPPET_CHARS],
        "text": text,
    }


def sample_of(chunk: Document) -> dict:
    """Short preview of a chunk for the "splitting" progress event."""
    meta = chunk.metadata
    return {
        "chunk_id": meta.get("chunk_id"),
        "source_name": meta.get("source_name"),
        "location": meta.get("location"),
        "heading": meta.get("heading"),
        "chars": len(chunk.page_content),
        "text": chunk.page_content[:SAMPLE_CHARS],
    }


def _ms_since(start: float) -> float:
    """Milliseconds elapsed since `start`, rounded to 0.1."""
    return round((time.perf_counter() - start) * 1000, 1)
