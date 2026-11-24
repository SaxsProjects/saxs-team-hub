import threading
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import (
    account_failures,
    client_ip,
    current_user,
    login_failures,
    login_limiter,
    rate_key_ip,
    require_admin_any,
    reset_requests,
    totp_failures,
)
from ..emailer import OutgoingEmail, send_email
from ..models import ActionToken, User
from ..schemas import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    MeOut,
    SetPasswordIn,
    TokenOut,
    TotpCodeIn,
    TotpSetupOut,
)
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
from ..services import audit, issue_action_token, link, revoke_sessions

router = APIRouter(prefix="/api/auth", tags=["auth"])


LOCKED_HINT = (
    "Too many failed sign-ins for this account. Try again in {minutes} minutes. "
    "If two-factor authentication is on, you can sign in now by entering your password and code together."
)


def _send_totp_alert(to: str) -> None:
    settings = get_settings()
    msg = OutgoingEmail(
        to=to,
        subject=f"Security alert for your {settings.company_name} Team Hub account",
        text=(
            "Someone entered your correct password but wrong two-factor codes many times, so "
            f"sign-in to your account is blocked for {settings.login_lockout_minutes} minutes.\n\n"
            "If this wasn't you, your password is known to someone else. Change it as soon as "
            f"the block ends: {link('/forgot-password')}"
        ),
    )
    # Off the request thread: SMTP can be slow, and background tasks do not run when a request ends in an
    # error, as this one does. send_email never raises.
    threading.Thread(target=send_email, args=(msg,), daemon=True).start()


@router.post("/login", response_model=TokenOut, dependencies=[Depends(login_limiter)])
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    """Sign in.

    Failure limits that cannot be dodged by changing IP address:
    - account + IP: after `login_failures_per_account_ip` failures that IP is locked out of the account.
      An attacker only locks themselves out, not the owner.
    - account (all IPs): after `login_failures_per_account` failures only a correct password AND
      two-factor code can sign in. Guessing both is infeasible, so the owner of a 2FA account can still
      get in. Accounts without 2FA wait for the lock to expire.
    - wrong two-factor codes (all IPs): after `totp_failures_per_account` every sign-in is refused until
      the lock expires, and the owner is emailed, because whoever is guessing already has the password.

    Each attempt reserves its slot in the counters atomically before the slow checks (password hashing,
    database), and successful steps give the slot back. Parallel requests therefore cannot slip past a
    limit, and no lock is held while anything slow runs. Locked responses are identical for every
    account, existing or not, so they reveal nothing.
    """
    settings = get_settings()
    email = body.email.lower()
    window = settings.login_lockout_minutes * 60
    pair = f"{email}|{rate_key_ip(client_ip(request))}"
    totp_limit = settings.totp_failures_per_account

    def locked(scope: str) -> HTTPException:
        audit(db, "anonymous", "auth.login_locked", "user", None, after={"scope": scope})
        db.commit()
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, LOCKED_HINT.format(minutes=settings.login_lockout_minutes))

    if totp_failures.blocked(email, totp_limit, window):
        raise locked("totp")
    if not login_failures.try_reserve(pair, settings.login_failures_per_account_ip, window):
        raise locked("account_ip")
    account_reserved = bool(account_failures.try_reserve(email, settings.login_failures_per_account, window))

    user = db.scalar(select(User).where(User.email == email))
    password_ok = bool(user and user.is_active and verify_password(user.password_hash, body.password))
    if not user:
        burn_password_check(body.password)

    def check_code() -> bool | None:
        """Verify the two-factor code, counted against the account-wide ceiling. None = ceiling reached."""
        n = totp_failures.try_reserve(email, totp_limit, window)
        if not n:
            return None
        if verify_totp(decrypt_text(user.totp_secret_enc), body.totp_code):
            totp_failures.refund(email)
            return True
        if n == totp_limit:  # exactly one request reaches the limit, so the alert goes out once
            audit(db, "anonymous", "auth.totp_lock", "user", user.id)
            _send_totp_alert(user.email)
        return False

    if not account_reserved:
        # Account-wide lock: only password + correct two-factor code gets through; every failure looks the same.
        if not (password_ok and user.totp_enabled and body.totp_code and check_code()):
            raise locked("account")
    else:
        if not password_ok:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")  # slots stay counted
        if user.totp_enabled:
            if not body.totp_code:
                # Not a failure: the client asks for the code next. Give both slots back.
                login_failures.refund(pair)
                account_failures.refund(email)
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "totp_required")
            ok = check_code()
            if ok is None:
                raise locked("totp")
            if not ok:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong two-factor code")
        account_failures.refund(email)
    login_failures.reset(pair)
    user.last_login_at = datetime.now(UTC)
    audit(db, user.email, "auth.login", "user", user.id)
    db.commit()
    token, expires_in = create_access_token(user.id, user.role)
    return TokenOut(access_token=token, expires_in=expires_in)


