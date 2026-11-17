"""Everything kept on disk as JSON: the RAG settings, and each knowledge base's manifest and extracted text."""

import json
import logging
import os
import re
import secrets
import shutil
import threading
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .schemas import CollectionDetail, CollectionSummary, IndexSettings, RagSettings, SourceInfo

log = logging.getLogger(__name__)

COLLECTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SOURCE_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")
DELETED_MARKER = ".deleted"


def utcnow() -> datetime:
    return datetime.now(UTC)


def write_json_atomic(path: Path, data: dict) -> None:
    """Write to a temporary file, then swap it in, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


class NotFoundError(Exception):
    """The collection or source does not exist."""


# --- Settings ----------------------------------------------------------------


class SettingsStore:
    """Loads and saves the RAG settings (data/settings.json)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> RagSettings:
        if not self.path.exists():
            return RagSettings()
        try:
            return RagSettings.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (ValidationError, ValueError) as exc:
            log.warning("Ignoring invalid %s (%s); using defaults", self.path.name, exc.__class__.__name__)
            return RagSettings()

    def save(self, settings: RagSettings) -> None:
        with self._lock:
            write_json_atomic(self.path, settings.model_dump())


# --- Collections -----------------------------------------------------------------


class Manifest(BaseModel):
    """A knowledge base's manifest.json: its sources, and the settings its index was built with."""

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    # The chunking settings and embedding model the current index was built with.
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    heading_aware_chunking: bool | None = None
    embedding_model: str | None = None
    index_version: int = 0
    indexed_at: datetime | None = None
    chunk_count: int = 0
    next_chunk_id: int = 0
    sources: list[SourceInfo] = Field(default_factory=list)

    def indexed_with(self) -> IndexSettings | None:
        if self.chunk_size is None or self.embedding_model is None:
            return None
        return IndexSettings(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap or 0,
            heading_aware_chunking=bool(self.heading_aware_chunking),
            embedding_model=self.embedding_model,
        )


def stale_reasons(manifest: Manifest, settings: RagSettings, embedding_model: str) -> list[str]:
    """Why the collection's index no longer matches the current settings (empty list = up to date)."""
    built = manifest.indexed_with()
    if built is None:
        return []
    reasons = []
    if built.chunk_size != settings.chunk_size:
        reasons.append(f"chunk size {built.chunk_size} → {settings.chunk_size}")
    if built.chunk_overlap != settings.chunk_overlap:
        reasons.append(f"chunk overlap {built.chunk_overlap} → {settings.chunk_overlap}")
    if built.heading_aware_chunking != settings.heading_aware_chunking:
        state = "on" if settings.heading_aware_chunking else "off"
        reasons.append(f"heading-aware chunking turned {state}")
    if built.embedding_model != embedding_model:
        reasons.append(f"embedding model {built.embedding_model} → {embedding_model}")
    return reasons


def requires_reindex(manifest: Manifest, embedding_model: str) -> bool:
    """A different embedding model makes the stored vectors unusable, not just outdated."""
    return manifest.embedding_model is not None and manifest.embedding_model != embedding_model


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:40].strip("-") or "kb"


class CollectionStore:
    """The knowledge bases on disk. Each has a folder holding manifest.json, raw text, uploads and its Chroma index."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # Paths
    def dir(self, collection_id: str) -> Path:
        if not COLLECTION_ID_RE.match(collection_id):
            raise NotFoundError(collection_id)
        return self.root / collection_id

    def raw_dir(self, collection_id: str) -> Path:
        return self.dir(collection_id) / "raw"

    def uploads_dir(self, collection_id: str) -> Path:
        return self.dir(collection_id) / "uploads"

    def chroma_dir(self, collection_id: str) -> Path:
        return self.dir(collection_id) / "chroma"

    def lock(self, collection_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(collection_id, threading.Lock())

    # Manifests
    def create(self, name: str) -> Manifest:
        collection_id = f"{slugify(name)}-{secrets.token_hex(3)}"
        now = utcnow()
        manifest = Manifest(id=collection_id, name=name.strip(), created_at=now, updated_at=now)
        for sub in ("raw", "uploads", "chroma"):
            (self.dir(collection_id) / sub).mkdir(parents=True, exist_ok=True)
        self.save(manifest)
        return manifest

    def get(self, collection_id: str) -> Manifest:
        path = self.dir(collection_id) / "manifest.json"
        if not path.exists() or (self.dir(collection_id) / DELETED_MARKER).exists():
            raise NotFoundError(collection_id)
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, manifest: Manifest) -> None:
        write_json_atomic(self.dir(manifest.id) / "manifest.json", manifest.model_dump(mode="json"))

    def list(self) -> list[Manifest]:
        manifests = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir() or not COLLECTION_ID_RE.match(child.name):
                continue
            try:
                manifests.append(self.get(child.name))
            except NotFoundError:
                continue
            except (ValidationError, ValueError):
                log.warning("Skipping collection %s: unreadable manifest", child.name)
        return sorted(manifests, key=lambda m: m.updated_at, reverse=True)

    def delete(self, collection_id: str) -> None:
        path = self.dir(collection_id)
        if not path.exists():
            raise NotFoundError(collection_id)
        try:
            shutil.rmtree(path)
        except OSError:
            # Windows keeps index files locked while they are open; finish on next start.
            (path / DELETED_MARKER).touch()

    def purge_deleted(self) -> None:
        for child in self.root.iterdir():
            if child.is_dir() and (child / DELETED_MARKER).exists():
                shutil.rmtree(child, ignore_errors=True)

    # Raw extracted text
    def save_raw(self, collection_id: str, source_id: str, payload: dict) -> None:
        write_json_atomic(self.raw_dir(collection_id) / f"{source_id}.json", payload)

    def load_raw(self, collection_id: str, source_id: str) -> dict:
        if not SOURCE_ID_RE.match(source_id):
            raise NotFoundError(source_id)
        path = self.raw_dir(collection_id) / f"{source_id}.json"
        if not path.exists():
            raise NotFoundError(source_id)
        return json.loads(path.read_text(encoding="utf-8"))

    # API views
    def summary(self, manifest: Manifest, settings: RagSettings, embedding_model: str, active_job_id: str | None) -> CollectionSummary:
        reasons = stale_reasons(manifest, settings, embedding_model)
        return CollectionSummary(
            id=manifest.id,
            name=manifest.name,
            created_at=manifest.created_at,
            updated_at=manifest.updated_at,
            chunk_count=manifest.chunk_count,
            source_count=len(manifest.sources),
            indexed_with=manifest.indexed_with(),
            stale=bool(reasons),
            stale_reasons=reasons,
            reindex_required=requires_reindex(manifest, embedding_model),
            active_job_id=active_job_id,
        )

    def detail(self, manifest: Manifest, settings: RagSettings, embedding_model: str, active_job_id: str | None) -> CollectionDetail:
        summary = self.summary(manifest, settings, embedding_model, active_job_id)
        return CollectionDetail(**summary.model_dump(), sources=manifest.sources)
