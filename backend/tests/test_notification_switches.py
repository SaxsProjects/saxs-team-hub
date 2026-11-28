from datetime import timedelta

from app import emailer
from app.db import SessionLocal
from app.jobs import remind_overdue_invoices
from app.models import Client, Invoice
from app.services import today_local


def _overdue_invoice():
    with SessionLocal() as db:
        client = Client(name="Greenline Studio")
        db.add(client)
        db.flush()
        db.add(
            Invoice(
                number="SP-INV-2026-001",
                client_id=client.id,
                title="Website",
                status="issued",
                issue_date=today_local() - timedelta(days=40),
                due_date=today_local() - timedelta(days=10),
                vat_rate_bp=0,
                subtotal_cents=100000,
                vat_cents=0,
                total_cents=100000,
            )
        )
        db.commit()


def test_notifications_default_on_and_need_admin(client, admin):
    r = client.get("/api/auth/notifications", headers=admin)
    assert r.status_code == 200
    assert r.json() == {
        "offers": True,
        "reviews": True,
        "payouts": True,
        "invoices": True,
        "enquiries": True,
        "client_reminders": True,
        "client_statements": True,
    }
    assert client.get("/api/auth/notifications").status_code == 401


def test_switching_off_invoice_reminders_stops_that_email_only(client, admin):
    _overdue_invoice()
    r = client.put("/api/auth/notifications", headers=admin, json={"offers": True, "payouts": True, "invoices": False})
    assert r.status_code == 200 and r.json()["invoices"] is False
    assert client.get("/api/auth/notifications", headers=admin).json()["invoices"] is False

    emailer.outbox.clear()
    with SessionLocal() as db:
        assert remind_overdue_invoices(db) == 1
    assert not any("overdue" in m.subject for m in emailer.outbox)

    client.put("/api/auth/notifications", headers=admin, json={"invoices": True})
    with SessionLocal() as db:
        remind_overdue_invoices(db)
    assert any("invoice(s) overdue" in m.subject for m in emailer.outbox)

    audit = client.get("/api/audit", headers=admin).json()
    assert any(e["action"] == "settings.notifications" for e in audit)
