"""Request dependencies: current user, role checks, client IP and rate limiting."""

import ipaddress
import threading
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


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def rate_key_ip(ip: str | None) -> str:
    """IP used as a rate-limit key. IPv6 is grouped by /64, since one connection usually has a whole /64."""
    if not ip:
        return "unknown"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip[:64]
    if addr.version == 6:
        embedded = _embedded_ipv4(addr)
        if embedded is not None:
            return str(embedded)  # an IPv4 client written in IPv6 form: limit it by its real IPv4 address
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address inside an IPv4-mapped, NAT64, 6to4 or Teredo IPv6 address, if any.

    Without this, every such client would share one /64 key, and one of them could lock out all the others.
    """
    if addr.ipv4_mapped:
        return addr.ipv4_mapped
    if addr in _NAT64:
        return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    if addr.sixtofour:
        return addr.sixtofour
    if addr.teredo:
        return addr.teredo[1]
    return None


def client_ip(request: Request) -> str | None:
    """The caller's IP address.

    Behind proxies, X-Forwarded-For reads "client-supplied, ..., address seen by our proxy". The left-most
    entries are whatever the caller sent and can be faked, so use the entry added by our own proxy:
    `trusted_proxy_hops` from the right. Fall back to the connecting address if it is missing or invalid.
    """
    settings = get_settings()
    peer = request.client.host if request.client else None
    hops = settings.trusted_proxy_hops if settings.trust_proxy else 0
    if hops:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= hops:
            ip = _valid_ip(parts[-hops])
            if ip:
                return ip
    return peer[:64] if peer else None


MAX_TRACKED_KEYS = 10_000


def _prune(hits: dict[str, deque], window_seconds: float, protect_at: int) -> None:
    """Keep memory bounded without ever dropping an active lockout.

    First drop keys with no hits inside the window. If still too many, drop the keys with the fewest
    hits; keys at or above `protect_at` (currently blocked) are never dropped, so flooding the limiter
    with new keys cannot clear a lockout.
    """
    if len(hits) <= MAX_TRACKED_KEYS:
        return
    now = time.monotonic()
    for key in [k for k, q in hits.items() if not q or now - q[-1] > window_seconds]:
        del hits[key]
    if len(hits) <= MAX_TRACKED_KEYS:
        return
    removable = sorted((len(q), k) for k, q in hits.items() if len(q) < protect_at)
    for _, key in removable[: len(hits) - MAX_TRACKED_KEYS]:
        del hits[key]


class RateLimiter:
    """Simple in-memory sliding-window limiter, per client IP and bucket."""

    def __init__(self, max_requests: int, window_seconds: int, bucket: str):
        self.max = max_requests
        self.window = window_seconds
        self.bucket = bucket
        self.hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()  # requests run in a thread pool: check-and-count must be atomic

    def __call__(self, request: Request) -> None:
        if get_settings().environment == "test":
            return
        key = f"{self.bucket}:{rate_key_ip(client_ip(request))}"
        with self._lock:
            now = time.monotonic()
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, please try again shortly")
            q.append(now)
            _prune(self.hits, self.window, self.max)


class AccountThrottle:
    """Sliding-window failure counter keyed by account (or account + IP), independent of the IP limiter.

    In memory, like RateLimiter: correct for the single Render instance; move to the database or
    Redis before running more than one instance.
    """

    def __init__(self, bucket: str):
        self.bucket = bucket
        self.hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.RLock()

    @staticmethod
    def _key(key: str) -> str:
        return key.strip().lower()

    def count(self, key: str, window_seconds: int) -> int:
        with self._lock:
            q = self.hits.get(self._key(key))  # .get: checking a key must not create one
            if not q:
                return 0
            now = time.monotonic()
            while q and now - q[0] > window_seconds:
                q.popleft()
            return len(q)

    def blocked(self, key: str, limit: int, window_seconds: int) -> bool:
        return self.count(key, window_seconds) >= limit

    def hit(self, key: str, window_seconds: int, protect_at: int) -> int:
        """Count one failure and return the new count."""
        with self._lock:
            self.count(key, window_seconds)
            q = self.hits[self._key(key)]
            q.append(time.monotonic())
            new = len(q)
            _prune(self.hits, window_seconds, protect_at)
            return new

    def try_reserve(self, key: str, limit: int, window_seconds: int) -> int:
        """Atomically count an attempt if under `limit`. Returns the new count, or 0 if the limit is reached.

        Reserving before the (slow) checks means parallel requests cannot all pass the limit before any is
        counted. A request that turns out not to be a failure gives its slot back with `refund`.
        """
        with self._lock:
            if self.count(key, window_seconds) >= limit:
                return 0
            q = self.hits[self._key(key)]
            q.append(time.monotonic())
            new = len(q)
            _prune(self.hits, window_seconds, limit)
            return new

    def refund(self, key: str) -> None:
        """Give back one reserved slot."""
        with self._lock:
            q = self.hits.get(self._key(key))
            if q:
                q.pop()
                if not q:
                    del self.hits[self._key(key)]

    def reset(self, key: str) -> None:
        with self._lock:
            self.hits.pop(self._key(key), None)

    def clear(self) -> None:
        with self._lock:
            self.hits.clear()


login_limiter = RateLimiter(10, 300, "login")
refresh_limiter = RateLimiter(60, 300, "refresh")  # the app renews about every 14 minutes per tab
login_failures = AccountThrottle("login-failures")  # keyed by account + IP: the hard lock
account_failures = AccountThrottle("account-failures")  # keyed by account: stops spread-out guessing
totp_failures = AccountThrottle("totp-failures")  # keyed by account: hard ceiling on 2FA code guesses
reset_requests = AccountThrottle("reset-requests")
public_offer_limiter = RateLimiter(60, 300, "public-offer")
