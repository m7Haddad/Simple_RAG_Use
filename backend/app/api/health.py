"""Health endpoints: is the server up, and can it reach the LLM?"""

import time

from fastapi import APIRouter, Depends

from ..llm import check_llm
from ..schemas import LlmHealth
from ..state import LLM_HEALTH_TTL_S, AppContext
from .deps import get_ctx

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/llm", response_model=LlmHealth)
async def llm_health(refresh: bool = False, ctx: AppContext = Depends(get_ctx)) -> LlmHealth:
    if ctx.llm_health and not refresh and time.monotonic() - ctx.llm_health[0] < LLM_HEALTH_TTL_S:
        return ctx.llm_health[1]
    result = await check_llm(ctx.config)
    ctx.llm_health = (time.monotonic(), result)
    return result
