from sqlalchemy import select

from app import emailer
from app.company import company_settings
from app.db import SessionLocal
from app.models import User
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

DETAILS = {
    "company_legal_name": "SaxsProjects (Pty) Ltd",
    "company_registration_number": "2026/941760/07",
    "company_vat_number": "",
    "company_address": "1 Test Street|Thohoyandou|0950",
    "company_email": "accounts@example.com",
    "company_phone": "",
    "company_website": "",
    "company_bank_name": "",
    "company_bank_account_name": "",
    "company_bank_account_number": "",
    "company_bank_branch_code": "",
    "company_bank_account_type": "",
    "signatory_name": "Test Director",
    "signatory_title": "Director",
}


def _two_factor_on():
    with SessionLocal() as db:
        db.scalar(select(User).where(User.email == ADMIN_EMAIL)).totp_enabled = True
        db.commit()


def test_needs_two_factor(client, admin):
    assert client.get("/api/company", headers=admin).status_code == 200
    r = client.put("/api/company", headers=admin, json=DETAILS)
    assert r.status_code == 403 and "two-factor" in r.json()["detail"]


def test_saved_details_win_and_are_audited(client, admin):
    _two_factor_on()
    r = client.put("/api/company", headers=admin, json=DETAILS)
    assert r.status_code == 200, r.text
    assert r.json()["company_registration_number"] == "2026/941760/07"
    with SessionLocal() as db:
        s = company_settings(db)
        assert s.company_registration_number == "2026/941760/07"
        assert s.company_address_lines == ["1 Test Street", "Thohoyandou", "0950"]
    assert client.get("/api/finance/readiness", headers=admin).json()["registration_number_set"] is True
    events = client.get("/api/audit?scope=workspace", headers=admin).json()
    update = next(e for e in events if e["action"] == "company.update")
    assert update["after"]["company_registration_number"] == "2026/941760/07"


def test_bad_values_are_refused(client, admin):
    _two_factor_on()
    bad = (("company_vat_number", "123"), ("company_registration_number", "941760"), ("company_bank_branch_code", "12"))
    for field, value in bad:
        r = client.put("/api/company", headers=admin, json={**DETAILS, field: value})
        assert r.status_code == 422, field


def test_bank_change_needs_password_masks_and_alerts(client, admin):
    _two_factor_on()
    bank = {
        **DETAILS,
        "company_bank_name": "Capitec",
        "company_bank_account_number": "1234 5678 90",
        "company_bank_branch_code": "470010",
    }
    assert client.put("/api/company", headers=admin, json=bank).status_code == 400
    assert client.put("/api/company", headers=admin, json={**bank, "current_password": "wrong-password"}).status_code == 400
    emailer.outbox.clear()
    r = client.put("/api/company", headers=admin, json={**bank, "current_password": ADMIN_PASSWORD})
    assert r.status_code == 200 and r.json()["company_bank_account_number"] == "1234567890"
    alert = next(m for m in emailer.outbox if m.subject == "Company banking details changed")
    assert "•••• 7890" in alert.text and "1234567890" not in alert.text
    update = next(e for e in client.get("/api/audit", headers=admin).json() if e["action"] == "company.update")
    assert update["after"]["company_bank_account_number"] == "•••• 7890"
    # Non-bank edits don't ask for the password again.
    r = client.put("/api/company", headers=admin, json={**bank, "company_phone": "0820000000"})
    assert r.status_code == 200


def test_audit_scopes_split_account_events_from_workspace(client, admin):
    client.post("/api/people", headers=admin, json={"full_name": "Thabo Mokoena", "email": "t@example.com"})
    workspace = {e["action"] for e in client.get("/api/audit?scope=workspace", headers=admin).json()}
    account = {e["action"] for e in client.get("/api/audit?scope=account", headers=admin).json()}
    assert "auth.login" in account and "auth.login" not in workspace
    assert "person.create" in workspace and "person.create" not in account
