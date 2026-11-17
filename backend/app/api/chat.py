"""POST /chat: run the answer pipeline and stream its events to the browser."""

import asyncio
import logging

import openai
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..errors import ApiError, redact
from ..jobs.manager import sse
from ..llm import LlmConfigError, describe_llm_error
from ..rag.pipeline import answer
from ..schemas import ChatRequest
from ..state import AppContext
from ..storage import requires_reindex
from .deps import get_ctx, get_manifest
from .ingest import SSE_HEADERS

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:
    manifest = get_manifest(ctx, body.collection_id)
    if requires_reindex(manifest, ctx.config.embedding_model_name):
        raise ApiError(409, "reindex_required", "The embedding model changed since this collection was indexed. Re-index it first.")
    try:
        llm = ctx.llm()
    except LlmConfigError as exc:
        raise ApiError(503, "llm_not_configured", str(exc)) from exc

    settings = ctx.settings()
    notices: list[str] = []
    reranker = None
    if settings.reranker:
        reranker = await asyncio.to_thread(ctx.load_reranker)
        if reranker is None:
            notices.append(f"Reranker unavailable, answering without it. {ctx.reranker_status().error or ''}".strip())
    index = ctx.index(manifest.id, manifest.index_version or 1)
    history = [turn.model_dump() for turn in body.history]

    async def events():
        for notice in notices:
            yield sse("notice", {"message": notice})
        try:
            async for event, data in answer(
                body.question,
                history,
                index=index,
                embeddings=ctx.embeddings(),
                llm=llm,
                k=settings.retrieval_k,
                hybrid=settings.hybrid_search,
                min_relevance=settings.min_relevance,
                reranker=reranker,
                query_rewrite=settings.query_rewrite,
            ):
                if event == "token" and await request.is_disconnected():
                    log.info("Client disconnected; generation stopped")
                    return
                yield sse(event, data)
        except asyncio.CancelledError:
            # The browser went away (Stop button, closed tab): cancelling here also closes the LLM request.
            log.info("Client disconnected; generation stopped")
            raise
        except (openai.OpenAIError, LlmConfigError, TimeoutError) as exc:
            message, hint = describe_llm_error(exc, ctx.config)
            yield sse("error", {"code": "llm_error", "message": message, "hint": hint})
        except Exception as exc:
            log.exception("Chat pipeline failed")
            message = redact(f"{exc.__class__.__name__}: {exc}", ctx.config.secret_values())[:300]
            yield sse("error", {"code": "pipeline_error", "message": message, "hint": "See the backend log for details."})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)
