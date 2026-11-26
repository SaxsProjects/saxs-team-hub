"""Dashboard, member overview, payment list, and encrypted backup/restore."""

import csv
import io

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine

from app.db import Base, SessionLocal, engine
from app.models import Payout
from app.services import today_local
from scripts import backup
from tests.test_task_orders_and_rates import create_order, other_person, pay


def accepted_fee(client, admin, member, person_id, fee_cents=250_000):
    oid = create_order(client, admin, person_id, fee_cents=fee_cents)["id"]
    client.post(f"/api/me/task-orders/{oid}/confirm", headers=member)
    client.post(f"/api/me/task-orders/{oid}/submit", headers=member, json={"note": "done"})
    return client.post(f"/api/task-orders/{oid}/accept", headers=admin, json={}).json()["payout"]


def make_due(payout_id):
    with SessionLocal() as db:
        db.get(Payout, payout_id).due_at = today_local()
        db.commit()


def test_dashboard_and_member_overview(client, admin, team):
    person, member = team
    fee = accepted_fee(client, admin, member, person["id"])
    waiting = create_order(client, admin, person["id"])  # proposed: the member still has to confirm it

    me = client.get("/api/me/overview", headers=member).json()
    assert me["owed_cents"] == 250_000 and me["due_now_cents"] == 0 and me["next_due_on"]
    assert me["task_orders_to_confirm"] == 1 and me["can_request_payment_count"] == 0

    make_due(fee["id"])
    me = client.get("/api/me/overview", headers=member).json()
    assert me["due_now_count"] == 1 and me["can_request_payment_count"] == 1
    client.post(f"/api/me/payouts/{fee['id']}/request-payment", headers=member)
    assert client.get("/api/me/overview", headers=member).json()["can_request_payment_count"] == 0

    board = client.get("/api/dashboard", headers=admin).json()
    assert board["payouts"]["due_now_cents"] == 250_000
    assert board["payouts"]["payment_requested_count"] == 1
    assert board["task_orders_by_status"] == {"accepted": 1, "proposed": 1}
    assert waiting["status"] == "proposed"

    client.post(f"/api/payouts/{fee['id']}/paid", headers=admin, json={"eft_reference": "CAP-1"})
    board = client.get("/api/dashboard", headers=admin).json()
    assert board["payouts"]["unpaid_cents"] == 0 and board["payouts"]["paid_this_year_cents"] == 250_000
    assert client.get("/api/me/overview", headers=member).json()["paid_this_year_cents"] == 250_000


def test_overviews_are_role_limited(client, admin, team):
    _, member = team
    assert client.get("/api/dashboard", headers=member).status_code == 403
    assert client.get("/api/payment-list.csv", headers=member).status_code == 403
    assert client.get("/api/dashboard").status_code == 401


def test_payment_list_csv(client, admin, team):
    person, member = team
    due = accepted_fee(client, admin, member, person["id"], 123_456)
    accepted_fee(client, admin, member, person["id"], 99_900)  # not due yet: left out
    make_due(due["id"])
    other = other_person(client, admin)
    client.patch(f"/api/people/{other['id']}", headers=admin, json={"full_name": "=HYPERLINK(1)"})
    pid = client.post("/api/projects", headers=admin, json={"name": "Site", "client_name": "Client"}).json()["id"]
    client.put(f"/api/projects/{pid}/contributors", headers=admin, json={"person_id": other["id"], "work_share_bp": 10_000})
    [share] = pay(client, admin, pid, 100_000, today_local().isoformat(), "EFT-1")
    make_due(share["id"])

    r = client.get("/api/payment-list.csv", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][0] == "Beneficiary" and len(rows) == 3
    amounts = {row[2]: row[1] for row in rows[1:]}
    assert amounts[due["statement_number"]] == "1234.56"
    assert any(row[0].startswith("'=") for row in rows[1:])  # formula neutralised
    assert all("account" not in cell.lower() for cell in rows[0])

    client.post(f"/api/me/payouts/{due['id']}/request-payment", headers=member)
    only = list(csv.reader(io.StringIO(client.get("/api/payment-list.csv?requested_only=true", headers=admin).text)))
    assert [row[2] for row in only[1:]] == [due["statement_number"]]
    actions = [a["action"] for a in client.get("/api/audit", headers=admin).json()]
    assert "payout.export_payment_list" in actions


@pytest.fixture
def backup_key(monkeypatch):
    monkeypatch.setenv("BACKUP_KEY", Fernet.generate_key().decode())


def test_backup_round_trip(client, admin, team, backup_key, tmp_path):
    person, member = team
    accepted_fee(client, admin, member, person["id"])
    original = backup.dump(engine)
    blob = backup.seal(original)
    assert b"Payout" not in blob and person["email"].encode() not in blob  # encrypted, not just compressed

    target = create_engine(f"sqlite:///{tmp_path / 'restore.db'}")
    Base.metadata.create_all(target)
    with target.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        if original["alembic_revision"]:
            conn.exec_driver_sql("INSERT INTO alembic_version VALUES (?)", (original["alembic_revision"],))
    counts = backup.load(target, backup.unseal(blob))
    assert counts["payouts"] == 1 and counts["people"] >= 1
    restored = backup.dump(target)
    assert restored["tables"] == original["tables"]

    with pytest.raises(SystemExit, match="already has data"):
        backup.load(target, backup.unseal(blob))


def test_backup_rejects_tampering_and_wrong_key(client, admin, backup_key, monkeypatch):
    blob = bytearray(backup.seal(backup.dump(engine)))
    blob[60] ^= 1
    with pytest.raises(SystemExit, match="Cannot decrypt"):
        backup.unseal(bytes(blob))
    good = backup.seal(backup.dump(engine))
    monkeypatch.setenv("BACKUP_KEY", Fernet.generate_key().decode())
    with pytest.raises(SystemExit, match="Cannot decrypt"):
        backup.unseal(good)
