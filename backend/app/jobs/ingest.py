"""
The two background jobs: ingest (load new sources, then index them) and re-index
(rebuild an index from the stored text with the current settings).
"""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..errors import redact
from ..rag.loading import LoadError, Page, load_file, load_html, load_markdown, load_plain_text
from ..rag.pipeline import LoadedSource, build_index
from ..sources import SourceError, check_signature, fetch_url
from ..schemas import SourceInfo
from ..storage import utcnow
from .manager import Job

log = logging.getLogger(__name__)


@dataclass
class PendingSource:
    """A source the API has accepted but that is not loaded yet."""

    source_id: str
    name: str
    kind: str              # "file" or "url"
    original: str          # URL, or the generated filename in uploads/
    path: Path | None = None

    def as_job_source(self) -> dict:
        return {"source_id": self.source_id, "name": self.name, "kind": self.kind}


def new_source_id() -> str:
    return uuid.uuid4().hex[:12]


def run_ingest(ctx, job: Job, collection_id: str, pending: list[PendingSource]) -> None:
    """Load each source on its own (one failure does not stop the rest), then split, embed and index."""
    job.emit("loading", f"Loading {len(pending)} source(s)")
    loaded: list[LoadedSource] = []
    records: dict[str, dict] = {}

    for source in pending:
        job.update_source(source.source_id, status="loading")
        job.emit("loading", f"Loading {source.name}")
        try:
            name, original, content_type, pages = _load_source(ctx, collection_id, source)
        except (SourceError, LoadError) as exc:
            message = exc.message if isinstance(exc, SourceError) else str(exc)
            job.update_source(source.source_id, status="error", error=redact(message, ctx.config.secret_values()))
            job.emit("loading", f"Could not load {source.name}")
            continue
        except Exception as exc:
            log.exception("Unexpected error loading a source")
            job.update_source(source.source_id, status="error", error=f"Unexpected error ({exc.__class__.__name__}); see backend log")
            job.emit("loading", f"Could not load {source.name}")
            continue

        characters = sum(len(p.text) for p in pages)
        ctx.collections.save_raw(collection_id, source.source_id, {
            "source_id": source.source_id, "name": name, "kind": source.kind, "original": original,
            "content_type": content_type, "loaded_at": utcnow().isoformat(),
            "pages": [p.to_dict() for p in pages],
        })
        records[source.source_id] = {
            "source_id": source.source_id, "name": name, "kind": source.kind, "original": original,
            "content_type": content_type, "pages": len(pages), "characters": characters, "added_at": utcnow(),
        }
        loaded.append(LoadedSource(source_id=source.source_id, name=name, pages=pages))
        job.update_source(source.source_id, status="loaded", name=name, pages=len(pages), characters=characters)
        job.add_stats(pages=len(pages), characters=characters)
        job.emit("loading", f"Loaded {name}")

    if not loaded:
        job.emit("error", "No source could be loaded", error="None of the sources could be loaded. See the per-source errors.")
        return

    settings = ctx.settings()
    embedding_model = ctx.config.embedding_model_name
    with ctx.collections.lock(collection_id):
        manifest = ctx.collections.get(collection_id)
        if manifest.index_version and manifest.embedding_model != embedding_model:
            job.emit("error", "Re-index required", error="The embedding model changed since this collection was indexed. Re-index it before adding sources.")
            return
        if not manifest.index_version:
            # First index: record the current settings as this collection's chunking settings.
            manifest.index_version = 1
            manifest.chunk_size = settings.chunk_size
            manifest.chunk_overlap = settings.chunk_overlap
            manifest.heading_aware_chunking = settings.heading_aware_chunking
            manifest.embedding_model = embedding_model
        # New sources are chunked the same way as the rest of the index, so it stays consistent.
        index = ctx.index(collection_id, manifest.index_version)
        result = build_index(
            loaded,
            index=index,
            embeddings=ctx.embeddings(),
            chunk_size=manifest.chunk_size,
            chunk_overlap=manifest.chunk_overlap,
            heading_aware=bool(manifest.heading_aware_chunking),
            first_chunk_id=manifest.next_chunk_id,
            on_progress=_progress_reporter(job),
        )
        for source_id, count in result.chunks_per_source.items():
            records[source_id]["chunks"] = count
            job.update_source(source_id, status="indexed", chunks=count)
        manifest.sources.extend(SourceInfo(**record) for record in records.values())
        manifest.next_chunk_id += result.chunk_count
        manifest.chunk_count = index.count()
        manifest.indexed_at = manifest.updated_at = utcnow()
        ctx.collections.save(manifest)

    failed = sum(1 for s in job.snapshot()["sources"] if s["status"] == "error")
    suffix = f" ({failed} source(s) failed)" if failed else ""
    job.emit("done", f"Indexed {result.chunk_count} chunks from {len(loaded)} source(s){suffix}")


