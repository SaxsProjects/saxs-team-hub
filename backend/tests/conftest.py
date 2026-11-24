import os

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite://",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
        "ADMIN_NOTIFY_EMAIL": "founder@example.com",
        "FRONTEND_URL": "https://hub.example.com",
        "JOBS_TOKEN": "jobs-token-for-tests",
        "SMTP_HOST": "",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import emailer  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.deps import account_failures, login_failures, reset_requests, totp_failures  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
ADMIN_EMAIL = "founder@saxsprojects.co.za"
ADMIN_PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    emailer.outbox.clear()
    login_failures.clear()
    account_failures.clear()
    totp_failures.clear()
    reset_requests.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin(client):
    with SessionLocal() as db:
        db.add(User(email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD), role="admin"))
        db.commit()
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def link_token(link: str) -> str:
    return link.rsplit("/", 1)[-1]


@pytest.fixture
def sent_offer(client, admin):
    """A person with an offer that has been sent. Returns (person, offer, token)."""
    person = client.post("/api/people", headers=admin, json={"full_name": "Thandi Mokoena", "email": "thandi@example.com"}).json()
    offer = client.post(
        "/api/offers", headers=admin, json={"person_id": person["id"], "role": "Junior Developer", "deadline": "2099-12-31"}
    ).json()
    r = client.post(f"/api/offers/{offer['id']}/pdf", headers=admin, files={"file": ("proposal.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/offers/{offer['id']}/send", headers=admin)
    assert r.status_code == 200, r.text
    return person, r.json(), link_token(r.json()["offer_link"])


def accept(client, token, name="Thandi Mokoena"):
    return client.post(
        f"/api/public/offers/{token}/accept",
        json={"typed_signature": name, "agree": True},
        headers={"User-Agent": "pytest-browser"},
    )


def member_login(client, email="thandi@example.com", password="member-password-123"):
    mail = next(m for m in emailer.outbox if m.to == email and "set-password?token=" in m.text)
    token = mail.text.split("set-password?token=")[1].split()[0]
    assert client.post("/api/auth/set-password", json={"token": token, "password": password}).status_code == 204
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
