"""GET and PUT /settings. Reading is open; changing needs the admin token."""

from fastapi import APIRouter, Depends

from ..auth import require_admin
from ..schemas import RagSettings, SettingsResponse
from ..state import AppContext
from ..storage import stale_reasons
from .deps import get_ctx

router = APIRouter(tags=["settings"])


def settings_response(ctx: AppContext) -> SettingsResponse:
    settings = ctx.settings()
    embedding_model = ctx.config.embedding_model_name
    stale = [m.id for m in ctx.collections.list() if stale_reasons(m, settings, embedding_model)]
    return SettingsResponse(
        settings=settings,
        embedding_model=embedding_model,
        reranker=ctx.reranker_status(),
        stale_collections=stale,
    )


@router.get("/settings", response_model=SettingsResponse)
def get_settings(ctx: AppContext = Depends(get_ctx)) -> SettingsResponse:
    return settings_response(ctx)


@router.put("/settings", response_model=SettingsResponse, dependencies=[Depends(require_admin)])
def put_settings(body: RagSettings, ctx: AppContext = Depends(get_ctx)) -> SettingsResponse:
    ctx.settings_store.save(body)
    if body.reranker:
        ctx.load_reranker_in_background()
    return settings_response(ctx)
