"""Faked X-Forwarded-For headers must not get around rate limits, and accounts lock after repeated failures."""

import pyotp
import pytest
from starlette.requests import Request

from app import emailer
from app.config import get_settings
from app.deps import client_ip, login_limiter

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def make_request(xff: str | None, peer: str = "10.0.0.5") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": (peer, 1234)})


@pytest.fixture
def hops(monkeypatch):
    def set_hops(n: int, trust: bool = True):
        monkeypatch.setattr(get_settings(), "trusted_proxy_hops", n)
        monkeypatch.setattr(get_settings(), "trust_proxy", trust)

    return set_hops


def test_client_ip_uses_the_entry_added_by_our_proxy(hops):
    hops(1)
    # The caller wrote "1.2.3.4"; our proxy appended the real address it saw.
    assert client_ip(make_request("1.2.3.4, 203.0.113.9")) == "203.0.113.9"
    assert client_ip(make_request("203.0.113.9")) == "203.0.113.9"
    assert client_ip(make_request("2001:db8::1")) == "2001:db8::1"
    # Missing or garbage values fall back to the connecting address.
    assert client_ip(make_request(None)) == "10.0.0.5"
    assert client_ip(make_request("not-an-ip")) == "10.0.0.5"
    assert client_ip(make_request(" , ")) == "10.0.0.5"

    hops(2)
    assert client_ip(make_request("1.2.3.4, 203.0.113.9, 198.51.100.1")) == "203.0.113.9"
    assert client_ip(make_request("203.0.113.9")) == "10.0.0.5"  # fewer entries than proxies: untrusted

    hops(1, trust=False)
    assert client_ip(make_request("1.2.3.4, 203.0.113.9")) == "10.0.0.5"


@pytest.fixture
def ip_limit_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "development")  # the IP limiter is off in tests
    login_limiter.hits.clear()
    yield
    login_limiter.hits.clear()


def test_faked_forwarded_for_cannot_bypass_the_ip_limit(client, admin, ip_limit_on):
    codes = []
    for i in range(12):
        r = client.post(
            "/api/auth/login",
            json={"email": f"nobody{i}@example.com", "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.9.{i}.{i}, 198.51.100.7"},  # a new fake IP every time
        )
        codes.append(r.status_code)
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]


def login(client, password, ip, email=ADMIN_EMAIL, code=None):
    body = {"email": email, "password": password}
    if code:
        body["totp_code"] = code
    return client.post("/api/auth/login", json=body, headers={"X-Forwarded-For": ip})


def test_one_attacker_ip_only_locks_itself_out(client, admin):
    attacker, owner = "203.0.113.66", "198.51.100.20"
    for i in range(10):
        assert login(client, f"guess-{i}", attacker).status_code == 401
    # The attacker's IP is now locked out of this account, even with the right password...
    assert login(client, ADMIN_PASSWORD, attacker).status_code == 429
    # ...but the owner, signing in from their own connection, is not.
    assert login(client, ADMIN_PASSWORD, owner).status_code == 200


def test_spread_out_guessing_locks_the_account(client, admin):
    for i in range(50):
        assert login(client, f"guess-{i}", f"203.0.113.{i}").status_code == 401
    # Account-wide lock: no 2FA on this account, so even the right password from a new IP waits.
    r = login(client, ADMIN_PASSWORD, "198.51.100.20")
    assert r.status_code == 429 and "minutes" in r.json()["detail"]


def test_owner_with_two_factor_gets_in_during_an_account_lock(client, admin):
    secret = client.post("/api/auth/2fa/setup", headers=admin).json()["secret"]
    assert client.post("/api/auth/2fa/enable", headers=admin, json={"code": pyotp.TOTP(secret).now()}).status_code == 204
    for i in range(50):
        login(client, f"guess-{i}", f"203.0.113.{i}")
    owner = "198.51.100.20"
    # Password alone, or a wrong code, gets the same locked answer as everyone else.
    assert login(client, ADMIN_PASSWORD, owner).status_code == 429
    assert login(client, ADMIN_PASSWORD, owner, code="000000").status_code == 429
    # Password and the right code together still work.
    assert login(client, ADMIN_PASSWORD, owner, code=pyotp.TOTP(secret).now()).status_code == 200


def test_successful_login_resets_the_failure_count(client, admin):
    ip = "198.51.100.20"
    for _ in range(9):
        login(client, "wrong-password", ip)
    assert login(client, ADMIN_PASSWORD, ip).status_code == 200
    for _ in range(9):
        assert login(client, "wrong-password", ip).status_code == 401
    assert login(client, ADMIN_PASSWORD, ip).status_code == 200


def test_unknown_emails_lock_the_same_way(client):
    for _ in range(10):
        assert login(client, "x", "203.0.113.5", email="ghost@example.com").status_code == 401
    assert login(client, "x", "203.0.113.5", email="ghost@example.com").status_code == 429


def test_flooding_with_new_keys_cannot_clear_a_lockout(client, admin, monkeypatch):
    from app import deps

    monkeypatch.setattr(deps, "MAX_TRACKED_KEYS", 50)
    attacker = "203.0.113.66"
    for i in range(10):
        login(client, f"guess-{i}", attacker)
    assert login(client, ADMIN_PASSWORD, attacker).status_code == 429
    # Flood the counters with hundreds of other accounts to try to push the lockout out.
    for i in range(300):
        login(client, "x", attacker, email=f"junk{i}@example.com")
    assert len(deps.login_failures.hits) <= 51
    assert login(client, ADMIN_PASSWORD, attacker).status_code == 429


def test_reset_emails_are_limited_per_account(client, admin):
    emailer.outbox.clear()
    for i in range(6):
        r = client.post("/api/auth/forgot-password", json={"email": ADMIN_EMAIL}, headers={"X-Forwarded-For": f"203.0.113.{i}"})
        assert r.status_code == 204  # same answer every time, so nothing is revealed
    sent = [m for m in emailer.outbox if m.to == ADMIN_EMAIL and "reset-password?token=" in m.text]
    assert len(sent) == 3
