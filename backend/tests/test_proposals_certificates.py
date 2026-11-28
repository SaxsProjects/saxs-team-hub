"""Proposals (SP-PRO) and certificates (SP-CERT)."""

from datetime import timedelta

import pytest

from app.db import SessionLocal
from app.models import Proposal
from app.services import today_local

from .test_client_finance import pdf_text
from .test_finance import company_ready, new_client, no_signature_cache, signed  # noqa: F401

JOBS = {"X-Jobs-Token": "jobs-token-for-tests"}


def generate(client, admin, service="website"):
    c = new_client(client, admin)
    r = client.post("/api/proposals/generate", headers=admin, json={"client_id": c["id"], "service": service})
    assert r.status_code == 201, r.text
    return r.json()


def test_presets_and_generated_draft(client, admin):
    keys = [p["key"] for p in client.get("/api/proposals/presets", headers=admin).json()]
    assert {"website", "web_app", "mobile_app", "ecommerce", "automation", "it_support", "custom"} <= set(keys)
    p = generate(client, admin)
    assert p["status"] == "draft" and p["number"] is None and p["title"] == "Business website for Glow Salon"
    assert "Glow Salon" in p["need"] and p["scope"] and p["why_us"]
    # Prices are never invented: every line starts at R0.00.
    assert p["items"] and all(i["unit_price_cents"] == 0 for i in p["items"]) and p["total_cents"] == 0
    draft = client.get(f"/api/proposals/{p['id']}/pdf", headers=admin)
    assert draft.status_code == 200 and "DRAFT - NOT ISSUED" in pdf_text(draft.content)


def test_proposals_are_admin_only(client, admin, team):
    _, member = team
    assert client.get("/api/proposals", headers=member).status_code == 403
    assert client.get("/api/certificates", headers=member).status_code == 403


@pytest.mark.usefixtures("company_ready")
def test_issue_needs_prices_then_numbers_and_converts_to_a_quotation(client, admin):
    p = generate(client, admin)
    assert client.post(f"/api/proposals/{p['id']}/issue", headers=admin).status_code == 400  # R0.00
    items = [{"description": "Website design and build", "quantity": 1, "unit_price_cents": 650_000}]
    r = client.patch(f"/api/proposals/{p['id']}", headers=admin, json={"items": items})
    assert r.status_code == 200 and r.json()["total_cents"] == 650_000
    issued = client.post(f"/api/proposals/{p['id']}/issue", headers=admin).json()
    assert issued["number"] == "SP-PRO-0001" and issued["status"] == "issued" and issued["pdf_sha256"]
    text = pdf_text(client.get(f"/api/proposals/{p['id']}/pdf", headers=admin).content)
    assert "SP-PRO-0001" in text and "Amount excl. VAT" in text and "R6,500.00" in text

    assert client.patch(f"/api/proposals/{p['id']}", headers=admin, json={"title": "Changed"}).status_code == 409
    assert client.delete(f"/api/proposals/{p['id']}", headers=admin).status_code == 409

    done = client.post(f"/api/proposals/{p['id']}/quotation", headers=admin).json()
    assert done["status"] == "accepted" and done["quotation_id"]
    q = client.get(f"/api/quotations/{done['quotation_id']}", headers=admin).json()
    assert q["status"] == "draft" and q["total_cents"] == 650_000 and q["lines"][0]["description"] == "Website design and build"
    assert client.post(f"/api/proposals/{p['id']}/quotation", headers=admin).status_code == 409


@pytest.mark.usefixtures("company_ready")
def test_proposals_expire_and_drafts_can_be_deleted(client, admin):
    p = generate(client, admin)
    client.patch(
        f"/api/proposals/{p['id']}",
        headers=admin,
        json={"items": [{"description": "Work", "quantity": 1, "unit_price_cents": 100}]},
    )
    client.post(f"/api/proposals/{p['id']}/issue", headers=admin)
    with SessionLocal() as db:
        db.get(Proposal, p["id"]).valid_until = today_local() - timedelta(days=1)
        db.commit()
    assert client.post("/api/jobs/daily", headers=JOBS).json()["proposals_expired"] == 1
    assert client.post(f"/api/proposals/{p['id']}/accept", headers=admin).status_code == 409
    other = client.post(
        "/api/proposals", headers=admin, json={"client_id": p["client_id"], "title": "Custom thing", "service": "custom"}
    ).json()
    assert client.delete(f"/api/proposals/{other['id']}", headers=admin).status_code == 204


@pytest.mark.usefixtures("no_signature_cache")
def test_certificate_needs_signature_and_filled_blanks(client, admin):
    body = {"kind": "training", "recipient_name": "Jane Doe", "body": "has completed training in Web Basics (40 hours)."}
    assert client.post("/api/certificates", headers=admin, json=body).status_code == 409  # no signature yet
    preview = client.post("/api/certificates/preview", headers=admin, json=body)
    assert preview.status_code == 200 and "SP-CERT-PREVIEW" in pdf_text(preview.content)
    assert client.get("/api/certificates", headers=admin).json() == []  # previews save nothing


@pytest.mark.usefixtures("company_ready")
def test_certificate_issue_verify_and_revoke(client, admin):
    presets = {p["kind"]: p for p in client.get("/api/certificates/presets", headers=admin).json()}
    assert presets["completion"]["subtitle"] == "OF COMPLETION" and "____" in presets["completion"]["body"]
    blank = {"kind": "completion", "recipient_name": "Jane Doe", "body": presets["completion"]["body"]}
    assert client.post("/api/certificates", headers=admin, json=blank).status_code == 400

    body = {"kind": "completion", "recipient_name": "Jane Doe", "body": "has successfully completed the Web Basics course."}
    r = client.post("/api/certificates", headers=admin, json=body)
    assert r.status_code == 201, r.text
    cert = r.json()
    assert cert["number"] == "SP-CERT-0001" and cert["title"] == "CERTIFICATE" and cert["subtitle"] == "OF COMPLETION"
    assert cert["verify_url"].endswith(f"/verify/{cert['verify_code']}") and len(cert["verify_code"]) >= 16
    text = pdf_text(client.get(f"/api/certificates/{cert['id']}/pdf", headers=admin).content)
    assert "SP-CERT-0001" in text and "Jane Doe" in text and "/verify/" in text

    page = client.get(f"/verify/{cert['verify_code']}")
    assert page.status_code == 200 and "genuine and valid" in page.text and "Jane Doe" in page.text
    assert client.get("/verify/not-a-real-code").status_code == 404

    assert (
        client.post(f"/api/certificates/{cert['id']}/revoke", headers=admin, json={"reason": "Issued in error"}).status_code
        == 200
    )
    assert "revoked" in client.get(f"/verify/{cert['verify_code']}").text
    assert client.post(f"/api/certificates/{cert['id']}/revoke", headers=admin, json={"reason": "Again"}).status_code == 409
    second = client.post("/api/certificates", headers=admin, json=body).json()
    assert second["number"] == "SP-CERT-0002"


@pytest.mark.usefixtures("company_ready")
def test_certificate_cannot_be_dated_in_the_future(client, admin):
    body = {
        "kind": "custom",
        "recipient_name": "Jane Doe",
        "body": "for something real.",
        "issue_date": (today_local() + timedelta(days=3)).isoformat(),
    }
    assert client.post("/api/certificates", headers=admin, json=body).status_code == 400
