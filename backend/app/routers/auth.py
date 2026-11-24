from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user, login_limiter, require_admin_any
from ..models import ActionToken, User
from ..schemas import ChangePasswordIn, LoginIn, MeOut, SetPasswordIn, TokenOut, TotpCodeIn, TotpSetupOut
from ..security import (
    burn_password_check,
    create_access_token,
    decrypt_text,
    encrypt_text,
    hash_password,
    hash_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from ..services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut, dependencies=[Depends(login_limiter)])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user:
        burn_password_check(body.password)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    if not user.is_active or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    if user.totp_enabled:
        if not body.totp_code:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "totp_required")
        if not verify_totp(decrypt_text(user.totp_secret_enc), body.totp_code):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong two-factor code")
    user.last_login_at = datetime.now(UTC)
    audit(db, user.email, "auth.login", "user", user.id)
    db.commit()
    token, expires_in = create_access_token(user.id, user.role)
    return TokenOut(access_token=token, expires_in=expires_in)


@router.post("/set-password", status_code=204)
def set_password(body: SetPasswordIn, db: Session = Depends(get_db)):
    record = db.scalar(select(ActionToken).where(ActionToken.token_hash == hash_token(body.token)))
    now = datetime.now(UTC)
    if not record or record.purpose != "set_password" or record.used_at or record.expires_at < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired. Ask for a new one.")
    user = db.get(User, record.user_id)
    user.password_hash = hash_password(body.password)
    record.used_at = now
    audit(db, user.email, "auth.set_password", "user", user.id)
    db.commit()


@router.post("/change-password", status_code=204)
def change_password(body: ChangePasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    audit(db, user.email, "auth.change_password", "user", user.id)
    db.commit()


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut(
        id=user.id,
        email=user.email,
        role=user.role,
        person_id=user.person_id,
        totp_enabled=user.totp_enabled,
        two_factor_required=user.role == "admin" and get_settings().admin_2fa_required,
    )


@router.post("/2fa/setup", response_model=TotpSetupOut)
def totp_setup(user: User = Depends(require_admin_any), db: Session = Depends(get_db)):
    """Start two-factor setup: scan the URI with an authenticator app, then call /2fa/enable."""
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor is already on")
    secret = new_totp_secret()
    user.totp_secret_enc = encrypt_text(secret)
    db.commit()
    return TotpSetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/2fa/enable", status_code=204)
def totp_enable(body: TotpCodeIn, user: User = Depends(require_admin_any), db: Session = Depends(get_db)):
    if not verify_totp(decrypt_text(user.totp_secret_enc), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Wrong code. Check your phone's clock and try again.")
    user.totp_enabled = True
    audit(db, user.email, "auth.2fa_enabled", "user", user.id)
    db.commit()
