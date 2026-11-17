"""Job progress endpoints: the latest snapshot, or a live SSE stream."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..state import AppContext
from .deps import get_ctx

router = APIRouter(prefix="/ingest", tags=["ingest"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return ctx.jobs.get(job_id).snapshot()


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:
    job = ctx.jobs.get(job_id)
    return StreamingResponse(ctx.jobs.stream(job, request.is_disconnected), media_type="text/event-stream", headers=SSE_HEADERS)
