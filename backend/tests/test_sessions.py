"""Sign-ins that stay alive while active: renewal cookie, idle and maximum limits, reuse detection."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import SignInSession, User
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

ORIGIN = {"Origin": "http://localhost:5173"}  # the default CORS_ORIGINS in tests
COOKIE = "teamhub_session"  # outside production the cookie has no __Host- prefix (no HTTPS in tests)


def renew(client, **headers):
    return client.post("/api/auth/refresh", headers={**ORIGIN, **headers})


def sessions():
    with SessionLocal() as db:
        return db.scalars(select(SignInSession).order_by(SignInSession.id)).all()


def shift(**changes):
    with SessionLocal() as db:
        db.execute(update(SignInSession).values(**changes))
        db.commit()


def test_login_sets_a_locked_down_cookie(client, admin):
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    cookie = r.headers["set-cookie"]
    assert f"{COOKIE}=" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "Domain" not in cookie  # host-only
    assert r.json()["expires_in"] == 15 * 60
    s = sessions()[-1]
    assert s.expires_at - s.created_at == timedelta(hours=8)  # founder: 8 hours at most


def test_member_sessions_last_up_to_12_hours(client, team):
    member = sessions()[-1]
    assert member.expires_at - member.created_at == timedelta(hours=12)


def test_renewal_rotates_the_cookie_and_gives_a_working_pass(client, admin):
    old = client.cookies.get(COOKIE)
    r = renew(client)
    assert r.status_code == 200, r.text
    new = client.cookies.get(COOKIE)
    assert new and new != old
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200
    assert renew(client).status_code == 200  # and again with the new cookie


def test_renewal_needs_the_cookie_and_our_own_site(client, admin):
    assert client.post("/api/auth/refresh").status_code == 403  # no Origin
    assert renew(client, Origin="https://evil.example").status_code == 403
    client.cookies.clear()
    assert renew(client).status_code == 401


def test_copied_old_cookie_ends_the_session(client, admin):
    stolen = client.cookies.get(COOKIE)
    assert renew(client).status_code == 200
    shift(renewed_at=datetime.now(UTC) - timedelta(minutes=5))  # past the two-tab grace period
    client.cookies.set(COOKIE, stolen)
    assert renew(client).status_code == 401
    assert sessions()[-1].ended_reason == "token_reused"
    # The legitimate holder is signed out as well, since we can't tell who is who.
    assert renew(client).status_code == 401


def test_two_tabs_renewing_together_both_succeed(client, admin):
    first = client.cookies.get(COOKIE)
    assert renew(client).status_code == 200
    client.cookies.set(COOKIE, first)  # the second tab still sent the old cookie
    assert renew(client).status_code == 200
    assert sessions()[-1].ended_at is None


def test_idle_for_30_minutes_signs_out(client, admin):
    shift(last_used_at=datetime.now(UTC) - timedelta(minutes=31))
    assert renew(client).status_code == 401
    assert sessions()[-1].ended_reason == "idle"


def test_active_use_cannot_pass_the_maximum(client, admin):
    shift(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert renew(client).status_code == 401
    assert sessions()[-1].ended_reason == "max_age"


def test_logout_ends_the_session(client, admin):
    r = client.post("/api/auth/logout", headers=ORIGIN)
    assert r.status_code == 204
    assert sessions()[-1].ended_reason == "signed_out"
    assert renew(client).status_code == 401


def test_logout_checks_the_site(client, admin):
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert sessions()[-1].ended_at is None


def test_password_change_ends_other_sessions_but_keeps_this_one(client, admin):
    other = client.cookies.get(COOKIE)  # e.g. a phone that signed in earlier
    r = client.post(
        "/api/auth/change-password",
        headers=admin,
        json={"current_password": ADMIN_PASSWORD, "new_password": "a-brand-new-password-42"},
    )
    assert r.status_code == 200, r.text
    assert renew(client).status_code == 200  # this browser got a fresh session
    client.cookies.set(COOKIE, other)
    shift(renewed_at=datetime.now(UTC) - timedelta(minutes=5))
    assert renew(client).status_code == 401


def test_switched_off_account_cannot_renew(client, admin):
    with SessionLocal() as db:
        db.execute(update(User).values(is_active=False))
        db.commit()
    assert renew(client).status_code == 401
    assert sessions()[-1].ended_reason == "account_inactive"


def test_simultaneous_renewals_keep_the_session(client, admin, monkeypatch):
    """Two tabs renew with the same cookie at the same moment: the loser must not break the session."""
    from app import sessions as sessions_module
    from app.security import hash_token

    winner = "token-from-the-other-tab"
    real_new_token = sessions_module.new_token

    def other_tab_rotates_first():
        # Runs after this request has validated the row: another request rotates it in between.
        with SessionLocal() as db:
            row = db.scalars(select(SignInSession)).one()
            row.previous_hash, row.token_hash, row.renewed_at = row.token_hash, hash_token(winner), datetime.now(UTC)
            db.commit()
        return real_new_token()

    monkeypatch.setattr(sessions_module, "new_token", other_tab_rotates_first)
    r = renew(client)
    assert r.status_code == 200
    assert "set-cookie" not in r.headers  # the other tab's cookie stays in the browser
    monkeypatch.setattr(sessions_module, "new_token", real_new_token)
    client.cookies.set(COOKIE, winner)
    assert renew(client).status_code == 200
    assert sessions()[-1].ended_at is None


def test_password_reset_ends_sessions(client, admin):
    with SessionLocal() as db:
        db.execute(update(User).values(sessions_valid_after=datetime.now(UTC) + timedelta(seconds=1)))
        db.commit()
    assert renew(client).status_code == 401
    assert sessions()[-1].ended_reason == "signed_out_everywhere"


def test_wildcard_cors_is_refused():
    import pytest

    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(cors_origins="https://hub.saxsprojects.co.za,*").cors_origin_list  # noqa: B018
