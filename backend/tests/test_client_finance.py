"""Client follow-ups, statements of account, the monthly report, the VAT tracker and the VAT lines on documents."""

import re
import zlib
from datetime import date, timedelta

import pytest

from app import emailer
from app.client_finance import reminder_stage_due, send_client_reminders, send_monthly_report
from app.config import get_settings
from app.db import SessionLocal
from app.models import Invoice, Notification
from app.services import today_local

from .test_finance import company_ready, no_signature_cache, signed, standalone_invoice  # noqa: F401

JOBS = {"X-Jobs-Token": "jobs-token-for-tests"}


def pdf_text(content: bytes) -> str:
    """The text drawn on every page (fpdf2 compresses page streams)."""
    out = []
    for raw in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", content, re.S):
        try:
            out.append(zlib.decompress(raw).decode("latin-1"))
        except zlib.error:
            out.append(raw.decode("latin-1", "replace"))
    strings = re.findall(r"\(((?:\\.|[^\\)])*)\)\s*Tj", "\n".join(out))
    return " ".join(re.sub(r"\\(.)", r"\1", text) for text in strings)


def set_due(invoice_id: int, due: date) -> None:
    with SessionLocal() as db:
        db.get(Invoice, invoice_id).due_date = due
        db.commit()


def reminders_to(address: str) -> list:
    return [m for m in emailer.outbox if m.to == address and "invoice" in m.subject.lower()]


def test_reminder_stages():
    today = date(2026, 12, 15)
    assert reminder_stage_due(today + timedelta(days=4), today) == 0
    assert reminder_stage_due(today + timedelta(days=3), today) == 1
    assert reminder_stage_due(today, today) == 1
    assert reminder_stage_due(today - timedelta(days=1), today) == 2
    assert reminder_stage_due(today - timedelta(days=7), today) == 3
    assert reminder_stage_due(today - timedelta(days=14), today) == 4
    assert reminder_stage_due(None, today) == 0


