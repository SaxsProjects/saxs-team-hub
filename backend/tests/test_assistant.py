"""Saxs Assistant: suggestions come from real records and the compliance calendar, per role."""

from datetime import date, timedelta

import pytest

from app.assistant import upcoming_deadlines
from app.db import SessionLocal
from app.models import Invoice
from app.services import today_local

from .test_finance import company_ready, no_signature_cache, signed, standalone_invoice  # noqa: F401


def test_compliance_calendar():
    titles = [d.title for d in upcoming_deadlines(date(2026, 11, 28))]
    assert "Provisional tax (IRP6), second period" in titles  # the nil return due 31 Dec 2026
    assert "CIPC annual return" not in titles  # first one is in 2027
    later = upcoming_deadlines(date(2027, 10, 1))
    assert any(d.title == "CIPC annual return" and d.on == date(2027, 11, 24) for d in later)


@pytest.mark.usefixtures("company_ready")
def test_founder_briefing_lists_overdue_invoices_with_links(client, admin):
    inv = standalone_invoice(client, admin)
    with SessionLocal() as db:
        db.get(Invoice, inv["id"]).due_date = today_local() - timedelta(days=5)
        db.commit()
    body = client.get("/api/assistant", headers=admin).json()
    assert body["greeting"].startswith("Good ")
    overdue = next(i for i in body["items"] if i["id"] == "overdue")
    assert overdue["priority"] == "high" and overdue["link"] == "/finance/invoices" and "automatically" in overdue["detail"]
    assert body["autopilot"]["client_reminders"] is True
    assert [i["priority"] for i in body["items"]] == sorted(
        (i["priority"] for i in body["items"]), key=["high", "normal", "info"].index
    )


def test_member_briefing_is_their_own(client, admin, team):
    _, member = team
    body = client.get("/api/assistant", headers=member).json()
    ids = {i["id"] for i in body["items"]}
    assert "photo" in ids and "overdue" not in ids and body["autopilot"] == {}
    assert client.get("/api/assistant").status_code == 401
