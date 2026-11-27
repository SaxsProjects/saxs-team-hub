"""Previews show the founder a document before it is issued or sent, and never save anything."""

from datetime import timedelta

from app import emailer
from app.services import today_local

from .conftest import PDF
from .test_finance import TODAY, YEAR, company_ready, has_image, no_signature_cache, signed, standalone_invoice  # noqa: F401


def audit_count(client, admin) -> int:
    return len(client.get("/api/audit?limit=500", headers=admin).json())


def test_receipt_preview_saves_nothing(client, admin, company_ready):  # noqa: F811
    inv = standalone_invoice(client, admin)
    before = audit_count(client, admin)
    body = {"amount_cents": 40_000, "received_on": TODAY, "method": "eft", "reference": "EFT 123"}

    r = client.post(f"/api/invoices/{inv['id']}/payments/preview", headers=admin, json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert not has_image(r.content)  # never signed: the signature is only added when it is issued

    # Nothing changed: no receipt, the balance is the same, nothing audited, and no number used up.
    again = client.get(f"/api/invoices/{inv['id']}", headers=admin).json()
    assert again["balance_cents"] == inv["balance_cents"] and again["status"] == "issued"
    assert client.get(f"/api/invoices/{inv['id']}/receipts", headers=admin).json() == []
    assert audit_count(client, admin) == before
    paid = client.post(f"/api/invoices/{inv['id']}/payments", headers=admin, json=body)
    assert paid.status_code == 201 and paid.json()["receipt"]["number"] == f"SP-R-{YEAR}-001"


def test_receipt_preview_applies_the_same_checks(client, admin, company_ready):  # noqa: F811
    inv = standalone_invoice(client, admin)
    url = f"/api/invoices/{inv['id']}/payments/preview"
    too_much = {"amount_cents": inv["balance_cents"] + 1, "received_on": TODAY, "reference": "x"}
    assert client.post(url, headers=admin, json=too_much).status_code == 400
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    assert client.post(url, headers=admin, json={"amount_cents": 1, "received_on": tomorrow, "reference": "x"}).status_code == 400

    draft = client.post(
        "/api/invoices",
        headers=admin,
        json={
            "client_id": inv["client_id"],
            "title": "Draft work",
            "lines": [{"description": "Website work", "quantity": 1, "unit_price_cents": 10_000}],
        },
    ).json()
    r = client.post(
        f"/api/invoices/{draft['id']}/payments/preview",
        headers=admin,
        json={"amount_cents": 1, "received_on": TODAY, "reference": "x"},
    )
    assert r.status_code == 409


def test_credit_note_preview_saves_nothing(client, admin, company_ready):  # noqa: F811
    inv = standalone_invoice(client, admin)
    before = audit_count(client, admin)
    url = f"/api/invoices/{inv['id']}/credit-notes/preview"

    r = client.post(url, headers=admin, json={"amount_cents": 25_000, "reason": "Discount agreed"})
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF") and not has_image(r.content)
    assert (
        client.post(url, headers=admin, json={"amount_cents": inv["balance_cents"] + 1, "reason": "Too much"}).status_code == 400
    )

    again = client.get(f"/api/invoices/{inv['id']}", headers=admin).json()
    assert again["balance_cents"] == inv["balance_cents"] and again["credited_cents"] == 0
    assert client.get(f"/api/invoices/{inv['id']}/credit-notes", headers=admin).json() == []
    assert audit_count(client, admin) == before
    note = client.post(
        f"/api/invoices/{inv['id']}/credit-notes", headers=admin, json={"amount_cents": 25_000, "reason": "Discount agreed"}
    )
    assert note.status_code == 201 and note.json()["credit_note"]["number"] == f"SP-CN-{YEAR}-001"


def test_previews_are_founder_only(client, admin, team, company_ready):  # noqa: F811
    _, member = team
    inv = standalone_invoice(client, admin)
    pay = {"amount_cents": 1, "received_on": TODAY, "reference": "x"}
    assert client.post(f"/api/invoices/{inv['id']}/payments/preview", headers=member, json=pay).status_code == 403
    assert (
        client.post(
            f"/api/invoices/{inv['id']}/credit-notes/preview", headers=member, json={"amount_cents": 1, "reason": "abc"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/offers/email-preview", headers=member, json={"person_id": 1, "role": "Dev", "deadline": "2099-12-31"}
        ).status_code
        == 403
    )


def test_offer_email_preview_matches_what_is_sent(client, admin):
    person = client.post("/api/people", headers=admin, json={"full_name": "Thandi Mokoena", "email": "thandi@example.com"}).json()
    r = client.post(
        "/api/offers/email-preview",
        headers=admin,
        json={"person_id": person["id"], "role": "Junior Developer", "deadline": "2099-12-31"},
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["to"] == "thandi@example.com"
    assert (
        "Junior Developer" in preview["subject"]
        and "Hi Thandi Mokoena" in preview["text"]
        and "31 December 2099" in preview["text"]
    )
    assert client.get("/api/offers", headers=admin).json() == []  # nothing was created
    assert not [m for m in emailer.outbox if m.to == "thandi@example.com"]  # and nothing was emailed

    offer = client.post(
        "/api/offers", headers=admin, json={"person_id": person["id"], "role": "Junior Developer", "deadline": "2099-12-31"}
    ).json()
    client.post(f"/api/offers/{offer['id']}/pdf", headers=admin, files={"file": ("proposal.pdf", PDF, "application/pdf")})
    client.post(f"/api/offers/{offer['id']}/send", headers=admin)
    sent = next(m for m in emailer.outbox if m.to == "thandi@example.com")
    # Same email apart from the reference and the personal link, which only exist once it is sent.
    assert sent.subject == preview["subject"].replace("reference given when sent", offer["reference"])
    assert sent.text.split("\n")[:3] == preview["text"].split("\n")[:3]

    assert (
        client.post(
            "/api/offers/email-preview", headers=admin, json={"person_id": 999, "role": "Dev", "deadline": "2099-12-31"}
        ).status_code
        == 404
    )


def test_founder_can_open_the_attached_proposal(client, admin):
    person = client.post("/api/people", headers=admin, json={"full_name": "Sipho Dlamini", "email": "sipho@example.com"}).json()
    offer = client.post(
        "/api/offers", headers=admin, json={"person_id": person["id"], "role": "Designer", "deadline": "2099-12-31"}
    ).json()
    assert client.get(f"/api/offers/{offer['id']}/pdf", headers=admin).status_code == 404
    client.post(f"/api/offers/{offer['id']}/pdf", headers=admin, files={"file": ("proposal.pdf", PDF, "application/pdf")})
    r = client.get(f"/api/offers/{offer['id']}/pdf", headers=admin)
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
