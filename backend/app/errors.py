"""One error format for the whole API, plus redaction that keeps secrets out of responses and logs."""

import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    """An error returned to the client as {"error": {"code", "message", "details"}}."""

    def __init__(self, status: int, code: str, message: str, details=None, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


_KEY_PATTERN = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,})")


def redact(text: str, secrets: list[str]) -> str:
    """Remove secret values (and anything that looks like an API key) from a message."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return _KEY_PATTERN.sub("[redacted]", text)


class RedactingFormatter(logging.Formatter):
    """Wraps a handler's formatter so the final log line (including tracebacks) never contains a secret."""

    def __init__(self, inner: logging.Formatter | None, secrets: list[str]):
        super().__init__()
        self.inner = inner or logging.Formatter("%(levelname)s %(name)s: %(message)s")
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        return redact(self.inner.format(record), self.secrets)


def install_log_redaction(secrets: list[str]) -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            if not isinstance(handler.formatter, RedactingFormatter):
                handler.setFormatter(RedactingFormatter(handler.formatter, secrets))


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
        msg = str(err.get("msg", "invalid value")).removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "Invalid request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(error_body("validation_error", _validation_message(exc), details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.exception("Unhandled error: %s", exc.__class__.__name__)
        return JSONResponse(error_body("internal_error", "Something went wrong on the server. Check the backend log."), status_code=500)
