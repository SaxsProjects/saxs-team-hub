"""Faked X-Forwarded-For headers must not get around rate limits, and accounts lock after repeated failures."""

import pytest
from starlette.requests import Request

from app import emailer
from app.config import get_settings
from app.db import SessionLocal
from app.deps import client_ip, login_limiter
from app.models import User
from app.security import hash_password

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


def test_account_locks_after_repeated_failures_from_any_ip(client, admin):
    for i in range(10):
        r = client.post(
            "/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": f"guess-{i}"},
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
        )
        assert r.status_code == 401
    # Even the right password is refused while the account is locked.
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 429
    # Other accounts are unaffected.
    with SessionLocal() as db:
        db.add(User(email="other@saxsprojects.co.za", password_hash=hash_password("another-password-1"), role="admin"))
        db.commit()
    assert (
        client.post("/api/auth/login", json={"email": "other@saxsprojects.co.za", "password": "another-password-1"}).status_code
        == 200
    )


def test_successful_login_resets_the_failure_count(client, admin):
    for _ in range(9):
        client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"})
    assert client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 200
    for _ in range(9):
        assert client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 200


def test_unknown_emails_lock_the_same_way(client):
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"}).status_code == 429


def test_reset_emails_are_limited_per_account(client, admin):
    emailer.outbox.clear()
    for i in range(6):
        r = client.post("/api/auth/forgot-password", json={"email": ADMIN_EMAIL}, headers={"X-Forwarded-For": f"203.0.113.{i}"})
        assert r.status_code == 204  # same answer every time, so nothing is revealed
    sent = [m for m in emailer.outbox if m.to == ADMIN_EMAIL and "reset-password?token=" in m.text]
    assert len(sent) == 3
