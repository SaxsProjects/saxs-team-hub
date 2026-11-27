"""Trusted devices: stay signed in on your own phone or computer.

After a full sign-in (password and, where it is on, two-factor) a person can trust the device. A random
token goes into an HttpOnly, host-only cookie (only its hash is stored). On that device they unlock with a
passkey (Face ID, fingerprint, Windows Hello) or their password alone; two-factor is not asked again.

Trust ends when the device is removed (Settings > Security), after a password reset, after
`device_trust_days` without use, after `device_unlock_failures` wrong passwords on it, or when the account
is switched off.
"""

import re
import threading
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .emailer import OutgoingEmail, send_email
from .models import TrustedDevice, User
from .security import hash_token, new_token
from .services import audit, link


def _now() -> datetime:
    return datetime.now(UTC)


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.device_cookie_name,
        token,
        max_age=settings.device_trust_days * 86400,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_device_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.device_cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")


def device_name(request: Request, given: str | None = None) -> str:
    """A readable name for the device list, e.g. "Android app" or "Chrome on Windows"."""
    if given and given.strip():
        return re.sub(r"[^\w .,()·'-]", "", given.strip())[:80] or "Device"
    ua = request.headers.get("user-agent", "")
    if "TeamHubDesktop/" in ua:
        return "Team Hub Windows app"
    system = next(
        (
            name
            for pattern, name in (
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Android", "Android"),
                ("Windows", "Windows"),
                ("Mac OS", "Mac"),
                ("Linux", "Linux"),
            )
            if pattern in ua
        ),
        "Unknown system",
    )
    browser = next(
        (
            name
            for pattern, name in (("Edg/", "Edge"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
            if pattern in ua
        ),
        "Browser",
    )
    return f"{browser} on {system}"


def _send_new_device_alert(user: User, name: str) -> None:
    settings = get_settings()
    msg = OutgoingEmail(
        to=user.email,
        subject=f"New trusted device on your {settings.company_name} Team Hub account",
        text=(
            f"{name} is now a trusted device for your Team Hub account. It can be unlocked with a passkey "
            "(Face ID, fingerprint or Windows Hello) or your password, without a two-factor code.\n\n"
            "If this wasn't you, sign in and remove it under Settings > Security, then change your password: "
            f"{link('/forgot-password')}"
        ),
    )
    threading.Thread(target=send_email, args=(msg,), daemon=True).start()


def trust_device(db: Session, user: User, request: Request, response: Response, name: str | None = None) -> TrustedDevice:
    """Trust this device for `user` (replacing any device cookie it already had) and set the cookie."""
    old = current_device(db, request)
    if old is not None:
        revoke(old, "replaced")
    token = new_token()
    device = TrustedDevice(user_id=user.id, token_hash=hash_token(token), name=device_name(request, name), failed_unlocks=0)
    db.add(device)
    db.flush()
    _set_cookie(response, token)
    audit(db, user.email, "auth.device_trusted", "user", user.id, after={"device": device.name})
    _send_new_device_alert(user, device.name)
    return device


def revoke(device: TrustedDevice, reason: str) -> None:
    if device.revoked_at is None:
        device.revoked_at = _now()
        device.revoked_reason = reason


def revoke_all(db: Session, user: User, reason: str) -> int:
    devices = db.scalars(select(TrustedDevice).where(TrustedDevice.user_id == user.id, TrustedDevice.revoked_at.is_(None))).all()
    for d in devices:
        revoke(d, reason)
    return len(devices)


def is_valid(device: TrustedDevice, user: User | None, now: datetime | None = None) -> bool:
    now = now or _now()
    return (
        device.revoked_at is None
        and user is not None
        and user.is_active
        and now - device.last_used_at <= timedelta(days=get_settings().device_trust_days)
    )


def current_device(db: Session, request: Request) -> TrustedDevice | None:
    """The trusted device named by this request's cookie, if it is still trusted."""
    raw = request.cookies.get(get_settings().device_cookie_name)
    if not raw:
        return None
    device = db.scalar(select(TrustedDevice).where(TrustedDevice.token_hash == hash_token(raw)))
    if device is None:
        return None
    user = db.get(User, device.user_id)
    if not is_valid(device, user):
        if device.revoked_at is None:
            revoke(device, "expired" if user and user.is_active else "account_inactive")
            db.commit()
        return None
    return device


def touch(device: TrustedDevice, response: Response, request: Request) -> None:
    """Record a successful unlock and slide the cookie's expiry forward."""
    device.last_used_at = _now()
    device.failed_unlocks = 0
    raw = request.cookies.get(get_settings().device_cookie_name)
    if raw:
        _set_cookie(response, raw)
