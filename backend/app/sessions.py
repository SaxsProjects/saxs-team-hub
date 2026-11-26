"""Sign-in sessions that stay alive while someone is working.

The web app holds a short access pass (a JWT, `access_token_minutes`) in memory and renews it in the
background with an HttpOnly cookie that scripts cannot read. A sign-in ends:

- after `session_idle_minutes` without a renewal (the app only renews while the person is active),
- `session_max_hours` after signing in (`admin_session_max_hours` for the founder), whatever happens,
- on sign-out, a password change or reset, or when the account is switched off (`sessions_valid_after`),
- when an already-replaced renewal token is presented again, which means it was copied.

The cookie is SameSite=Strict, host-only on the API host, and the renew/sign-out endpoints also check
the Origin header, so another website cannot use it.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .models import SignInSession, User
from .security import create_access_token, hash_token, new_token
from .services import audit


def _now() -> datetime:
    return datetime.now(UTC)


def _set_cookie(response: Response, token: str, expires_at: datetime) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max(0, int((expires_at - _now()).total_seconds())),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict"
    )


def check_origin(request: Request) -> None:
    """Cookie-authenticated requests must come from the Team Hub app itself."""
    if request.headers.get("origin", "").rstrip("/") not in get_settings().cors_origin_list:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request not allowed from this site")


def start_session(db: Session, user: User, request: Request, response: Response) -> tuple[str, int]:
    """Create a sign-in session, set its renewal cookie and return a fresh access token."""
    settings = get_settings()
    now = _now()
    hours = settings.admin_session_max_hours if user.role == "admin" else settings.session_max_hours
    token = new_token()
    session = SignInSession(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(hours=hours),
        user_agent=(request.headers.get("user-agent") or "")[:200] or None,
    )
    db.add(session)
    _set_cookie(response, token, session.expires_at)
    return create_access_token(user.id, user.role)


def _end(session: SignInSession, reason: str) -> None:
    if session.ended_at is None:
        session.ended_at = _now()
        session.ended_reason = reason


def _why_invalid(session: SignInSession, user: User | None, now: datetime) -> str | None:
    settings = get_settings()
    if session.ended_at is not None:
        return session.ended_reason or "ended"
    if not user or not user.is_active:
        return "account_inactive"
    if user.sessions_valid_after and session.created_at < user.sessions_valid_after:
        return "signed_out_everywhere"
    if now >= session.expires_at:
        return "max_age"
    if now - session.last_used_at > timedelta(minutes=settings.session_idle_minutes):
        return "idle"
    return None


def _session_ended() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Your sign-in has ended. Please sign in again.")


def renew_session(db: Session, request: Request, response: Response) -> tuple[str, int]:
    """Swap the renewal cookie for a new one and return a fresh access token, or raise 401."""
    settings = get_settings()
    check_origin(request)
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        raise _session_ended()
    digest = hash_token(raw)
    now = _now()

    session = db.scalar(select(SignInSession).where(SignInSession.token_hash == digest))
    if session is None:
        earlier = db.scalar(select(SignInSession).where(SignInSession.previous_hash == digest))
        if earlier is None:
            clear_cookie(response)
            raise _session_ended()
        grace = timedelta(seconds=settings.session_renew_grace_seconds)
        user = db.get(User, earlier.user_id)
        if earlier.renewed_at and now - earlier.renewed_at <= grace and _why_invalid(earlier, user, now) is None:
            # Another tab renewed a moment ago and the browser already holds the new cookie.
            return create_access_token(user.id, user.role)
        # An old token came back after it was replaced: someone copied it. End the session.
        _end(earlier, "token_reused")
        audit(db, user.email if user else "unknown", "auth.session_token_reused", "user", earlier.user_id)
        db.commit()
        clear_cookie(response)
        raise _session_ended()

    user = db.get(User, session.user_id)
    reason = _why_invalid(session, user, now)
    if reason:
        _end(session, reason)
        db.commit()
        clear_cookie(response)
        raise _session_ended()

    token = new_token()
    rotated = db.execute(
        update(SignInSession)
        .where(SignInSession.id == session.id, SignInSession.token_hash == digest)
        .values(previous_hash=digest, token_hash=hash_token(token), renewed_at=now, last_used_at=now)
    ).rowcount
    db.commit()
    if rotated != 1:
        # A simultaneous request from another tab rotated it first; that tab's cookie wins.
        return create_access_token(user.id, user.role)
    _set_cookie(response, token, session.expires_at)
    return create_access_token(user.id, user.role)


def end_session(db: Session, request: Request, response: Response) -> None:
    """Sign out this browser: end its session (if the cookie is present) and remove the cookie."""
    check_origin(request)
    raw = request.cookies.get(get_settings().session_cookie_name)
    if raw:
        session = db.scalar(select(SignInSession).where(SignInSession.token_hash == hash_token(raw)))
        if session:
            _end(session, "signed_out")
            db.commit()
    clear_cookie(response)
