"""Unlocking a trusted device: passkey (Face ID, fingerprint, Windows Hello) or password, no two-factor.

See app/devices.py for what makes a device trusted and when trust ends.
"""

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .. import devices
from ..config import get_settings
from ..db import get_db
from ..deps import account_failures, current_user, login_limiter, totp_failures
from ..models import Passkey, TrustedDevice, User, WebAuthnChallenge
from ..schemas import TokenOut
from ..security import verify_password
from ..services import audit
from ..sessions import check_origin, start_session

router = APIRouter(prefix="/api/auth", tags=["auth"])

CHALLENGE_MINUTES = 5


class DeviceOut(BaseModel):
    """Who this device belongs to, for the "Welcome back" screen."""

    email: str
    full_name: str | None
    device_name: str
    passkey: bool


class TrustedDeviceOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    last_used_at: datetime
    passkey: bool
    this_device: bool


class UnlockIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class PasskeyOptionsOut(BaseModel):
    challenge_id: int
    options: dict


class PasskeyIn(BaseModel):
    challenge_id: int
    credential: dict


def _device_or_401(db: Session, request: Request) -> TrustedDevice:
    check_origin(request)
    device = devices.current_device(db, request)
    if device is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "This device is not trusted. Sign in with your password and two-factor code."
        )
    return device


def _my_device(db: Session, request: Request, user: User) -> TrustedDevice:
    """This signed-in person's trusted device. 409, not 401: a 401 would read as "your sign-in ended"."""
    check_origin(request)
    device = devices.current_device(db, request)
    if device is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This device isn't trusted. Sign out, then sign in with “Keep me signed in” ticked."
        )
    if device.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This device is trusted for another account")
    return device


def _untrusted(message: str) -> JSONResponse:
    """A 401 that also removes the device cookie, so the app goes back to the full sign-in."""
    response = JSONResponse({"detail": message}, status_code=status.HTTP_401_UNAUTHORIZED)
    devices.clear_device_cookie(response)
    return response


def _new_challenge(db: Session, device: TrustedDevice, purpose: str, challenge: bytes) -> WebAuthnChallenge:
    row = WebAuthnChallenge(
        device_id=device.id,
        purpose=purpose,
        challenge=challenge,
        expires_at=datetime.now(UTC) + timedelta(minutes=CHALLENGE_MINUTES),
    )
    db.add(row)
    db.flush()
    return row


def _use_challenge(db: Session, device: TrustedDevice, purpose: str, challenge_id: int) -> bytes:
    """Consume a challenge exactly once; a second use, another device's or an expired one is refused."""
    now = datetime.now(UTC)
    row = db.get(WebAuthnChallenge, challenge_id)
    if not row or row.device_id != device.id or row.purpose != purpose or row.used_at or row.expires_at < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This request has expired. Please try again.")
    used = db.execute(
        update(WebAuthnChallenge).where(WebAuthnChallenge.id == row.id, WebAuthnChallenge.used_at.is_(None)).values(used_at=now)
    ).rowcount
    if used != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This request has expired. Please try again.")
    return row.challenge


def _unlocked(db: Session, user: User, device: TrustedDevice, method: str, request: Request, response: Response) -> TokenOut:
    devices.touch(device, response, request)
    user.last_login_at = datetime.now(UTC)
    audit(db, user.email, "auth.unlock", "user", user.id, after={"device": device.name, "method": method})
    token, expires_in = start_session(db, user, request, response)
    db.commit()
    return TokenOut(access_token=token, expires_in=expires_in)


@router.get("/device", response_model=DeviceOut)
def this_device(request: Request, db: Session = Depends(get_db)):
    """Whose trusted device this is. 401 when it isn't trusted (then the app shows the normal sign-in)."""
    device = _device_or_401(db, request)
    user = db.get(User, device.user_id)
    return DeviceOut(
        email=user.email,
        full_name=user.person.full_name if user.person else None,
        device_name=device.name,
        passkey=bool(device.passkeys),
    )


