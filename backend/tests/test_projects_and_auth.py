import pyotp
import pytest

from app.config import get_settings

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, accept, member_login


@pytest.fixture
def team(client, admin, sent_offer):
    """An accepted contributor with a member login."""
    person, _, token = sent_offer
    accept(client, token)
    return person, member_login(client)


def test_payout_flow(client, admin, team):
    person, member = team
    project = client.post("/api/projects", headers=admin, json={"name": "Salon booking app", "client_name": "Glow Salon"}).json()
    pid = project["id"]
    r = client.put(f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": person["id"], "work_share_bp": 6000})
    assert r.status_code == 200 and r.json()["rate_bp"] == 1500
    assert (
        client.put(
            f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": person["id"], "work_share_bp": 10_001}
        ).status_code
        == 422
    )

    client.post(
        f"/api/projects/{pid}/costs",
        headers=admin,
        json={"description": "Hosting", "amount_cents": 50_000, "incurred_at": "2026-12-01"},
    )
    r = client.post(
        f"/api/projects/{pid}/payments",
        headers=admin,
        json={"amount_cents": 250_000, "received_at": "2026-12-05", "reference": "EFT-1"},
    )
    assert r.status_code == 201, r.text
    [payout] = r.json()["payouts"]
    # (2500 - 500) x 15% x 60% = R180.00, due 7 days later
    assert payout["amount_cents"] == 18_000
    assert payout["due_at"] == "2026-12-12"
    assert payout["statement_number"].startswith("SP-PS-")

    # Shares are locked once money comes in.
    assert (
        client.put(
            f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": person["id"], "work_share_bp": 5000}
        ).status_code
        == 409
    )

    r = client.post(
        f"/api/projects/{pid}/payments",
        headers=admin,
        json={"amount_cents": 250_000, "received_at": "2026-12-20", "reference": "EFT-2"},
    )
    assert r.json()["payouts"][0]["amount_cents"] == 22_500  # total earned 405.00 - 180.00 already paid

    detail = client.get(f"/api/projects/{pid}", headers=admin).json()
    assert detail["net_income_cents"] == 450_000

    mine = client.get("/api/me/payouts", headers=member).json()
    assert [p["amount_cents"] for p in mine] == [18_000, 22_500]
    statement = client.get(f"/api/payouts/{payout['id']}/statement.pdf", headers=member)
    assert statement.status_code == 200 and statement.content.startswith(b"%PDF")

    paid = client.post(f"/api/payouts/{payout['id']}/paid", headers=admin, json={"eft_reference": "FNB-778"})
    assert paid.json()["eft_reference"] == "FNB-778"
    assert client.post(f"/api/payouts/{payout['id']}/paid", headers=admin, json={"eft_reference": "x1"}).status_code == 409
    assert client.get("/api/payouts?unpaid=true", headers=admin).json()[0]["amount_cents"] == 22_500


def test_member_cannot_read_other_statements(client, admin, team):
    person, member = team
    other = client.post("/api/people", headers=admin, json={"full_name": "Sipho Dube", "email": "s@example.com"}).json()
    from app.db import SessionLocal
    from app.models import Person

    with SessionLocal() as db:
        db.get(Person, other["id"]).status = "accepted"
        db.commit()
    pid = client.post("/api/projects", headers=admin, json={"name": "Site", "client_name": "Client"}).json()["id"]
    client.put(f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": other["id"], "work_share_bp": 10000})
    payout = client.post(
        f"/api/projects/{pid}/payments",
        headers=admin,
        json={"amount_cents": 100_000, "received_at": "2026-12-01", "reference": "R1"},
    ).json()["payouts"][0]
    assert client.get(f"/api/payouts/{payout['id']}/statement.pdf", headers=member).status_code == 404


def test_rate_change_needs_written_review(client, admin, team):
    person, _ = team
    assert client.patch(f"/api/people/{person['id']}", headers=admin, json={"rate_bp": 2000}).status_code == 400
    assert (
        client.patch(f"/api/people/{person['id']}", headers=admin, json={"rate_bp": 1800, "rate_review_note": "x"}).status_code
        == 422
    )
    r = client.patch(
        f"/api/people/{person['id']}",
        headers=admin,
        json={"rate_bp": 2000, "rate_review_note": "Review 2027-03-01: excellent delivery"},
    )
    assert r.json()["rate_bp"] == 2000


def test_admin_two_factor(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "require_admin_2fa", True)
    assert client.get("/api/people", headers=admin).status_code == 403  # must enable 2FA first
    secret = client.post("/api/auth/2fa/setup", headers=admin).json()["secret"]
    assert client.post("/api/auth/2fa/enable", headers=admin, json={"code": "000000"}).status_code == 400
    assert client.post("/api/auth/2fa/enable", headers=admin, json={"code": pyotp.TOTP(secret).now()}).status_code == 204

    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    r = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": pyotp.TOTP(secret).now()}
    )
    token = r.json()["access_token"]
    assert client.get("/api/people", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_set_password_link_is_single_use(client, team):
    from app import emailer

    mail = next(m for m in emailer.outbox if "set-password?token=" in m.text)
    token = mail.text.split("set-password?token=")[1].split()[0]
    assert client.post("/api/auth/set-password", json={"token": token, "password": "another-password-1"}).status_code == 400


def test_security_headers_and_health(client):
    r = client.get("/api/health")
    assert r.json()["ok"] is True
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_production_refuses_weak_config(monkeypatch):
    from app.config import Settings

    s = Settings(environment="production", database_url="sqlite://", secret_key="short")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        s.check_production_ready()
