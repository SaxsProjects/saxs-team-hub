"""The notification bell: events reach the right person, counts are per user, nobody reads anyone else's."""

from datetime import timedelta

from app.db import SessionLocal
from app.models import Notification
from app.notifications import notify_admins
from app.services import today_local


def bell(client, headers):
    r = client.get("/api/notifications", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_offer_acceptance_rings_the_founders_bell(client, admin, team):
    body = bell(client, admin)
    assert body["unread"] >= 1
    assert any("accepted" in n["title"].lower() for n in body["items"])
    assert client.get("/api/notifications/unread-count", headers=admin).json()["unread"] == body["unread"]


def test_task_order_flow_notifies_both_sides(client, admin, team):
    person, member = team
    client.post("/api/notifications/read-all", headers=admin)
    due = (today_local() + timedelta(days=7)).isoformat()
    order = client.post(
        "/api/task-orders",
        headers=admin,
        json={"person_id": person["id"], "title": "Landing page", "deliverable": "One page.", "fee_cents": 50_000, "due_on": due},
    ).json()
    mine = bell(client, member)
    assert mine["unread"] == 1 and mine["items"][0]["title"] == f"New task offered: {order['number']}"
    assert mine["items"][0]["link"] == "/my/task-orders"

    client.post(f"/api/me/task-orders/{order['id']}/confirm", headers=member)
    titles = [n["title"] for n in bell(client, admin)["items"]]
    assert f"Task confirmed: {order['number']}" in titles


def test_read_one_read_all_and_privacy(client, admin, team):
    _, member = team
    with SessionLocal() as db:
        notify_admins(db, "system", "Hello founder", "Body")
        db.commit()
    items = bell(client, admin)["items"]
    target = next(n for n in items if n["title"] == "Hello founder")

    # A member cannot read or clear the founder's notifications, and does not learn whether they exist.
    assert client.post("/api/notifications/read", headers=member, json={"ids": [target["id"]]}).status_code == 404
    assert all(n["id"] != target["id"] for n in bell(client, member)["items"])
    assert client.get("/api/notifications").status_code == 401

    before = bell(client, admin)["unread"]
    r = client.post("/api/notifications/read", headers=admin, json={"ids": [target["id"]]})
    assert r.status_code == 200 and r.json()["unread"] == before - 1
    assert client.post("/api/notifications/read-all", headers=admin).json()["unread"] == 0
    assert bell(client, admin)["unread"] == 0
    assert bell(client, admin)["items"][0]["read_at"] is not None


def test_the_same_unread_reminder_is_refreshed_not_stacked(client, admin):
    with SessionLocal() as db:
        for _ in range(3):
            notify_admins(db, "payouts", "2 contractor payout(s) due", "list")
            db.commit()
        assert db.query(Notification).filter(Notification.title == "2 contractor payout(s) due").count() == 1
    client.post("/api/notifications/read-all", headers=admin)
    with SessionLocal() as db:
        notify_admins(db, "payouts", "2 contractor payout(s) due", "list")
        db.commit()
        assert db.query(Notification).filter(Notification.title == "2 contractor payout(s) due").count() == 2
