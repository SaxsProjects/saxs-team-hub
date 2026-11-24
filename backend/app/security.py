"""Passwords, sessions, one-time tokens, field encryption and two-factor codes."""

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_hasher = PasswordHasher()
JWT_ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 10


# ---- Passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# Spend similar time when the account doesn't exist, so login timing doesn't reveal valid emails.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def burn_password_check(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


# ---- Sessions (JWT) --------------------------------------------------------


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        # millisecond issue time, so "sign out everywhere" also catches tokens from the same second
        "iat_ms": int(now.timestamp() * 1000),
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM), expires_in


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---- One-time tokens (offer links, password setup) -------------------------


def new_token() -> str:
    """256-bit random, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---- Field encryption (banking details, ID numbers, TOTP secrets) ----------


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.field_encryption_key
    if not key:
        # Development fallback only; production refuses to start without a real key.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken:
        return None


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_text(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


# ---- Two-factor (TOTP) -----------------------------------------------------


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=f"{get_settings().company_name} Team Hub")


def verify_totp(secret: str | None, code: str | None) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)