def test_clients_without_registration_number_and_with_vat_number(client, admin):
    r = client.post("/api/clients", headers=admin, json={"name": "Thabo Plumbing", "kind": "sole_proprietor"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["registration_number"] is None and body["kind"] == "sole_proprietor" and body["reminders_enabled"] is True
    r = client.patch(
        f"/api/clients/{body['id']}", headers=admin, json={"vat_number": " 4123456789 ", "registration_number": "  "}
    )
    assert r.json()["vat_number"] == "4123456789" and r.json()["registration_number"] is None
    assert client.post("/api/clients", headers=admin, json={"name": "X Co", "kind": "alien"}).status_code == 422


@pytest.mark.usefixtures("company_ready")
def test_reminders_move_one_stage_at_a_time_and_never_repeat(client, admin):
    inv = standalone_invoice(client, admin)
    address = "owner@glow.example"
    today = today_local()

    set_due(inv["id"], today + timedelta(days=10))
    with SessionLocal() as db:
        assert send_client_reminders(db) == 0  # not due yet

    set_due(inv["id"], today + timedelta(days=2))
    with SessionLocal() as db:
        assert send_client_reminders(db) == 1
        db.commit()
        assert send_client_reminders(db) == 0  # the same stage is never sent twice
        db.commit()
    first = reminders_to(address)
    assert len(first) == 1 and first[0].subject.startswith("Payment reminder")
    assert first[0].attachments and first[0].attachments[0][0] == f"{inv['number']}.pdf"

    # Weeks later: only the stage it has reached is sent, not every stage it skipped.
    set_due(inv["id"], today - timedelta(days=20))
    r = client.post("/api/jobs/daily", headers=JOBS).json()
    assert r["client_reminders_sent"] == 1
    assert [m.subject.split(":")[0] for m in reminders_to(address)] == ["Payment reminder", "Final notice"]
    with SessionLocal() as db:
        assert db.get(Invoice, inv["id"]).reminder_stage == 4
        assert db.query(Notification).filter(Notification.title.like("Final notice sent%")).count() == 1


@pytest.mark.usefixtures("company_ready")
def test_reminders_respect_the_client_and_founder_switches(client, admin):
    inv = standalone_invoice(client, admin)
    set_due(inv["id"], today_local() - timedelta(days=2))
    client.patch(f"/api/clients/{inv['client_id']}", headers=admin, json={"reminders_enabled": False})
    with SessionLocal() as db:
        assert send_client_reminders(db) == 0
    client.patch(f"/api/clients/{inv['client_id']}", headers=admin, json={"reminders_enabled": True})
    client.put("/api/auth/notifications", headers=admin, json={"client_reminders": False})
    with SessionLocal() as db:
        assert send_client_reminders(db) == 0
    client.put("/api/auth/notifications", headers=admin, json={"client_reminders": True})
    with SessionLocal() as db:
        assert send_client_reminders(db) == 1


@pytest.mark.usefixtures("company_ready")
def test_statement_of_account_preview_and_issue(client, admin):
    inv = standalone_invoice(client, admin, cents=250_000)
    set_due(inv["id"], today_local() - timedelta(days=40))
    preview = client.get(f"/api/clients/{inv['client_id']}/statement.pdf", headers=admin)
    assert preview.status_code == 200 and preview.headers["content-type"] == "application/pdf"
    text = pdf_text(preview.content)
    assert "STATEMENT OF ACCOUNT" in text and inv["number"] in text and "R2,500.00" in text

    r = client.post(f"/api/clients/{inv['client_id']}/statements", headers=admin, json={"email": True})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["number"] == "SP-SOA-0001" and body["emailed"] is True
    mail = next(m for m in emailer.outbox if m.subject.startswith("Statement of account SP-SOA-0001"))
    assert mail.to == "owner@glow.example" and mail.attachments[0][0] == "SP-SOA-0001.pdf"
    stored = client.get(f"/api/statements/{body['document_id']}.pdf", headers=admin)
    assert stored.status_code == 200 and "SP-SOA-0001" in pdf_text(stored.content)
    assert client.post(f"/api/clients/{inv['client_id']}/statements", headers=admin, json={}).json()["number"] == "SP-SOA-0002"


@pytest.mark.usefixtures("company_ready")
def test_statement_email_needs_an_address(client, admin):
    c = client.post("/api/clients", headers=admin, json={"name": "No Email Co"}).json()
    r = client.post(f"/api/clients/{c['id']}/statements", headers=admin, json={"email": True})
    assert r.status_code == 400 and "email" in r.json()["detail"]


@pytest.mark.usefixtures("company_ready")
def test_finance_report_and_monthly_email(client, admin):
    inv = standalone_invoice(client, admin, cents=100_000)
    month = today_local().strftime("%Y-%m")
    r = client.get(f"/api/reports/finance?month={month}", headers=admin)
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["totals"]["invoiced_excl_cents"] == 100_000 and report["totals"]["vat_cents"] == 0
    assert report["position"]["open_count"] == 1 and report["clients"][0]["name"] == "Corner Shop"
    pdf = client.get(f"/api/reports/finance.pdf?month={month}", headers=admin)
    assert pdf.status_code == 200 and "FINANCE REPORT" in pdf_text(pdf.content)
    assert client.get("/api/reports/finance?month=2026-13", headers=admin).status_code == 400
    assert client.get("/api/reports/finance?month=2999-01", headers=admin).status_code == 400

    first = today_local().replace(day=1) + timedelta(days=32)
    first = first.replace(day=1)
    with SessionLocal() as db:
        assert send_monthly_report(db, first) == 1
        db.commit()
        assert send_monthly_report(db, first) == 0  # once a month
        assert send_monthly_report(db, first + timedelta(days=1)) == 0  # only on the 1st
    assert any(m.subject.startswith("Finance report for") for m in emailer.outbox)
    del inv


@pytest.mark.usefixtures("company_ready")
def test_documents_show_amounts_excluding_and_including_vat(client, admin):
    inv = standalone_invoice(client, admin, cents=120_000)
    text = pdf_text(client.get(f"/api/invoices/{inv['id']}/pdf", headers=admin).content)
    for label in ("Amount excl. VAT", "VAT 0% (not registered)", "Amount incl. VAT", "not a registered VAT vendor"):
        assert label in text, label


@pytest.mark.usefixtures("company_ready")
def test_vat_tracker_on_the_dashboard(client, admin, monkeypatch):
    company = get_settings()
    standalone_invoice(client, admin, cents=1_000_000)
    vat = client.get("/api/dashboard", headers=admin).json()["vat"]
    assert vat["registered"] is False and vat["taxable_12m_cents"] == 1_000_000 and vat["status"] == "below"
    monkeypatch.setattr(company, "vat_voluntary_threshold_cents", 500_000)
    assert client.get("/api/dashboard", headers=admin).json()["vat"]["status"] == "voluntary_possible"
    monkeypatch.setattr(company, "vat_compulsory_threshold_cents", 1_100_000)
    assert client.get("/api/dashboard", headers=admin).json()["vat"]["status"] == "approaching"
    monkeypatch.setattr(company, "vat_compulsory_threshold_cents", 900_000)
    vat = client.get("/api/dashboard", headers=admin).json()["vat"]
    assert vat["status"] == "must_register" and "21 days" in vat["message"]
    monkeypatch.setattr(company, "company_vat_number", "4000000000")
    assert client.get("/api/dashboard", headers=admin).json()["vat"]["status"] == "registered"
