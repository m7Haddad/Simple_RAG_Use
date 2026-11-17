"""
BONUS: MAP. Squash the 384-dimensional chunk vectors into 2D so you can look at them.

Why this is only a picture:
  Every chunk vector has 384 numbers. A screen has 2 axes. Any 2D view has to
  throw information away, so two dots that look close may not be close in the
  real space (and the other way round). The distances in the Inspector are the
  real numbers; the map is a teaching aid that shows the overall shape.

How PCA (Principal Component Analysis) picks the two axes:
  1. Centre the data: subtract the average vector from every vector.
  2. Find the direction along which the chunks differ the most. That is axis 1.
  3. Find the direction, at a right angle to axis 1, along which they differ
     the most of what is left. That is axis 2.
  Each chunk's (x, y) is simply how far it lies along those two directions.
  "Explained variance" says how much of the total spread those two axes
  capture. With text embeddings it is often only 10-25%, which is a good
  reminder of how much the flat picture leaves out.

Why PCA and not t-SNE or UMAP:
  PCA is a fixed linear formula, so a NEW vector (your question) can be placed
  on the same map exactly, with the same mean and the same two directions. It
  also needs nothing beyond numpy and runs in milliseconds.
"""

import threading
from dataclasses import dataclass

import numpy as np

from .vectorstore import VectorIndex

SNIPPET_CHARS = 160  # preview text shown when hovering a dot


@dataclass
class Projection:
    """A fitted 2D projection: the average vector, the two axes, and how much spread they keep."""

    mean: np.ndarray            # shape (dims,)
    components: np.ndarray      # shape (2, dims): the two axes
    explained: tuple[float, float]  # share of the total variance kept by each axis (0..1)

    def project(self, vectors: np.ndarray) -> np.ndarray:
        """Place any vector (a chunk or a question) on the map: centre it, then measure it along each axis."""
        return (np.atleast_2d(vectors) - self.mean) @ self.components.T


def fit_pca(vectors: np.ndarray) -> Projection:
    """Fit a 2-axis PCA with a plain SVD (no scikit-learn needed)."""
    mean = vectors.mean(axis=0)
    centred = vectors - mean
    # Fewer than 2 chunks (or identical chunks): nothing to spread out, put everything at the centre.
    if len(vectors) < 2 or not np.any(centred):
        return Projection(mean=mean, components=np.zeros((2, vectors.shape[1])), explained=(0.0, 0.0))
    # The rows of vt are the directions of greatest spread, best first.
    _, singular, vt = np.linalg.svd(centred, full_matrices=False)
    # The squared singular values are proportional to the variance along each direction.
    variance = singular**2
    total = float(variance.sum()) or 1.0
    # Keep the first two directions. (With exactly 2 chunks there may be only one, so pad with zeros.)
    components = np.zeros((2, vectors.shape[1]))
    components[: min(2, len(vt))] = vt[:2]
    explained = tuple(float(v / total) for v in (list(variance[:2]) + [0.0, 0.0])[:2])
    return Projection(mean=mean, components=components, explained=explained)


@dataclass
class VectorMap:
    """The map for one index version: the fitted projection plus every chunk's dot."""

    projection: Projection
    points: list[dict]


# Built maps, kept in memory so the PCA runs once per index version.
_map_cache: dict[tuple, VectorMap] = {}
_map_lock = threading.Lock()


def get_vector_map(index: VectorIndex) -> VectorMap:
    """Build (or reuse) the 2D map of every chunk in this index version."""
    # The chunk count is part of the key, so adding sources rebuilds the map.
    key = (str(index.directory), index.version, index.count())
    with _map_lock:
        if key not in _map_cache:
            if len(_map_cache) >= 4:
                _map_cache.pop(next(iter(_map_cache)))  # keep memory bounded
            _map_cache[key] = _build_map(index)
        return _map_cache[key]


def _build_map(index: VectorIndex) -> VectorMap:
    """Fit the projection on every chunk vector, then turn each chunk into a dot with a hover preview."""
    chunks, vectors = index.all_chunks_with_vectors()
    if not chunks:
        return VectorMap(projection=fit_pca(np.zeros((1, 1))), points=[])
    projection = fit_pca(vectors)
    xy = projection.project(vectors)
    points = []
    for chunk, (x, y) in zip(chunks, xy):
        meta = chunk.metadata
        points.append({
            "chunk_id": meta.get("chunk_id"),
            "source_id": meta.get("source_id"),
            "source_name": meta.get("source_name"),
            "location": meta.get("location"),
            "heading": meta.get("heading"),
            "snippet": chunk.page_content[:SNIPPET_CHARS],
            "x": round(float(x), 5),
            "y": round(float(y), 5),
        })
    return VectorMap(projection=projection, points=points)
