"""
STEP 5: RETRIEVE. Find the k chunks most likely to contain the answer.

The basic version (vector search) is two moves:
  1. Embed the question with the SAME model used for the chunks.
  2. Ask the vector store for the k nearest chunk vectors.

The two knobs:
  retrieval_k    How many chunks we keep. Too few and the answer may be missing
                 from the context. Too many and the prompt fills with loosely
                 related text that distracts the LLM (and costs more tokens).
  min_relevance  A relevance cutoff (relevance = 1 - cosine distance, so
                 1 = same meaning, 0 = unrelated). Chunks below it are dropped
                 before the final cut, so k is a MAXIMUM: an off-topic
                 question can return fewer chunks, or none. 0 = off.

Two optional upgrades, each behind a setting:

  Hybrid search (vector + BM25 keywords)
    Vector search is great at meaning but can miss exact terms: product
    codes, error numbers, rare names. BM25 is classic keyword search: it
    scores chunks by how often the question's words appear in them, giving
    more weight to rare words. We run both, then merge the two ranked lists
    with Reciprocal Rank Fusion (RRF): each chunk scores
    sum(1 / (60 + its rank in each list)). Chunks that rank well in either
    list rise. RRF only uses ranks, so we never have to compare a cosine
    distance with a BM25 score directly (they use different scales).

  Reranker (cross-encoder)
    The embedding model encodes the question and each chunk SEPARATELY, so it
    is fast but approximate. A cross-encoder reads the question and a chunk
    TOGETHER and outputs a relevance score. It is much more accurate, but too
    slow to run on every chunk. So we first over-fetch a larger candidate
    pool cheaply, let the cross-encoder re-order it, and keep the top k.

retrieve() is called exactly ONCE per question. The same list of chunks is
used both to build the prompt and to show the sources.
"""

import math
import re
import threading
import time
from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from .vectorstore import VectorIndex

RRF_K = 60  # the standard RRF constant; it damps the influence of the very top ranks

# The best possible RRF score: ranked first in both lists. Dividing a chunk's
# score by it gives a 0..1 "hybrid score" the UI can draw as a bar.
RRF_MAX = 2.0 / (RRF_K + 1)


@dataclass
class RetrievedChunk:
    """A chunk returned by search, with its final rank and the scores that placed it there."""

    document: Document
    rank: int                         # final position (1 = best)
    distance: float | None            # cosine distance to the question (lower = closer)
    vector_rank: int | None = None    # position in the vector-search list
    bm25_rank: int | None = None      # position in the keyword list (hybrid only)
    rerank_score: float | None = None  # cross-encoder score (reranker only; higher = better)
    rrf_score: float | None = None     # fused vector + keyword score (hybrid only; higher = better)
    rerank_relevance: float | None = None  # the cross-encoder score as a 0..1 probability (reranker only)


@dataclass
class RetrievalResult:
    """Everything retrieve() returns: the chunks, the search mode and per-stage timings."""

    chunks: list[RetrievedChunk]
    mode: str  # "vector", "hybrid", "vector+rerank" or "hybrid+rerank"
    dropped: int = 0  # candidates removed for scoring below min_relevance
    timings_ms: dict[str, float] = field(default_factory=dict)


def retrieve(
    question: str,
    *,
    index: VectorIndex,
    embeddings: Embeddings,
    k: int,
    hybrid: bool = False,
    reranker: "Reranker | None" = None,
    min_relevance: float = 0.0,
) -> RetrievalResult:
    """
    Search the index for the chunks that best match the question.

    Embeds the question, fetches the nearest chunks, optionally blends in
    keyword matches and reranks, then keeps the top k. Each stage is timed so
    the Pipeline Inspector can show where the milliseconds went.
    """
    timings: dict[str, float] = {}
    started = time.perf_counter()

    # 1. The question becomes a vector in the same space as the chunks.
    query_vector = embeddings.embed_query(question)
    timings["embed_ms"] = _ms_since(started)

    # 2. Nearest neighbours. Fetch a bigger pool when a later stage will re-sort it.
    pool_size = max(k * 4, 20) if (hybrid or reranker) else k
    t = time.perf_counter()
    vector_hits = index.search(query_vector, pool_size)
    candidates = [
        RetrievedChunk(document=doc, rank=i + 1, distance=float(dist), vector_rank=i + 1)
        for i, (doc, dist) in enumerate(vector_hits)
    ]
    timings["search_ms"] = _ms_since(t)

    # 3. Optional: blend in keyword matches.
    if hybrid and candidates:
        t = time.perf_counter()
        candidates = _hybrid_merge(question, query_vector, candidates, index, pool_size)
        timings["bm25_ms"] = _ms_since(t)

    # 4. Optional: drop candidates that are too far from the question to be useful.
    # relevance = 1 - distance, so "relevance >= min_relevance" means "distance <= 1 - min_relevance".
    dropped = 0
    if min_relevance > 0:
        kept = [c for c in candidates if c.distance is not None and 1.0 - c.distance >= min_relevance]
        dropped = len(candidates) - len(kept)
        candidates = kept

    # 5. Optional: let the cross-encoder re-order the pool.
    if reranker and candidates:
        t = time.perf_counter()
        scores = reranker.score(question, [c.document.page_content for c in candidates])
        for chunk, score in zip(candidates, scores):
            chunk.rerank_score = float(score)
            chunk.rerank_relevance = reranker_relevance(reranker, float(score))
        candidates.sort(key=lambda c: c.rerank_score, reverse=True)
        timings["rerank_ms"] = _ms_since(t)

    # 6. Keep the best k and number them 1..k.
    final = candidates[:k]
    for position, chunk in enumerate(final, start=1):
        chunk.rank = position
    timings["retrieval_ms"] = _ms_since(started)

    mode = ("hybrid" if hybrid else "vector") + ("+rerank" if reranker else "")
    return RetrievalResult(chunks=final, dropped=dropped, mode=mode, timings_ms=timings)


