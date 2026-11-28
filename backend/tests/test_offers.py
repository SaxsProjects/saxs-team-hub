from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app import emailer
from app.db import SessionLocal
from app.jobs import run_daily
from app.models import AuditLog, Offer, OfferResponse, Person

from .conftest import PDF, accept, member_login


def test_admin_routes_need_login(client):
    assert client.get("/api/people").status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x" * 12}).status_code == 401


def test_offer_link_is_stored_only_as_hash(client, sent_offer):
    _, offer, token = sent_offer
    with SessionLocal() as db:
        row = db.get(Offer, offer["id"])
        assert row.token_hash and token not in row.token_hash
        assert row.offer_hash and row.status == "sent"
    invite = next(m for m in emailer.outbox if m.to == "thandi@example.com")
    assert token in invite.text


def test_cannot_send_without_pdf(client, admin):
    person = client.post("/api/people", headers=admin, json={"full_name": "A Person", "email": "a@example.com"}).json()
    offer = client.post(
        "/api/offers", headers=admin, json={"person_id": person["id"], "role": "Dev", "deadline": "2099-01-01"}
    ).json()
    assert client.post(f"/api/offers/{offer['id']}/send", headers=admin).status_code == 400


def test_rejects_non_pdf_upload(client, admin, sent_offer):
    person, _, _ = sent_offer
    offer = client.post(
        "/api/offers", headers=admin, json={"person_id": person["id"], "role": "Dev", "deadline": "2099-01-01"}
    ).json()
    r = client.post(
        f"/api/offers/{offer['id']}/pdf", headers=admin, files={"file": ("x.pdf", b"<html>not a pdf</html>", "application/pdf")}
    )
    assert r.status_code == 400


