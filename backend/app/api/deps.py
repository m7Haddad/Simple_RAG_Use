"""Small helpers shared by the routers."""

from fastapi import Request

from ..errors import ApiError
from ..state import AppContext
from ..storage import Manifest, NotFoundError


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_manifest(ctx: AppContext, collection_id: str) -> Manifest:
    try:
        return ctx.collections.get(collection_id)
    except NotFoundError as exc:
        raise ApiError(404, "collection_not_found", "Collection not found") from exc


def active_job_id(ctx: AppContext, collection_id: str) -> str | None:
    job = ctx.jobs.active_for(collection_id)
    return job.id if job else None