def run_reindex(ctx, job: Job, collection_id: str) -> None:
    """Re-chunk from the stored raw text with the CURRENT settings. Nothing is downloaded or parsed again."""
    settings = ctx.settings()
    manifest = ctx.collections.get(collection_id)
    job.emit("loading", "Reading stored text (no re-download, no re-parsing)")

    loaded: list[LoadedSource] = []
    for source in manifest.sources:
        job.update_source(source.source_id, status="loading")
        try:
            raw = ctx.collections.load_raw(collection_id, source.source_id)
        except Exception:
            job.update_source(source.source_id, status="error", error="Stored text is missing; remove and re-add this source")
            continue
        pages = [Page(**p) for p in raw["pages"]]
        characters = sum(len(p.text) for p in pages)
        loaded.append(LoadedSource(source_id=source.source_id, name=source.name, pages=pages))
        job.update_source(source.source_id, status="loaded", pages=len(pages), characters=characters)
        job.add_stats(pages=len(pages), characters=characters)
    job.emit("loading", f"Read {len(loaded)} source(s) from disk")

    if not loaded:
        job.emit("error", "Nothing to re-index", error="This collection has no stored sources to re-index.")
        return

    new_version = manifest.index_version + 1
    index = ctx.index(collection_id, new_version)
    try:
        result = build_index(
            loaded,
            index=index,
            embeddings=ctx.embeddings(),
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            heading_aware=settings.heading_aware_chunking,
            first_chunk_id=0,
            on_progress=_progress_reporter(job),
        )
    except Exception:
        index.destroy()
        ctx.close_indexes(collection_id, keep_version=manifest.index_version)
        raise

    with ctx.collections.lock(collection_id):
        manifest = ctx.collections.get(collection_id)
        manifest.index_version = new_version
        manifest.chunk_size = settings.chunk_size
        manifest.chunk_overlap = settings.chunk_overlap
        manifest.heading_aware_chunking = settings.heading_aware_chunking
        manifest.embedding_model = ctx.config.embedding_model_name
        manifest.chunk_count = index.count()
        manifest.next_chunk_id = result.chunk_count
        for source in manifest.sources:
            source.chunks = result.chunks_per_source.get(source.source_id, 0)
            job.update_source(source.source_id, status="indexed", chunks=source.chunks)
        manifest.indexed_at = manifest.updated_at = utcnow()
        ctx.collections.save(manifest)

    # The new index is live; the old version's vectors can go.
    ctx.close_indexes(collection_id, keep_version=new_version)
    index.drop_other_versions()
    job.emit("done", f"Re-indexed into {result.chunk_count} chunks")


def _progress_reporter(job: Job):
    def report(stage: str, message: str, **stats) -> None:
        if "chunks" in stats:
            job.set_stats(chunks=stats["chunks"])
        if "chunks_per_source" in stats:
            for source_id, count in stats["chunks_per_source"].items():
                job.update_source(source_id, chunks=count)
        if "sample_chunks" in stats:
            job.set_samples(stats["sample_chunks"])
        if "embedded" in stats:
            total = job.state["stats"]["chunks"] or 1
            job.set_stats(embedded=stats["embedded"], embedding_pct=round(100 * stats["embedded"] / total, 1))
        if "indexed" in stats:
            job.set_stats(indexed=stats["indexed"])
        job.emit(stage, message)

    return report


def _load_source(ctx, collection_id: str, source: PendingSource) -> tuple[str, str, str | None, list[Page]]:
    """Returns (display name, original, content type, pages)."""
    if source.kind == "file":
        pages = load_file(source.path)
        return source.name, source.original, source.path.suffix.lstrip(".").lower(), pages

    fetched = fetch_url(source.original, max_bytes=ctx.config.max_url_mb * 1024 * 1024, timeout_s=ctx.config.url_timeout_s)
    url_name = _name_from_url(fetched.url)
    if fetched.kind in ("pdf", "docx"):
        check_signature(f".{fetched.kind}", fetched.body[:1024])
        path = ctx.collections.uploads_dir(collection_id) / f"{uuid.uuid4().hex}.{fetched.kind}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetched.body)
        return url_name, fetched.url, fetched.content_type, load_file(path)
    text = fetched.text()
    if fetched.kind == "html":
        title, pages = load_html(text)
        name = f"{title[:80]} ({urlsplit(fetched.url).hostname})" if title else url_name
    elif fetched.kind == "md":
        name, pages = url_name, load_markdown(text)
    else:
        name, pages = url_name, load_plain_text(text)
    if not pages:
        raise LoadError("The page contained no readable text")
    return name, fetched.url, fetched.content_type, pages


def _name_from_url(url: str) -> str:
    parts = urlsplit(url)
    tail = parts.path.rstrip("/").rsplit("/", 1)[-1]
    return f"{parts.hostname}/{tail}"[:120] if tail else (parts.hostname or url)[:120]
