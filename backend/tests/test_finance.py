import base64
import hashlib
import struct
import zlib
from datetime import date

import pytest

from app import pdf as pdf_module
from app.config import Settings, get_settings
from app.finance import document_totals, excluding_vat, portion_of, round_half_up
from app.services import today_local

from .conftest import accept, member_login

YEAR = today_local().year
TODAY = today_local().isoformat()


def tiny_png(width: int = 60, height: int = 20) -> bytes:
    """A small valid PNG (a dark diagonal stroke on white), standing in for the real signature in tests."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(
        b"\x00" + b"".join(b"\x10\x10\x40" if abs(x - y * 3) < 3 else b"\xff\xff\xff" for x in range(width))
        for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


@pytest.fixture
def no_signature_cache():
    pdf_module.load_signature.cache_clear()
    yield
    pdf_module.load_signature.cache_clear()


@pytest.fixture
def signed(monkeypatch, tmp_path, no_signature_cache):
    path = tmp_path / "signature.png"
    path.write_bytes(tiny_png())
    s = get_settings()
    monkeypatch.setattr(s, "signature_image_path", str(path))
    monkeypatch.setattr(s, "signatory_name", "Test Director")
    return s


@pytest.fixture
def company_ready(monkeypatch, signed):
    s = signed
    monkeypatch.setattr(s, "company_registration_number", "2026/000000/07")
    monkeypatch.setattr(s, "company_bank_name", "Test Bank")
    monkeypatch.setattr(s, "company_bank_account_number", "000000000")
    monkeypatch.setattr(s, "company_bank_branch_code", "000000")
    return s


def has_image(pdf_bytes: bytes) -> bool:
    # Object dictionaries are not compressed, so an embedded image shows up as /Subtype /Image.
    return b"/Subtype /Image" in pdf_bytes


def new_client(client, admin, name="Glow Salon"):
    r = client.post(
        "/api/clients", headers=admin, json={"name": name, "email": "owner@glow.example", "address": "1 Main Rd\nThohoyandou"}
    )
    assert r.status_code == 201, r.text
    return r.json()


def new_quote(client, admin, client_id, lines=None, title="Booking website"):
    lines = lines or [{"description": "Website build", "quantity": 1, "unit_price_cents": 2_000_000}]
    r = client.post("/api/quotations", headers=admin, json={"client_id": client_id, "title": title, "lines": lines})
    assert r.status_code == 201, r.text
    return r.json()


# ---- Pure money rules -----------------------------------------------------------------------------


def test_money_rules():
    assert document_totals([100_000, 50_050], 0).total_cents == 150_050
    t = document_totals([100_000], 1500)
    assert (t.subtotal_cents, t.vat_cents, t.total_cents) == (100_000, 15_000, 115_000)
    assert document_totals([333], 1500).vat_cents == 50  # 49.95 rounds half-up to 50
    assert portion_of(2_000_000, 50) == 1_000_000
    assert excluding_vat(115_000, 100_000, 115_000) == 100_000
    assert excluding_vat(500, 500, 500) == 500
    assert round_half_up(5, 10) == 1 and round_half_up(4, 10) == 0
    with pytest.raises(ValueError):
        document_totals([2_000_000_001], 0)


# ---- Readiness and signing rules --------------------------------------------------------------------


def test_cannot_issue_without_signature_or_company_details(client, admin, no_signature_cache):
    c = new_client(client, admin)
    q = new_quote(client, admin, c["id"])
    r = client.get("/api/finance/readiness", headers=admin).json()
    assert r["can_issue_quotations"] is False and r["can_issue_invoices"] is False
    assert client.post(f"/api/quotations/{q['id']}/issue", headers=admin).status_code == 409

    inv = client.post(
        "/api/invoices",
        headers=admin,
        json={
            "client_id": c["id"],
            "title": "Hosting",
            "lines": [{"description": "Hosting", "quantity": 1, "unit_price_cents": 10_000}],
        },
    ).json()
    r = client.post(f"/api/invoices/{inv['id']}/issue", headers=admin)
    assert r.status_code == 409 and "COMPANY_REGISTRATION_NUMBER" in r.json()["detail"]


def test_invoice_needs_bank_details_even_when_signed(client, admin, signed):
    c = new_client(client, admin)
    assert client.get("/api/finance/readiness", headers=admin).json()["can_issue_quotations"] is True
    inv = client.post(
        "/api/invoices",
        headers=admin,
        json={
            "client_id": c["id"],
            "title": "Hosting",
            "lines": [{"description": "Hosting", "quantity": 1, "unit_price_cents": 10_000}],
        },
    ).json()
    assert client.post(f"/api/invoices/{inv['id']}/issue", headers=admin).status_code == 409


def test_readiness_never_returns_values(client, admin, company_ready):
    body = client.get("/api/finance/readiness", headers=admin).text
    assert "000000000" not in body and "Test Director" not in body and "signature.png" not in body


def test_finance_is_admin_only(client, admin, sent_offer):
    _, _, token = sent_offer
    accept(client, token)
    member = member_login(client)
    assert client.get("/api/clients").status_code == 401
    for path in ("/api/clients", "/api/quotations", "/api/invoices", "/api/finance/readiness", "/api/finance/summary"):
        assert client.get(path, headers=member).status_code == 403, path


# ---- Quotations ----------------------------------------------------------------------------------


def test_quotation_lifecycle_numbering_and_signature(client, admin, company_ready):
    c = new_client(client, admin)
    q = new_quote(
        client,
        admin,
        c["id"],
        lines=[
            {"description": "Website build", "quantity": 1, "unit_price_cents": 1_500_000},
            {"description": "Training session", "quantity": 2, "unit_price_cents": 250_000},
        ],
    )
    assert q["number"] is None and q["total_cents"] == 2_000_000 and q["vat_cents"] == 0

    draft = client.get(f"/api/quotations/{q['id']}/pdf", headers=admin)
    assert draft.status_code == 200 and draft.content.startswith(b"%PDF")
    assert not has_image(draft.content)  # drafts are never signed
    assert b"/ca 0.15" in draft.content  # the faint DRAFT watermark

    r = client.post(f"/api/quotations/{q['id']}/issue", headers=admin)
    assert r.status_code == 200, r.text
    issued = r.json()
    assert issued["number"] == f"SP-Q-{YEAR}-001" and issued["status"] == "issued"
    assert issued["issue_date"] == TODAY and issued["valid_until"]

    stored = client.get(f"/api/quotations/{q['id']}/pdf", headers=admin).content
    assert has_image(stored)  # the director's signature
    assert b"/ca 0.15" not in stored
    assert hashlib.sha256(stored).hexdigest() == issued["pdf_sha256"]  # exactly what was issued

    # Issued documents are locked.
    assert client.patch(f"/api/quotations/{q['id']}", headers=admin, json={"title": "Changed"}).status_code == 409
    assert client.post(f"/api/quotations/{q['id']}/issue", headers=admin).status_code == 409
    assert client.delete(f"/api/quotations/{q['id']}", headers=admin).status_code == 409

    q2 = new_quote(client, admin, c["id"], title="Second")
    assert client.post(f"/api/quotations/{q2['id']}/issue", headers=admin).json()["number"] == f"SP-Q-{YEAR}-002"

    # A draft that is deleted never used a number.
    q3 = new_quote(client, admin, c["id"], title="Scrapped")
    assert client.delete(f"/api/quotations/{q3['id']}", headers=admin).status_code == 204
    q4 = new_quote(client, admin, c["id"], title="Third")
    assert client.post(f"/api/quotations/{q4['id']}/issue", headers=admin).json()["number"] == f"SP-Q-{YEAR}-003"


def test_quotation_without_lines_cannot_be_issued(client, admin, company_ready):
    c = new_client(client, admin)
    q = client.post("/api/quotations", headers=admin, json={"client_id": c["id"], "title": "Empty"}).json()
    assert client.post(f"/api/quotations/{q['id']}/issue", headers=admin).status_code == 400


def test_accept_creates_project_and_decline(client, admin, company_ready):
    c = new_client(client, admin)
    q = new_quote(client, admin, c["id"])
    assert client.post(f"/api/quotations/{q['id']}/accept", headers=admin).status_code == 409  # still a draft
    client.post(f"/api/quotations/{q['id']}/issue", headers=admin)
    accepted = client.post(f"/api/quotations/{q['id']}/accept", headers=admin).json()
    assert accepted["status"] == "accepted" and accepted["project_id"]
    project = client.get(f"/api/projects/{accepted['project_id']}", headers=admin).json()
    assert project["client_name"] == "Glow Salon"

    q2 = new_quote(client, admin, c["id"], title="Other")
    client.post(f"/api/quotations/{q2['id']}/issue", headers=admin)
    assert client.post(f"/api/quotations/{q2['id']}/decline", headers=admin).json()["status"] == "declined"
    assert client.post(f"/api/quotations/{q2['id']}/accept", headers=admin).status_code == 409


# ---- Invoices, receipts and payouts ----------------------------------------------------------------


def test_deposit_and_balance_invoices_drive_payouts(client, admin, company_ready, sent_offer):
    """The contractor-agreement example: R20,000 received, R2,000 costs, 15% x 100% share = R2,700 in total."""
    person, _, token = sent_offer
    accept(client, token)
    c = new_client(client, admin)
    q = new_quote(client, admin, c["id"])  # R20,000
    client.post(f"/api/quotations/{q['id']}/issue", headers=admin)
    pid = client.post(f"/api/quotations/{q['id']}/accept", headers=admin).json()["project_id"]
    client.put(f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": person["id"], "work_share_bp": 10_000})
    client.post(
        f"/api/projects/{pid}/costs",
        headers=admin,
        json={"description": "Hosting and domain", "amount_cents": 200_000, "incurred_at": TODAY},
    )

    # 50% deposit invoice
    deposit = client.post("/api/invoices", headers=admin, json={"quotation_id": q["id"], "portion_percent": 50}).json()
    assert deposit["total_cents"] == 1_000_000 and deposit["project_id"] == pid
    assert "deposit" in deposit["lines"][0]["description"]
    draft_pdf = client.get(f"/api/invoices/{deposit['id']}/pdf", headers=admin).content
    assert b"/ca 0.15" in draft_pdf  # DRAFT - NOT VALID FOR PAYMENT
    deposit = client.post(f"/api/invoices/{deposit['id']}/issue", headers=admin).json()
    assert deposit["number"] == f"SP-INV-{YEAR}-001" and deposit["status"] == "issued"
    inv_pdf = client.get(f"/api/invoices/{deposit['id']}/pdf", headers=admin).content
    assert hashlib.sha256(inv_pdf).hexdigest() == deposit["pdf_sha256"]
    assert not has_image(inv_pdf)  # invoices carry banking details, not a signature

    # Can't overpay, can't pay a draft, can't date a payment in the future.
    pay = {"amount_cents": 1_000_001, "received_on": TODAY, "reference": "EFT-1"}
    assert client.post(f"/api/invoices/{deposit['id']}/payments", headers=admin, json=pay).status_code == 400
    future = {"amount_cents": 1_000, "received_on": "2999-01-01", "reference": "EFT-1"}
    assert client.post(f"/api/invoices/{deposit['id']}/payments", headers=admin, json=future).status_code == 400

    r = client.post(
        f"/api/invoices/{deposit['id']}/payments",
        headers=admin,
        json={"amount_cents": 1_000_000, "received_on": TODAY, "reference": "EFT-1"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["invoice"]["status"] == "paid" and body["invoice"]["balance_cents"] == 0
    assert body["receipt"]["number"] == f"SP-R-{YEAR}-001"
    [first] = body["payouts"]
    assert first["amount_cents"] == 120_000  # (10,000 - 2,000) x 15% = R1,200
    receipt_pdf = client.get(f"/api/receipts/{body['receipt']['id']}/pdf", headers=admin).content
    assert has_image(receipt_pdf) and hashlib.sha256(receipt_pdf).hexdigest() == body["receipt"]["pdf_sha256"]

    # Balance invoice: whatever is left on the quotation.
    balance = client.post("/api/invoices", headers=admin, json={"quotation_id": q["id"]}).json()
    assert balance["total_cents"] == 1_000_000 and "Balance" in balance["lines"][0]["description"]
    client.post(f"/api/invoices/{balance['id']}/issue", headers=admin)
    r = client.post(
        f"/api/invoices/{balance['id']}/payments",
        headers=admin,
        json={"amount_cents": 1_000_000, "received_on": TODAY, "reference": "EFT-2"},
    ).json()
    assert r["payouts"][0]["amount_cents"] == 150_000  # total R2,700 - R1,200 already paid
    assert first["amount_cents"] + r["payouts"][0]["amount_cents"] == 270_000

    # Fully invoiced now.
    assert client.post("/api/invoices", headers=admin, json={"quotation_id": q["id"]}).status_code == 409

    # The payout statement is signed.
    statement = client.get(f"/api/payouts/{first['id']}/statement.pdf", headers=admin).content
    assert has_image(statement)

    summary = client.get("/api/finance/summary", headers=admin).json()
    assert summary["received_cents"] == 2_000_000 and summary["outstanding_cents"] == 0


def test_invoice_from_unaccepted_quote_or_without_lines_is_refused(client, admin, company_ready):
    c = new_client(client, admin)
    q = new_quote(client, admin, c["id"])
    assert client.post("/api/invoices", headers=admin, json={"quotation_id": q["id"]}).status_code == 409
    assert client.post("/api/invoices", headers=admin, json={"client_id": c["id"], "title": "No lines"}).status_code == 400
    assert (
        client.post(
            "/api/invoices",
            headers=admin,
            json={
                "client_id": c["id"],
                "title": "Extra",
                "portion_percent": 50,
                "lines": [{"description": "Thing", "quantity": 1, "unit_price_cents": 1}],
            },
        ).status_code
        == 400
    )


def standalone_invoice(client, admin, cents=100_000):
    c = new_client(client, admin, name="Corner Shop")
    inv = client.post(
        "/api/invoices",
        headers=admin,
        json={
            "client_id": c["id"],
            "title": "Support",
            "lines": [{"description": "Monthly support", "quantity": 1, "unit_price_cents": cents}],
        },
    ).json()
    r = client.post(f"/api/invoices/{inv['id']}/issue", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def test_credit_notes_correct_issued_invoices(client, admin, company_ready):
    inv = standalone_invoice(client, admin)
    assert client.patch(f"/api/invoices/{inv['id']}", headers=admin, json={"title": "Edited"}).status_code == 409
    assert (
        client.post(
            f"/api/invoices/{inv['id']}/credit-notes", headers=admin, json={"amount_cents": 100_001, "reason": "Too much"}
        ).status_code
        == 400
    )

    r = client.post(
        f"/api/invoices/{inv['id']}/credit-notes", headers=admin, json={"amount_cents": 40_000, "reason": "Discount agreed"}
    )
    assert r.status_code == 201, r.text
    note = r.json()["credit_note"]
    assert note["number"] == f"SP-CN-{YEAR}-001" and r.json()["invoice"]["balance_cents"] == 60_000
    note_pdf = client.get(f"/api/credit-notes/{note['id']}/pdf", headers=admin).content
    assert has_image(note_pdf)

    paid = client.post(
        f"/api/invoices/{inv['id']}/payments",
        headers=admin,
        json={"amount_cents": 60_000, "received_on": TODAY, "reference": "EFT"},
    ).json()
    assert paid["invoice"]["status"] == "paid" and paid["payouts"] == []  # no project, so no payouts

    other = standalone_invoice(client, admin)
    r = client.post(
        f"/api/invoices/{other['id']}/credit-notes", headers=admin, json={"amount_cents": 100_000, "reason": "Cancelled"}
    )
    assert r.json()["invoice"]["status"] == "void"
    assert (
        client.post(
            f"/api/invoices/{other['id']}/payments",
            headers=admin,
            json={"amount_cents": 1, "received_on": TODAY, "reference": "x"},
        ).status_code
        == 409
    )


def test_overdue_flag_and_daily_jobs(client, admin, company_ready):
    from app.db import SessionLocal
    from app.models import Invoice, Quotation

    inv = standalone_invoice(client, admin)
    c = new_client(client, admin, name="Late Client")
    q = new_quote(client, admin, c["id"])
    client.post(f"/api/quotations/{q['id']}/issue", headers=admin)
    with SessionLocal() as db:
        db.get(Invoice, inv["id"]).due_date = date(2020, 1, 1)
        db.get(Quotation, q["id"]).valid_until = date(2020, 1, 1)
        db.commit()
    assert client.get(f"/api/invoices/{inv['id']}", headers=admin).json()["overdue"] is True
    r = client.post("/api/jobs/daily", headers={"X-Jobs-Token": "jobs-token-for-tests"}).json()
    assert r["quotations_expired"] == 1 and r["invoices_overdue"] == 1
    assert client.get(f"/api/quotations/{q['id']}", headers=admin).json()["status"] == "expired"


def test_vat_registered_company_issues_tax_invoices(client, admin, company_ready, monkeypatch, sent_offer):
    monkeypatch.setattr(company_ready, "company_vat_number", "4000000000")
    person, _, token = sent_offer
    accept(client, token)
    c = new_client(client, admin)
    project = client.post("/api/projects", headers=admin, json={"name": "App", "client_name": "Glow Salon"}).json()
    client.put(
        f"/api/projects/{project['id']}/contributors", headers=admin, json={"person_id": person["id"], "work_share_bp": 10_000}
    )
    inv = client.post(
        "/api/invoices",
        headers=admin,
        json={
            "client_id": c["id"],
            "project_id": project["id"],
            "title": "App build",
            "lines": [{"description": "App build", "quantity": 1, "unit_price_cents": 1_000_000}],
        },
    ).json()
    assert (inv["subtotal_cents"], inv["vat_cents"], inv["total_cents"]) == (1_000_000, 150_000, 1_150_000)
    client.post(f"/api/invoices/{inv['id']}/issue", headers=admin)
    r = client.post(
        f"/api/invoices/{inv['id']}/payments",
        headers=admin,
        json={"amount_cents": 1_150_000, "received_on": TODAY, "reference": "EFT"},
    ).json()
    # Payouts use money received excluding VAT: R10,000 x 15% = R1,500.
    assert r["payouts"][0]["calculation"]["received_to_date_cents"] == 1_000_000
    assert r["payouts"][0]["amount_cents"] == 150_000


# ---- Numbering -----------------------------------------------------------------------------------


def test_numbering_is_per_type_and_year_and_respects_seed():
    from app.db import SessionLocal
    from app.numbering import allocate_number

    with SessionLocal() as db:
        assert allocate_number(db, "Q", 2026) == "SP-Q-2026-001"
        assert allocate_number(db, "Q", 2026) == "SP-Q-2026-002"
        assert allocate_number(db, "INV", 2026) == "SP-INV-2026-001"
        assert allocate_number(db, "Q", 2027) == "SP-Q-2027-001"
        assert allocate_number(db, "PS", 2026, seed=lambda: 4) == "SP-PS-2026-005"
        db.rollback()  # nothing committed, so the numbers are not used up
        assert allocate_number(db, "Q", 2026) == "SP-Q-2026-001"
        with pytest.raises(ValueError):
            allocate_number(db, "XX", 2026)


# ---- Signature loading ---------------------------------------------------------------------------


def test_signature_from_base64_and_rejects_bad_files(monkeypatch, tmp_path, no_signature_cache):
    s = get_settings()
    monkeypatch.setattr(s, "signature_image_base64", base64.b64encode(tiny_png()).decode())
    assert pdf_module.load_signature().startswith(b"\x89PNG")

    pdf_module.load_signature.cache_clear()
    monkeypatch.setattr(s, "signature_image_base64", "not base64!!")
    with pytest.raises(pdf_module.SignatureError):
        pdf_module.load_signature()

    pdf_module.load_signature.cache_clear()
    bad = tmp_path / "sig.txt"
    bad.write_bytes(b"hello")
    monkeypatch.setattr(s, "signature_image_path", str(bad))
    with pytest.raises(pdf_module.SignatureError):
        pdf_module.load_signature()

    pdf_module.load_signature.cache_clear()
    monkeypatch.setattr(s, "signature_image_path", str(tmp_path / "missing.png"))
    with pytest.raises(pdf_module.SignatureError):
        pdf_module.load_signature()


def test_acceptance_record_is_countersigned(client, admin, signed, sent_offer):
    from app.db import SessionLocal
    from app.models import Document

    _, _, token = sent_offer
    assert accept(client, token).status_code == 200
    with SessionLocal() as db:
        record = db.query(Document).filter(Document.kind == "acceptance").one()
        assert has_image(record.content)


def test_production_refuses_to_start_without_signature():
    settings = Settings(
        environment="production",
        secret_key="x" * 40,
        field_encryption_key="k",
        database_url="postgresql://u:p@h/db",
        smtp_host="h",
        smtp_user="u",
        smtp_pass="p",
        admin_notify_email="a@example.com",
        signature_image_path="",
        signature_image_base64="",
        signatory_name="",
    )
    with pytest.raises(RuntimeError, match="SIGNATURE_IMAGE_PATH"):
        settings.check_production_ready()
