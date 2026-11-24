"""Request dependencies: current user, role checks, client IP and rate limiting."""

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User
from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not active")
    issued_ms = int(payload.get("iat_ms") or int(payload.get("iat", 0)) * 1000)
    if user.sessions_valid_after and issued_ms < int(user.sessions_valid_after.timestamp() * 1000):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session ended, please sign in again")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    if get_settings().admin_2fa_required and not user.totp_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Turn on two-factor authentication first (POST /api/auth/2fa/setup)")
    return user


def require_admin_any(user: User = Depends(current_user)) -> User:
    """Admin, even before two-factor is enabled (used by the 2FA setup endpoints)."""
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


def require_member(user: User = Depends(current_user)) -> User:
    if user.role != "member" or not user.person_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Team members only")
    return user


def client_ip(request: Request) -> str | None:
    if get_settings().trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


class RateLimiter:
    """Simple in-memory sliding-window limiter, per client IP and bucket."""

    def __init__(self, max_requests: int, window_seconds: int, bucket: str):
        self.max = max_requests
        self.window = window_seconds
        self.bucket = bucket
        self.hits: dict[str, deque] = defaultdict(deque)

    def __call__(self, request: Request) -> None:
        if get_settings().environment == "test":
            return
        key = f"{self.bucket}:{client_ip(request)}"
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, please try again shortly")
        q.append(now)
        if len(self.hits) > 10_000:
            self.hits.clear()


login_limiter = RateLimiter(10, 300, "login")
public_offer_limiter = RateLimiter(60, 300, "public-offer")
