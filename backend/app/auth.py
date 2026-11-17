"""
Admin authentication: an argon2 password check, short-lived JWTs and a login rate limiter.
Only changing settings requires it.
"""

import math
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import AppConfig
from .errors import ApiError

_hasher = PasswordHasher()
# Verified when no admin hash is configured, so a missing password costs the same time as a wrong one.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))
JWT_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password against the stored hash. A hash is always verified, so timing does not reveal whether a password is set."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def issue_token(config: AppConfig) -> tuple[str, int]:
    ttl = config.token_ttl_minutes * 60
    now = datetime.now(UTC)
    claims = {"sub": "admin", "iat": now, "exp": now + timedelta(seconds=ttl), "jti": secrets.token_hex(8)}
    return jwt.encode(claims, config.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM), ttl


def decode_token(token: str, config: AppConfig) -> dict:
    if not config.jwt_secret:
        raise ApiError(401, "not_authenticated", "Admin login is not configured")
    try:
        return jwt.decode(token, config.jwt_secret.get_secret_value(), algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "token_expired", "Your admin session expired. Enter the password again.") from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError(401, "invalid_token", "Invalid admin token. Enter the password again.") from exc


class LoginRateLimiter:
    """Sliding window: at most `max_attempts` login attempts per IP in `window_s` seconds."""

    def __init__(self, max_attempts: int, window_s: int):
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts[key]
            while attempts and now - attempts[0] > self.window_s:
                attempts.popleft()
            if len(attempts) >= self.max_attempts:
                retry_after = max(1, math.ceil(self.window_s - (now - attempts[0])))
                raise ApiError(
                    429,
                    "too_many_attempts",
                    f"Too many login attempts. Try again in {retry_after} seconds.",
                    details={"retry_after": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )
            attempts.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


def require_admin(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """FastAPI dependency: the request must carry a valid admin token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "not_authenticated", "Admin password required")
    return decode_token(credentials.credentials, request.app.state.ctx.config)