PASSWORD_TOKEN_PURPOSES = ("set_password", "reset_password")
RESET_LINK_HOURS = 1


def apply_password_token(db: Session, token: str, password: str) -> User:
    """Use a set-password or reset-password link. Raises 400 if the link is invalid, used or expired."""
    record = db.scalar(select(ActionToken).where(ActionToken.token_hash == hash_token(token)))
    now = datetime.now(UTC)
    if not record or record.purpose not in PASSWORD_TOKEN_PURPOSES or record.used_at or record.expires_at < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired. Ask for a new one.")
    user = db.get(User, record.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is not active.")
    user.password_hash = hash_password(password)
    record.used_at = now
    revoke_sessions(user)  # sign out everywhere after a password change
    audit(db, user.email, f"auth.{record.purpose}", "user", user.id)
    db.commit()
    return user


@router.post("/set-password", status_code=204)
def set_password(body: SetPasswordIn, db: Session = Depends(get_db)):
    """Set a password from an invite link or a password-reset link."""
    apply_password_token(db, body.token, body.password)


@router.post("/forgot-password", status_code=204, dependencies=[Depends(login_limiter)])
def forgot_password(body: ForgotPasswordIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Email a 1-hour reset link. Always returns 204, so it can't be used to discover accounts."""
    email = body.email.lower()
    # At most a few reset emails per account per hour, whatever IP they come from. Still answers 204.
    if reset_requests.blocked(email, get_settings().reset_emails_per_account_per_hour, 3600):
        burn_password_check(body.email)
        return
    reset_requests.hit(email, 3600, protect_at=get_settings().reset_emails_per_account_per_hour)
    user = db.scalar(select(User).where(User.email == email))
    if user and user.is_active:
        token = issue_action_token(db, user, "reset_password", timedelta(hours=RESET_LINK_HOURS))
        audit(db, user.email, "auth.reset_requested", "user", user.id)
        db.commit()
        settings = get_settings()
        background.add_task(
            send_email,
            OutgoingEmail(
                to=user.email,
                subject=f"Reset your {settings.company_name} Team Hub password",
                text=(
                    "Someone asked to reset the password for this Team Hub account. "
                    f"If it was you, choose a new password here (valid for {RESET_LINK_HOURS} hour):\n\n"
                    f"{link('/reset-password?token=' + token)}\n\n"
                    "If it wasn't you, ignore this email: your password stays the same."
                ),
            ),
        )
    else:
        burn_password_check(body.email)  # similar timing whether or not the account exists


@router.post("/change-password", response_model=TokenOut)
def change_password(body: ChangePasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Change password. Signs out every other session and returns a fresh token for this one."""
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    revoke_sessions(user)
    audit(db, user.email, "auth.change_password", "user", user.id)
    db.commit()
    token, expires_in = create_access_token(user.id, user.role)
    return TokenOut(access_token=token, expires_in=expires_in)


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