def test_view_marks_viewed_and_notifies_once(client, sent_offer):
    _, _, token = sent_offer
    r = client.get(f"/api/public/offers/{token}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "viewed" and body["can_respond"] and "POPIA" in body["privacy_notice"]
    client.get(f"/api/public/offers/{token}")
    assert sum("Offer viewed" in m.subject for m in emailer.outbox) == 1
    assert client.get(f"/api/public/offers/{token}/pdf").content == PDF


def test_unknown_or_malformed_token_is_404(client, sent_offer):
    assert client.get("/api/public/offers/not-a-real-token-but-long-enough").status_code == 404
    assert client.get("/api/public/offers/short").status_code == 404


def test_accept_requires_exact_typed_name(client, sent_offer):
    _, _, token = sent_offer
    assert accept(client, token, name="Someone Else").status_code == 400
    r = client.post(f"/api/public/offers/{token}/accept", json={"typed_signature": "Thandi Mokoena", "agree": False})
    assert r.status_code == 400


def test_accept_records_proof_onboarding_and_account(client, admin, sent_offer):
    person, offer, token = sent_offer
    r = accept(client, token, name="  thandi   MOKOENA ")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted" and not r.json()["can_respond"]

    with SessionLocal() as db:
        resp = db.scalar(select(OfferResponse).where(OfferResponse.offer_id == offer["id"]))
        assert resp.decision == "accepted"
        assert resp.user_agent == "pytest-browser"
        assert resp.offer_hash == db.get(Offer, offer["id"]).offer_hash
        assert resp.acceptance_document_id
        assert db.get(Person, person["id"]).status == "accepted"
        actions = {a.action for a in db.scalars(select(AuditLog))}
        assert {"offer.send", "offer.accept", "person.stage"} <= actions

    # Single use: a second response is refused.
    assert accept(client, token).status_code == 409
    assert client.post(f"/api/public/offers/{token}/decline", json={}).status_code == 409

    items = client.get(f"/api/people/{person['id']}/onboarding", headers=admin).json()
    assert len(items) == 7 and not any(i["done"] for i in items)

    welcome = next(m for m in emailer.outbox if m.to == "thandi@example.com" and "Welcome" in m.subject)
    assert welcome.attachments and welcome.attachments[0][1].startswith(b"%PDF")
    assert any("ACCEPTED" in m.subject for m in emailer.outbox if m.to == "founder@example.com")


def test_decline_flow(client, sent_offer):
    person, _, token = sent_offer
    r = client.post(f"/api/public/offers/{token}/decline", json={"reason": "Accepted another role"})
    assert r.status_code == 200 and r.json()["status"] == "declined"
    founder_mail = next(m for m in emailer.outbox if "declined" in m.subject)
    assert "Accepted another role" in founder_mail.text
    with SessionLocal() as db:
        assert db.get(Person, person["id"]).status == "declined"


def test_member_sees_only_own_data_and_ticks_allowed_items(client, admin, sent_offer):
    person, _, token = sent_offer
    accept(client, token)
    member = member_login(client)

    assert client.get("/api/people", headers=member).status_code == 403
    items = client.get("/api/me/onboarding", headers=member).json()
    allowed = next(i for i in items if i["member_can_complete"])
    locked = next(i for i in items if not i["member_can_complete"])
    assert client.patch(f"/api/me/onboarding/{allowed['id']}", headers=member, json={"done": True}).json()["done"]
    assert client.patch(f"/api/me/onboarding/{locked['id']}", headers=member, json={"done": True}).status_code == 403

    docs = client.get("/api/me/documents", headers=member).json()
    assert {d["kind"] for d in docs} == {"offer_pdf", "acceptance"}
    assert client.get(f"/api/documents/{docs[0]['id']}", headers=member).status_code == 200

    # Another candidate's document is invisible to this member.
    other = client.post("/api/people", headers=admin, json={"full_name": "Other Person", "email": "o@example.com"}).json()
    doc = client.post(
        f"/api/people/{other['id']}/documents", headers=admin, files={"file": ("agreement.pdf", PDF, "application/pdf")}
    ).json()
    assert client.get(f"/api/documents/{doc['id']}", headers=member).status_code == 404


def test_banking_details_encrypted_at_rest(client, sent_offer):
    person, _, token = sent_offer
    accept(client, token)
    member = member_login(client)
    details = {
        "bank_name": "Capitec",
        "account_holder": "T Mokoena",
        "account_number": "1234567890",
        "branch_code": "470010",
        "account_type": "savings",
    }
    assert client.put("/api/me/sensitive", headers=member, json=details).status_code == 204
    with SessionLocal() as db:
        raw = db.get(Person, person["id"]).sensitive_enc
        assert "1234567890" not in raw and "Capitec" not in raw
    masked = client.get("/api/me/sensitive", headers=member).json()
    assert masked["account_number"] == "****7890"
    items = client.get("/api/me/onboarding", headers=member).json()
    assert next(i for i in items if i["key"] == "banking_captured")["done"]


def test_daily_job_expires_overdue_offer(client, sent_offer):
    _, offer, token = sent_offer
    with SessionLocal() as db:
        row = db.get(Offer, offer["id"])
        row.token_expires_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
        result = run_daily(db)
    assert result["offers_expired"] == 1
    assert client.get(f"/api/public/offers/{token}").json()["status"] == "expired"
    assert accept(client, token).status_code == 410
    assert sum("Offer expired" in m.subject for m in emailer.outbox) == 1


def test_jobs_endpoint_requires_token(client):
    assert client.post("/api/jobs/daily").status_code == 401
    r = client.post("/api/jobs/daily", headers={"X-Jobs-Token": "jobs-token-for-tests"})
    assert r.status_code == 200 and set(r.json()) == {
        "offers_expired",
        "quotations_expired",
        "invoices_overdue",
        "payouts_due",
        "task_reviews_overdue",
        "people_purged",
        "proposals_expired",
        "client_reminders_sent",
        "statements_sent",
        "monthly_report_sent",
        "notifications_purged",
    }


def test_offer_in_past_rejected(client, admin):
    person = client.post("/api/people", headers=admin, json={"full_name": "A Person", "email": "a@example.com"}).json()
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    r = client.post("/api/offers", headers=admin, json={"person_id": person["id"], "role": "Dev", "deadline": yesterday})
    assert r.status_code == 400


def test_pipeline_board(client, admin, sent_offer):
    board = client.get("/api/pipeline", headers=admin).json()
    assert [p["full_name"] for p in board["stages"]["sent"]] == ["Thandi Mokoena"]
