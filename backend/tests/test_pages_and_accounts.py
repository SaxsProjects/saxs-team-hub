"""Email-link pages (offer, set/reset password) and account lifecycle (reset, invite, access, sign-out)."""

import re
import time

from sqlalchemy import select

from app import emailer
from app.config import Settings
from app.db import SessionLocal
from app.models import Offer, OfferResponse

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, PDF, accept, member_login


def last_link(path: str, to: str) -> str:
    mail = [m for m in emailer.outbox if m.to == to and path in m.text][-1]
    return re.search(rf"{re.escape(path)}\?token=([A-Za-z0-9_-]+)", mail.text).group(1)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- Offer page ---------------------------------------------------------------------------


def test_offer_page_shows_offer_and_forms(client, sent_offer):
    _, offer, token = sent_offer
    r = client.get(f"/offer/{token}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Junior Developer" in r.text and offer["reference"] in r.text
    assert "Accept offer" in r.text and "Decline offer" in r.text
    assert "POPIA" in r.text
    assert "default-src 'none'" in r.headers["content-security-policy"]
    pdf = client.get(f"/api/public/offers/{token}/pdf")
    assert pdf.content == PDF and "content-security-policy" not in pdf.headers


def test_offer_page_escapes_html(client, admin):
    person = client.post(
        "/api/people", headers=admin, json={"full_name": "Eve <script>x</script>", "email": "e@example.com"}
    ).json()
    offer = client.post(
        "/api/offers", headers=admin, json={"person_id": person["id"], "role": "<b>Dev</b>", "deadline": "2099-01-01"}
    ).json()
    client.post(f"/api/offers/{offer['id']}/pdf", headers=admin, files={"file": ("p.pdf", PDF, "application/pdf")})
    token = client.post(f"/api/offers/{offer['id']}/send", headers=admin).json()["offer_link"].rsplit("/", 1)[-1]
    page = client.get(f"/offer/{token}").text
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page
    assert "<b>Dev</b>" not in page


def test_accept_through_the_page(client, sent_offer):
    _, offer, token = sent_offer
    wrong = client.post(f"/offer/{token}/accept", data={"typed_signature": "Somebody Else", "agree": "yes"})
    assert wrong.status_code == 400 and "exactly as shown" in wrong.text and "Somebody Else" in wrong.text
    unticked = client.post(f"/offer/{token}/accept", data={"typed_signature": "Thandi Mokoena"})
    assert unticked.status_code == 400

    ok = client.post(
        f"/offer/{token}/accept",
        data={"typed_signature": "Thandi Mokoena", "agree": "yes"},
        headers={"User-Agent": "candidate-browser"},
    )
    assert ok.status_code == 200 and "acceptance has been recorded" in ok.text
    with SessionLocal() as db:
        resp = db.scalar(select(OfferResponse).where(OfferResponse.offer_id == offer["id"]))
        assert resp.decision == "accepted" and resp.user_agent == "candidate-browser"
    again = client.get(f"/offer/{token}")
    assert "You accepted this offer" in again.text and "Accept offer" not in again.text
    assert client.post(f"/offer/{token}/accept", data={"typed_signature": "Thandi Mokoena", "agree": "yes"}).status_code == 409


def test_decline_through_the_page(client, sent_offer):
    _, offer, token = sent_offer
    r = client.post(f"/offer/{token}/decline", data={"reason": "Studying full time"})
    assert r.status_code == 200 and "You declined this offer" in r.text
    with SessionLocal() as db:
        assert db.get(Offer, offer["id"]).status == "declined"


def test_unknown_offer_page_is_a_friendly_404(client):
    r = client.get("/offer/this-token-does-not-exist-at-all")
    assert r.status_code == 404 and "Sorry" in r.text


# ---- Password pages and reset ---------------------------------------------------------------


def test_set_password_page(client, sent_offer):
    _, _, token = sent_offer
    accept(client, token)
    setup = last_link("/set-password", "thandi@example.com")
    assert client.get(f"/set-password?token={setup}").status_code == 200
    mismatch = client.post("/set-password", data={"token": setup, "password": "long-enough-pass", "confirm": "different-pass"})
    assert mismatch.status_code == 400 and "match" in mismatch.text
    short = client.post("/set-password", data={"token": setup, "password": "short", "confirm": "short"})
    assert short.status_code == 400
    ok = client.post("/set-password", data={"token": setup, "password": "page-password-123", "confirm": "page-password-123"})
    assert ok.status_code == 200 and "Password saved" in ok.text
    login = client.post("/api/auth/login", json={"email": "thandi@example.com", "password": "page-password-123"})
    assert login.status_code == 200
    reused = client.post("/set-password", data={"token": setup, "password": "page-password-456", "confirm": "page-password-456"})
    assert reused.status_code == 400 and "invalid or has expired" in reused.text


def test_forgot_and_reset_password_signs_out_old_sessions(client, sent_offer):
    _, _, token = sent_offer
    accept(client, token)
    member = member_login(client)
    assert client.get("/api/me/profile", headers=member).status_code == 200

    assert client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"}).status_code == 204
    assert not any("reset-password" in m.text for m in emailer.outbox)
    assert client.post("/api/auth/forgot-password", json={"email": "thandi@example.com"}).status_code == 204
    reset = last_link("/reset-password", "thandi@example.com")

    time.sleep(0.01)
    r = client.post("/reset-password", data={"token": reset, "password": "brand-new-pass-1", "confirm": "brand-new-pass-1"})
    assert r.status_code == 200
    assert client.get("/api/me/profile", headers=member).status_code == 401  # old session ended
    assert (
        client.post("/api/auth/login", json={"email": "thandi@example.com", "password": "member-password-123"}).status_code == 401
    )
    assert client.post("/api/auth/login", json={"email": "thandi@example.com", "password": "brand-new-pass-1"}).status_code == 200


def test_forgot_password_page_reveals_nothing(client):
    r = client.post("/forgot-password", data={"email": "not-an-email"})
    assert r.status_code == 200 and "If that address has a Team Hub account" in r.text


def test_change_password_returns_new_session_and_ends_old_ones(client, admin):
    time.sleep(0.01)
    r = client.post(
        "/api/auth/change-password",
        headers=admin,
        json={"current_password": ADMIN_PASSWORD, "new_password": "another-long-password"},
    )
    assert r.status_code == 200
    assert client.get("/api/people", headers=admin).status_code == 401
    assert client.get("/api/people", headers=bearer(r.json()["access_token"])).status_code == 200
    assert client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "another-long-password"}).status_code == 200


