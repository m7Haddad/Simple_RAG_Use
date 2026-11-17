"""Knowledge base ("collection") endpoints: create, list, add sources, re-index, delete, and the vector map."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from ..errors import ApiError
from ..jobs.ingest import PendingSource, new_source_id, run_ingest, run_reindex
from ..rag.projection import get_vector_map
from ..schemas import CollectionDetail, CollectionSummary, DeleteResponse, JobInfo, JobStarted, MapQueryResponse, VectorMapResponse
from ..sources import SourceError, save_upload
from ..state import AppContext
from ..storage import Manifest, NotFoundError, requires_reindex
from .deps import active_job_id, get_ctx, get_manifest

router = APIRouter(prefix="/collections", tags=["collections"])


def _summary(ctx: AppContext, manifest: Manifest) -> CollectionSummary:
    return ctx.collections.summary(manifest, ctx.settings(), ctx.config.embedding_model_name, active_job_id(ctx, manifest.id))


def _clean_urls(urls: list[str]) -> list[str]:
    cleaned = []
    for url in (u.strip() for u in urls):
        if not url:
            continue
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ApiError(422, "invalid_url", f"Not a valid http(s) URL: {url[:100]}")
        cleaned.append(url)
    return list(dict.fromkeys(cleaned))


async def _collect_sources(ctx: AppContext, collection_id: str, files: list[UploadFile], urls: list[str]) -> list[PendingSource]:
    clean_urls = _clean_urls(urls)
    real_files = [f for f in files if f.filename]
    total = len(real_files) + len(clean_urls)
    if total == 0:
        raise ApiError(422, "no_sources", "Add at least one file or URL")
    if total > ctx.config.max_sources_per_request:
        raise ApiError(422, "too_many_sources", f"At most {ctx.config.max_sources_per_request} sources per request")

    pending: list[PendingSource] = []
    max_bytes = ctx.config.max_upload_mb * 1024 * 1024
    for upload in real_files:
        try:
            saved = await save_upload(upload, ctx.collections.uploads_dir(collection_id), max_bytes)
        except SourceError as exc:
            for p in pending:
                p.path.unlink(missing_ok=True)
            raise ApiError(422, exc.code, exc.message) from exc
        pending.append(PendingSource(new_source_id(), saved.display_name, "file", saved.path.name, saved.path))
    for url in clean_urls:
        pending.append(PendingSource(new_source_id(), url, "url", url))
    return pending


def _start_ingest(ctx: AppContext, manifest: Manifest, pending: list[PendingSource]) -> JobStarted:
    job = ctx.jobs.submit(
        "ingest", manifest.id, [p.as_job_source() for p in pending],
        lambda job: run_ingest(ctx, job, manifest.id, pending),
    )
    return JobStarted(
        collection=_summary(ctx, manifest),
        job=JobInfo(job_id=job.id, kind="ingest", collection_id=manifest.id, stage=job.stage),
    )


@router.get("", response_model=list[CollectionSummary])
def list_collections(ctx: AppContext = Depends(get_ctx)) -> list[CollectionSummary]:
    return [_summary(ctx, m) for m in ctx.collections.list()]


@router.post("", response_model=JobStarted, status_code=202)
async def create_collection(
    name: str = Form(..., min_length=1, max_length=80),
    files: list[UploadFile] = File(default_factory=list),
    urls: list[str] = Form(default_factory=list),
    ctx: AppContext = Depends(get_ctx),
) -> JobStarted:
    if not name.strip():
        raise ApiError(422, "invalid_name", "Name cannot be empty")
    _clean_urls(urls)
    if not any(f.filename for f in files) and not any(u.strip() for u in urls):
        raise ApiError(422, "no_sources", "Add at least one file or URL")
    manifest = ctx.collections.create(name)
    try:
        pending = await _collect_sources(ctx, manifest.id, files, urls)
    except ApiError:
        ctx.collections.delete(manifest.id)
        raise
    return _start_ingest(ctx, manifest, pending)


@router.get("/{collection_id}", response_model=CollectionDetail)
def get_collection(collection_id: str, ctx: AppContext = Depends(get_ctx)) -> CollectionDetail:
    manifest = get_manifest(ctx, collection_id)
    return ctx.collections.detail(manifest, ctx.settings(), ctx.config.embedding_model_name, active_job_id(ctx, collection_id))


@router.get("/{collection_id}/map", response_model=VectorMapResponse)
def get_map(collection_id: str, ctx: AppContext = Depends(get_ctx)) -> VectorMapResponse:
    """Every chunk of the live index as a dot on a 2D PCA map (Lab mode)."""
    manifest = get_manifest(ctx, collection_id)
    version = manifest.index_version or 1
    vector_map = get_vector_map(ctx.index(manifest.id, version))
    return VectorMapResponse(
        index_version=version,
        dimensions=int(vector_map.projection.mean.shape[0]) if vector_map.points else 0,
        explained_variance=list(vector_map.projection.explained),
        points=vector_map.points,
    )


@router.get("/{collection_id}/map/query", response_model=MapQueryResponse)
def project_query(collection_id: str, q: str = Query(min_length=1, max_length=4000), ctx: AppContext = Depends(get_ctx)) -> MapQueryResponse:
    """Embed a question with the same model as the chunks and place it on the same map."""
    manifest = get_manifest(ctx, collection_id)
    if requires_reindex(manifest, ctx.config.embedding_model_name):
        raise ApiError(409, "reindex_required", "The embedding model changed since this collection was indexed. Re-index it first.")
    vector_map = get_vector_map(ctx.index(manifest.id, manifest.index_version or 1))
    if not vector_map.points:
        raise ApiError(409, "empty_index", "This collection has no indexed chunks to map yet")
    x, y = vector_map.projection.project(ctx.embeddings().embed_query(q))[0]
    return MapQueryResponse(query=q, x=round(float(x), 5), y=round(float(y), 5))


@router.post("/{collection_id}/sources", response_model=JobStarted, status_code=202)
async def add_sources(
    collection_id: str,
    files: list[UploadFile] = File(default_factory=list),
    urls: list[str] = Form(default_factory=list),
    ctx: AppContext = Depends(get_ctx),
) -> JobStarted:
    manifest = get_manifest(ctx, collection_id)
    if ctx.jobs.active_for(collection_id):
        raise ApiError(409, "job_running", "This collection is already being processed. Wait for it to finish.")
    pending = await _collect_sources(ctx, collection_id, files, urls)
    return _start_ingest(ctx, manifest, pending)


@router.post("/{collection_id}/reindex", response_model=JobStarted, status_code=202)
def reindex_collection(collection_id: str, ctx: AppContext = Depends(get_ctx)) -> JobStarted:
    manifest = get_manifest(ctx, collection_id)
    if not manifest.sources:
        raise ApiError(400, "nothing_to_reindex", "This collection has no sources yet")
    sources = [{"source_id": s.source_id, "name": s.name, "kind": s.kind} for s in manifest.sources]
    job = ctx.jobs.submit("reindex", collection_id, sources, lambda job: run_reindex(ctx, job, collection_id))
    return JobStarted(
        collection=_summary(ctx, manifest),
        job=JobInfo(job_id=job.id, kind="reindex", collection_id=collection_id, stage=job.stage),
    )


@router.delete("/{collection_id}", response_model=DeleteResponse)
def delete_collection(collection_id: str, ctx: AppContext = Depends(get_ctx)) -> DeleteResponse:
    get_manifest(ctx, collection_id)
    if ctx.jobs.active_for(collection_id):
        raise ApiError(409, "job_running", "Wait for the running job to finish before deleting")
    ctx.close_indexes(collection_id)
    try:
        ctx.collections.delete(collection_id)
    except NotFoundError as exc:
        raise ApiError(404, "collection_not_found", "Collection not found") from exc
    return DeleteResponse(deleted=collection_id)
