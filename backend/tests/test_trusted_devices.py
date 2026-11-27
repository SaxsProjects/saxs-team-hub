"""Trusted devices: unlock with a passkey or the password alone; two-factor only on new devices and resets."""

import base64
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta

import cbor2
import pyotp
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app import emailer
from app.config import get_settings
from app.db import SessionLocal
from app.models import TrustedDevice, User
from app.security import hash_password

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD

ORIGIN = {"Origin": "http://localhost:5173"}  # the default CORS_ORIGINS in tests
RP_ID = "localhost"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FakeAuthenticator:
    """A software passkey that behaves like a phone's fingerprint sensor (user verified)."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.count = 0

    def _client_data(self, kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def register(self, options: dict, origin: str = ORIGIN["Origin"]) -> dict:
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        auth_data = (
            hashlib.sha256(options["rp"]["id"].encode()).digest()
            + bytes([0x45])  # user present + user verified + attested credential data
            + (0).to_bytes(4, "big")
            + bytes(16)
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + cose
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"], origin)),
                "attestationObject": b64(attestation),
            },
        }

    def sign(self, options: dict, origin: str = ORIGIN["Origin"], verified: bool = True) -> dict:
        self.count += 1
        auth_data = (
            hashlib.sha256(options["rpId"].encode()).digest()
            + bytes([0x05 if verified else 0x01])
            + self.count.to_bytes(4, "big")
        )
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {"clientDataJSON": b64(client_data), "authenticatorData": b64(auth_data), "signature": b64(signature)},
        }


def make_admin():
    with SessionLocal() as db:
        db.add(User(email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD), role="admin"))
        db.commit()


def login(client, trust=True, **extra):
    return client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "trust_device": trust, **extra},
        headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/140.0"},
    )


def bearer(r) -> dict:
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wait_for_mail(text: str) -> bool:
    for _ in range(50):
        if any(text in m.subject for m in emailer.outbox):
            return True
        time.sleep(0.02)
    return False


def add_passkey(client, auth_headers) -> FakeAuthenticator:
    authenticator = FakeAuthenticator()
    r = client.post("/api/auth/passkeys/options", headers={**ORIGIN, **auth_headers})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["options"]["authenticatorSelection"]["userVerification"] == "required"
    r = client.post(
        "/api/auth/passkeys",
        headers={**ORIGIN, **auth_headers},
        json={"challenge_id": body["challenge_id"], "credential": authenticator.register(body["options"])},
    )
    assert r.status_code == 204, r.text
    return authenticator


def unlock_with(client, authenticator, **kw):
    r = client.post("/api/auth/unlock/passkey/options", headers=ORIGIN)
    assert r.status_code == 200, r.text
    body = r.json()
    return client.post(
        "/api/auth/unlock/passkey",
        headers=ORIGIN,
        json={"challenge_id": body["challenge_id"], "credential": authenticator.sign(body["options"], **kw)},
    )


def test_trusted_device_remembers_the_account_and_unlocks_with_the_password(client):
    make_admin()
    assert client.get("/api/auth/device", headers=ORIGIN).status_code == 401  # not trusted yet
    r = login(client)
    assert r.status_code == 200 and r.json()["device_trusted"] is True
    assert wait_for_mail("New trusted device")

    me = client.get("/api/auth/device", headers=ORIGIN).json()
    assert me["email"] == ADMIN_EMAIL and me["device_name"] == "Chrome on Android" and me["passkey"] is False

    client.post("/api/auth/logout", headers=ORIGIN)  # the sign-in ends, the device stays trusted
    r = client.post("/api/auth/unlock", headers=ORIGIN, json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=bearer(r)).json()["email"] == ADMIN_EMAIL


def test_unlock_skips_two_factor_but_a_new_device_still_needs_it(client):
    make_admin()
    r = login(client, trust=False)
    secret = client.post("/api/auth/2fa/setup", headers=bearer(r)).json()["secret"]
    assert client.post("/api/auth/2fa/enable", headers=bearer(r), json={"code": pyotp.TOTP(secret).now()}).status_code == 204

    assert login(client).json()["detail"] == "totp_required"  # a new device: password and code
    assert login(client, totp_code=pyotp.TOTP(secret).now()).status_code == 200

    r = client.post("/api/auth/unlock", headers=ORIGIN, json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text  # no code on the trusted device

    other = type(client)(client.app)  # another phone, no device cookie
    assert other.post("/api/auth/unlock", headers=ORIGIN, json={"password": ADMIN_PASSWORD}).status_code == 401


def test_wrong_passwords_stop_trusting_the_device(client, monkeypatch):
    make_admin()
    monkeypatch.setattr(get_settings(), "device_unlock_failures", 3)
    login(client)
    for left in (2, 1):
        r = client.post("/api/auth/unlock", headers=ORIGIN, json={"password": "wrong-password"})
        assert r.status_code == 401 and f"{left} more" in r.json()["detail"]
    r = client.post("/api/auth/unlock", headers=ORIGIN, json={"password": "wrong-password"})
    assert r.status_code == 401 and "Sign in again" in r.json()["detail"]
    # Even the right password no longer works here: back to the full sign-in.
    assert client.post("/api/auth/unlock", headers=ORIGIN, json={"password": ADMIN_PASSWORD}).status_code == 401


def test_passkey_unlock(client):
    make_admin()
    authenticator = add_passkey(client, bearer(login(client)))
    assert client.get("/api/auth/device", headers=ORIGIN).json()["passkey"] is True

    client.post("/api/auth/logout", headers=ORIGIN)
    r = unlock_with(client, authenticator)
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=bearer(r)).status_code == 200
    assert unlock_with(client, authenticator).status_code == 200  # again, with a higher counter


def test_passkey_needs_fingerprint_or_face_and_the_right_site(client):
    make_admin()
    authenticator = add_passkey(client, bearer(login(client)))
    assert unlock_with(client, authenticator, verified=False).status_code == 400  # touched, not verified
    assert unlock_with(client, authenticator, origin="https://evil.example").status_code == 400
    assert unlock_with(client, FakeAuthenticator()).status_code == 400  # a passkey not on this device


def test_passkey_challenge_is_single_use(client):
    make_admin()
    authenticator = add_passkey(client, bearer(login(client)))
    body = client.post("/api/auth/unlock/passkey/options", headers=ORIGIN).json()
    signed = authenticator.sign(body["options"])
    assert (
        client.post(
            "/api/auth/unlock/passkey", headers=ORIGIN, json={"challenge_id": body["challenge_id"], "credential": signed}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/unlock/passkey", headers=ORIGIN, json={"challenge_id": body["challenge_id"], "credential": signed}
        ).status_code
        == 400
    )


def test_android_app_origin_is_accepted():
    origins = get_settings().passkey_origins
    cert = bytes.fromhex(get_settings().android_signing_cert_sha256)
    assert f"android:apk-key-hash:{b64(cert)}" in origins


def test_devices_list_and_remove(client):
    make_admin()
    headers = bearer(login(client))
    devices = client.get("/api/auth/devices", headers=headers).json()
    assert len(devices) == 1 and devices[0]["this_device"] is True
    r = client.delete(f"/api/auth/devices/{devices[0]['id']}", headers={**ORIGIN, **headers})
    assert r.status_code == 204
    assert client.get("/api/auth/devices", headers=headers).json() == []
    assert client.post("/api/auth/unlock", headers=ORIGIN, json={"password": ADMIN_PASSWORD}).status_code == 401


def test_other_people_cannot_remove_my_device(client, team):
    _, member = team  # the founder account already exists
    login(client)
    with SessionLocal() as db:
        device_id = db.query(TrustedDevice).one().id
    assert client.delete(f"/api/auth/devices/{device_id}", headers={**ORIGIN, **member}).status_code == 404


def test_trust_ends_after_90_days_unused(client):
    make_admin()
    login(client)
    with SessionLocal() as db:
        device = db.query(TrustedDevice).one()
        device.last_used_at = datetime.now(UTC) - timedelta(days=91)
        db.commit()
    assert client.post("/api/auth/unlock", headers=ORIGIN, json={"password": ADMIN_PASSWORD}).status_code == 401
    with SessionLocal() as db:
        assert db.query(TrustedDevice).one().revoked_reason == "expired"


def test_unlock_needs_the_app_origin(client):
    make_admin()
    login(client)
    assert client.post("/api/auth/unlock", json={"password": ADMIN_PASSWORD}).status_code == 403


def test_forget_device_for_another_account(client):
    make_admin()
    login(client)
    assert client.post("/api/auth/forget-device", headers=ORIGIN).status_code == 204
    assert client.get("/api/auth/device", headers=ORIGIN).status_code == 401


def test_reset_needs_two_factor_code_and_untrusts_every_device(client):
    make_admin()
    r = login(client, trust=False)
    secret = client.post("/api/auth/2fa/setup", headers=bearer(r)).json()["secret"]
    client.post("/api/auth/2fa/enable", headers=bearer(r), json={"code": pyotp.TOTP(secret).now()})
    assert login(client, totp_code=pyotp.TOTP(secret).now()).status_code == 200  # this device is trusted

    client.post("/api/auth/forgot-password", json={"email": ADMIN_EMAIL})
    mail = [m for m in emailer.outbox if "reset-password?token=" in m.text][-1]
    token = mail.text.split("reset-password?token=")[1].split()[0]

    page = client.get(f"/reset-password?token={token}")
    assert 'name="totp_code"' in page.text  # the reset page asks for the code

    r = client.post("/api/auth/set-password", json={"token": token, "password": "brand-new-password-1"})
    assert r.status_code == 400 and "6-digit" in r.json()["detail"]
    r = client.post("/api/auth/set-password", json={"token": token, "password": "brand-new-password-1", "totp_code": "000000"})
    assert r.status_code == 400 and "wrong" in r.json()["detail"]
    r = client.post(
        "/reset-password",
        data={
            "token": token,
            "password": "brand-new-password-1",
            "confirm": "brand-new-password-1",
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )
    assert r.status_code == 200 and "Password saved" in r.text

    # The trusted device must sign in fully again.
    assert client.post("/api/auth/unlock", headers=ORIGIN, json={"password": "brand-new-password-1"}).status_code == 401


def test_reset_without_two_factor_still_works_and_untrusts(client):
    make_admin()
    login(client)
    client.post("/api/auth/forgot-password", json={"email": ADMIN_EMAIL})
    mail = [m for m in emailer.outbox if "reset-password?token=" in m.text][-1]
    token = mail.text.split("reset-password?token=")[1].split()[0]
    assert 'name="totp_code"' not in client.get(f"/reset-password?token={token}").text
    assert client.post("/api/auth/set-password", json={"token": token, "password": "brand-new-password-1"}).status_code == 204
    assert client.post("/api/auth/unlock", headers=ORIGIN, json={"password": "brand-new-password-1"}).status_code == 401


def test_passkey_setup_on_an_untrusted_device_is_not_a_sign_out(client):
    make_admin()
    headers = bearer(login(client, trust=False))
    r = client.post("/api/auth/passkeys/options", headers={**ORIGIN, **headers})
    assert r.status_code == 409  # a 401 would make the app sign the person out
    assert client.get("/api/auth/me", headers=headers).status_code == 200