@router.post("/unlock", response_model=TokenOut, dependencies=[Depends(login_limiter)])
def unlock_with_password(body: UnlockIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Unlock a trusted device with the password alone."""
    settings = get_settings()
    device = _device_or_401(db, request)
    user = db.get(User, device.user_id)
    window = settings.login_lockout_minutes * 60
    if totp_failures.blocked(user.email, settings.totp_failures_per_account, window) or not account_failures.try_reserve(
        user.email, settings.login_failures_per_account, window
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed sign-ins for this account. Try again in {settings.login_lockout_minutes} minutes.",
        )
    if not verify_password(user.password_hash, body.password):
        device.failed_unlocks += 1
        if device.failed_unlocks >= settings.device_unlock_failures:
            devices.revoke(device, "too_many_passwords")
            audit(
                db,
                user.email,
                "auth.device_untrusted",
                "user",
                user.id,
                after={"device": device.name, "reason": "too_many_passwords"},
            )
            db.commit()
            return _untrusted("Too many wrong passwords on this device. Sign in again with your password and two-factor code.")
        db.commit()
        left = settings.device_unlock_failures - device.failed_unlocks
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"Wrong password. {left} more {'try' if left == 1 else 'tries'} on this device."
        )
    account_failures.refund(user.email)
    return _unlocked(db, user, device, "password", request, response)


@router.post("/unlock/passkey/options", response_model=PasskeyOptionsOut, dependencies=[Depends(login_limiter)])
def unlock_passkey_options(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    device = _device_or_401(db, request)
    if not device.passkeys:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No passkey on this device yet")
    options = generate_authentication_options(
        rp_id=settings.passkey_rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=p.credential_id) for p in device.passkeys],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    row = _new_challenge(db, device, "unlock", options.challenge)
    db.commit()
    return PasskeyOptionsOut(challenge_id=row.id, options=json.loads(options_to_json(options)))


@router.post("/unlock/passkey", response_model=TokenOut, dependencies=[Depends(login_limiter)])
def unlock_with_passkey(body: PasskeyIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Unlock a trusted device with its passkey (the device checks the face, fingerprint or PIN)."""
    settings = get_settings()
    device = _device_or_401(db, request)
    challenge = _use_challenge(db, device, "unlock", body.challenge_id)
    try:
        raw_id = base64url_to_bytes(str(body.credential.get("rawId") or body.credential.get("id") or ""))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That passkey wasn't recognised") from exc
    passkey = next((p for p in device.passkeys if p.credential_id == raw_id), None)
    if passkey is None:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That passkey wasn't recognised")
    try:
        verified = verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.passkey_rp_id,
            expected_origin=settings.passkey_origins,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except InvalidAuthenticationResponse as exc:
        db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That passkey couldn't be checked. Try again or use your password."
        ) from exc
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = datetime.now(UTC)
    return _unlocked(db, db.get(User, device.user_id), device, "passkey", request, response)


@router.post("/passkeys/options", response_model=PasskeyOptionsOut)
def passkey_register_options(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Start adding a passkey to this (trusted) device."""
    settings = get_settings()
    device = _my_device(db, request, user)
    options = generate_registration_options(
        rp_id=settings.passkey_rp_id,
        rp_name=f"{settings.company_name} Team Hub",
        user_id=f"teamhub-user-{user.id}".encode(),
        user_name=user.email,
        user_display_name=(user.person.full_name if user.person else None) or user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=p.credential_id) for p in device.passkeys],
    )
    row = _new_challenge(db, device, "register", options.challenge)
    db.commit()
    return PasskeyOptionsOut(challenge_id=row.id, options=json.loads(options_to_json(options)))


@router.post("/passkeys", status_code=204)
def passkey_register(body: PasskeyIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    device = _my_device(db, request, user)
    challenge = _use_challenge(db, device, "register", body.challenge_id)
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.passkey_rp_id,
            expected_origin=settings.passkey_origins,
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as exc:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The passkey couldn't be set up. Please try again.") from exc
    if db.scalar(select(Passkey).where(Passkey.credential_id == verified.credential_id)):
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "This passkey is already set up")
    db.add(
        Passkey(
            user_id=user.id,
            device_id=device.id,
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
        )
    )
    audit(db, user.email, "auth.passkey_added", "user", user.id, after={"device": device.name})
    db.commit()


@router.get("/devices", response_model=list[TrustedDeviceOut])
def list_devices(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """This person's trusted devices, newest use first."""
    here = devices.current_device(db, request)
    rows = db.scalars(
        select(TrustedDevice)
        .where(TrustedDevice.user_id == user.id, TrustedDevice.revoked_at.is_(None))
        .order_by(TrustedDevice.last_used_at.desc())
    ).all()
    return [
        TrustedDeviceOut(
            id=d.id,
            name=d.name,
            created_at=d.created_at,
            last_used_at=d.last_used_at,
            passkey=bool(d.passkeys),
            this_device=here is not None and here.id == d.id,
        )
        for d in rows
        if devices.is_valid(d, user)
    ]


@router.delete("/devices/{device_id}", status_code=204)
def remove_device(device_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Stop trusting a device. It will need the password and two-factor code again."""
    device = db.get(TrustedDevice, device_id)
    if not device or device.user_id != user.id or device.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    devices.revoke(device, "removed")
    audit(db, user.email, "auth.device_removed", "user", user.id, after={"device": device.name})
    db.commit()
    response = Response(status_code=204)
    here = request.cookies.get(get_settings().device_cookie_name)
    if here and devices.current_device(db, request) is None:
        devices.clear_device_cookie(response)
    return response


@router.post("/forget-device", status_code=204)
def forget_this_device(request: Request, db: Session = Depends(get_db)):
    """ "Use another account": stop trusting this device and remove its cookie."""
    check_origin(request)
    device = devices.current_device(db, request)
    if device is not None:
        user = db.get(User, device.user_id)
        devices.revoke(device, "forgotten")
        audit(db, user.email, "auth.device_removed", "user", user.id, after={"device": device.name})
        db.commit()
    response = Response(status_code=204)
    devices.clear_device_cookie(response)
    return response
