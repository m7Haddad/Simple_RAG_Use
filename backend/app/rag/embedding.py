"""
STEP 3: EMBED. Turn text into vectors (lists of numbers) that capture meaning.

What an embedding is:
  A model reads a piece of text and outputs a fixed-length list of numbers
  (384 of them for all-MiniLM-L6-v2). Texts with similar meaning get vectors
  that point in similar directions, even when they share no words:
  "reset my password" lands close to "I forgot my login credentials".
  That is what lets us search by meaning instead of by exact keywords.

Why a local model:
  sentence-transformers models run on your own CPU, need no API key, and your
  documents never leave the machine. The model (~90 MB) is downloaded once,
  on first use, into the Hugging Face cache.

The one rule you must not break:
  The SAME model must embed both the chunks (at indexing time) and the question
  (at query time). Vectors from different models live in different "spaces"
  and cannot be compared. That is why each collection records which model
  built it, and why changing EMBEDDING_MODEL_NAME marks every index stale.
"""

import threading
from collections.abc import Callable

from langchain_core.embeddings import Embeddings

EMBED_BATCH_SIZE = 32  # chunks per model call; small batches let us report progress

# Loaded models, kept for the life of the process so each one loads only once.
_models: dict[str, Embeddings] = {}
_models_lock = threading.Lock()


def get_embedding_model(model_name: str) -> Embeddings:
    """Return the embedding model, loading it on first use. Loading takes seconds; embedding a question takes milliseconds."""
    with _models_lock:  # the startup warm-up and the first request may ask at the same moment
        if model_name not in _models:
            _models[model_name] = _load_embedding_model(model_name)
        return _models[model_name]


def _load_embedding_model(model_name: str) -> Embeddings:
    """Load the model from the local Hugging Face cache, downloading it only if it is missing."""
    from langchain_huggingface import HuggingFaceEmbeddings

    def load(local_only: bool) -> Embeddings:
        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"local_files_only": local_only},
            # Normalising makes every vector length 1, so comparing two vectors
            # only measures the ANGLE between them (cosine similarity).
            encode_kwargs={"normalize_embeddings": True},
        )

    try:
        return load(local_only=True)  # already downloaded: start without touching the network
    except Exception:
        return load(local_only=False)  # first run: download once into the Hugging Face cache


def embed_in_batches(
    model: Embeddings,
    texts: list[str],
    on_batch: Callable[[int, int], None] | None = None,
    batch_size: int = EMBED_BATCH_SIZE,
) -> list[list[float]]:
    """
    Embed many chunks, a batch at a time. The result is the same as one big
    call, but batching lets the UI show real progress (and keeps memory flat).
    on_batch(done, total) is called after each batch.
    """
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(model.embed_documents(texts[start : start + batch_size]))
        if on_batch:
            on_batch(len(vectors), len(texts))
    return vectors