# ---- Admin: resend invite, access on/off ------------------------------------------------------


def test_resend_invite_replaces_old_link(client, admin, sent_offer):
    person, _, token = sent_offer
    accept(client, token)
    first = last_link("/set-password", "thandi@example.com")
    assert client.post(f"/api/people/{person['id']}/invite", headers=admin).status_code == 204
    second = last_link("/set-password", "thandi@example.com")
    assert first != second
    assert client.post("/api/auth/set-password", json={"token": first, "password": "first-link-pass"}).status_code == 400
    assert client.post("/api/auth/set-password", json={"token": second, "password": "second-link-pass"}).status_code == 204


def test_invite_needs_an_account(client, admin):
    person = client.post("/api/people", headers=admin, json={"full_name": "No Account", "email": "n@example.com"}).json()
    assert client.post(f"/api/people/{person['id']}/invite", headers=admin).status_code == 404


def test_turning_access_off_signs_member_out(client, admin, sent_offer):
    person, _, token = sent_offer
    accept(client, token)
    member = member_login(client)
    time.sleep(0.01)
    assert client.post(f"/api/people/{person['id']}/access", headers=admin, json={"active": False}).status_code == 200
    assert client.get("/api/me/profile", headers=member).status_code == 401
    assert (
        client.post("/api/auth/login", json={"email": "thandi@example.com", "password": "member-password-123"}).status_code == 401
    )
    assert client.post(f"/api/people/{person['id']}/invite", headers=admin).status_code == 409
    assert client.post(f"/api/people/{person['id']}/access", headers=admin, json={"active": True}).status_code == 200
    assert (
        client.post("/api/auth/login", json={"email": "thandi@example.com", "password": "member-password-123"}).status_code == 200
    )
    # members can't change access themselves
    assert client.post(f"/api/people/{person['id']}/access", headers=member, json={"active": True}).status_code in (401, 403)


def test_api_docs_off_in_production_unless_enabled():
    assert Settings(environment="production").api_docs_enabled is False
    assert Settings(environment="production", enable_api_docs=True).api_docs_enabled is True
    assert Settings(environment="development").api_docs_enabled is True