# --- Hybrid search: BM25 + Reciprocal Rank Fusion --------------------------

# Common words that carry no meaning for a keyword search.
_STOPWORDS = frozenset(
    "a an and are as at be by do does for from how i in is it of on or that the this to was what when where which who why with you".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase the text, split it into words and numbers, and drop the stopwords."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


# Built BM25 indexes, kept in memory. Several requests can arrive at once, hence the lock.
_bm25_cache: dict[tuple, tuple] = {}
_bm25_lock = threading.Lock()


def _get_bm25(index: VectorIndex):
    """BM25 needs the full list of chunks. Build it once per index version and cache it."""
    from rank_bm25 import BM25Okapi

    # The chunk count is part of the key, so adding sources rebuilds the keyword index.
    key = (str(index.directory), index.version, index.count())
    with _bm25_lock:
        if key not in _bm25_cache:
            chunks = index.all_chunks()
            # BM25 cannot handle an empty document, so a chunk with no usable words gets a placeholder.
            bm25 = BM25Okapi([tokenize(c.page_content) or ["_"] for c in chunks])
            if len(_bm25_cache) >= 4:
                _bm25_cache.pop(next(iter(_bm25_cache)))  # keep memory bounded
            _bm25_cache[key] = (bm25, chunks)
        return _bm25_cache[key]


def _hybrid_merge(
    question: str,
    query_vector: list[float],
    vector_candidates: list[RetrievedChunk],
    index: VectorIndex,
    pool_size: int,
) -> list[RetrievedChunk]:
    """Add the keyword (BM25) hits to the vector candidates and re-order everything by RRF."""
    # Score every chunk by keywords and keep the best ones that matched at all.
    bm25, all_chunks = _get_bm25(index)
    scores = bm25.get_scores(tokenize(question) or ["_"])
    keyword_order = sorted(range(len(all_chunks)), key=lambda i: scores[i], reverse=True)
    keyword_hits = [all_chunks[i] for i in keyword_order[:pool_size] if scores[i] > 0]

    # Merge both result lists into one, keyed by chunk id. A chunk found by
    # both searches keeps its vector rank and gains a keyword rank.
    by_id: dict[int, RetrievedChunk] = {c.document.metadata["chunk_id"]: c for c in vector_candidates}
    for position, doc in enumerate(keyword_hits, start=1):
        chunk_id = doc.metadata["chunk_id"]
        if chunk_id not in by_id:
            by_id[chunk_id] = RetrievedChunk(document=doc, rank=0, distance=None)
        by_id[chunk_id].bm25_rank = position

    # Chunks found only by keywords still get a real cosine distance for display.
    missing = [cid for cid, c in by_id.items() if c.distance is None]
    for cid, dist in index.distances_for(query_vector, missing).items():
        by_id[cid].distance = dist

    # RRF score: sum of 1/(60 + rank) over the lists the chunk appears in.
    def rrf(chunk: RetrievedChunk) -> float:
        return sum(1.0 / (RRF_K + r) for r in (chunk.vector_rank, chunk.bm25_rank) if r is not None)

    # Best fused score first. Keep the score so the UI can show it.
    for chunk in by_id.values():
        chunk.rrf_score = rrf(chunk)
    return sorted(by_id.values(), key=rrf, reverse=True)


# --- Reranker --------------------------------------------------------------


class Reranker:
    """A small local cross-encoder (~90 MB, downloaded on first use) that scores (question, text) pairs."""

    def __init__(self, model_name: str):
        """Load the cross-encoder, from the local cache if possible."""
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        try:
            self.model = CrossEncoder(model_name, local_files_only=True)
        except Exception:
            self.model = CrossEncoder(model_name)  # first use: download it
        # Most MS MARCO cross-encoders output raw logits (about -12..+12), not probabilities.
        activation = getattr(self.model, "activation_fn", None)
        self.outputs_logits = activation is None or type(activation).__name__ == "Identity"

    def score(self, question: str, texts: list[str]) -> list[float]:
        """Score each text against the question (higher = more relevant)."""
        return [float(s) for s in self.model.predict([(question, t) for t in texts])]


def reranker_relevance(reranker: "Reranker", score: float) -> float:
    """
    Turn a cross-encoder score into a 0..1 "probability this chunk answers the
    question". The model was trained so that sigmoid(logit) is that probability,
    which is why it tends to be decisive: close to 1 or close to 0.
    """
    if getattr(reranker, "outputs_logits", True):
        # Sigmoid. The score is clamped to +-60 first so exp() cannot overflow.
        return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, score))))
    return max(0.0, min(1.0, score))


def _ms_since(start: float) -> float:
    """Milliseconds elapsed since `start`, rounded to 0.1."""
    return round((time.perf_counter() - start) * 1000, 1)
