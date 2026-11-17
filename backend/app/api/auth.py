"""POST /auth/login: exchange the admin password for a short-lived token."""

from fastapi import APIRouter, Depends, Request

from ..auth import issue_token, verify_password
from ..errors import ApiError
from ..schemas import LoginRequest, LoginResponse
from ..state import AppContext
from .deps import get_ctx

router = APIRouter(tags=["auth"])

NOT_CONFIGURED = (
    "No admin password is set. From the backend folder run "
    "'python -m app.scripts.set_admin_password', then restart the backend."
)


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, ctx: AppContext = Depends(get_ctx)) -> LoginResponse:
    client = request.client.host if request.client else "unknown"
    ctx.login_limiter.check(client)
    config = ctx.config
    if not config.admin_password_hash or not config.jwt_secret:
        verify_password(body.password, None)
        raise ApiError(503, "admin_not_configured", NOT_CONFIGURED)
    if not verify_password(body.password, config.admin_password_hash.get_secret_value()):
        raise ApiError(401, "invalid_password", "Wrong password")
    ctx.login_limiter.reset(client)
    token, ttl = issue_token(config)
    return LoginResponse(token=token, expires_in=ttl)
