"""Website enquiries: the public form endpoint and the founder's follow-up."""

import json

from app.config import get_settings
from app.db import SessionLocal
from app.models import Client, Enquiry, Notification

SITE = "https://www.saxsprojects.co.za"
GOOD = {
    "name": "Thandi Mokoena",
    "email": "thandi@example.com",
    "organisation": "Glow Salon",
    "service": "Website",
    "message": "We need a website.",
}


def post(client, body, origin=SITE, content_type="text/plain"):
    headers = {"Content-Type": content_type}
    if origin:
        headers["Origin"] = origin
    return client.post("/api/public/enquiries", content=json.dumps(body) if not isinstance(body, str) else body, headers=headers)


def test_website_enquiry_is_saved_and_reaches_the_bell(client, admin):
    admin_headers = admin
    r = post(client, GOOD)
    assert r.status_code == 201
    assert r.headers["access-control-allow-origin"] == SITE
    # The website origin is only answered here (the reply is just {"ok": true}), never on the hub's own API.
    other = client.get("/api/health", headers={"Origin": SITE})
    assert "access-control-allow-origin" not in other.headers
    with SessionLocal() as db:
        e = db.query(Enquiry).one()
        bells = db.query(Notification).filter(Notification.title == "New website enquiry: Thandi Mokoena").count()
    assert (e.name, e.status, e.source) == ("Thandi Mokoena", "new", "website")
    assert bells >= 1

    listed = client.get("/api/enquiries", headers=admin_headers).json()
    assert listed[0]["message"] == "We need a website."
    brief = client.get("/api/assistant", headers=admin_headers).json()
    assert any(i["id"] == "enquiries" for i in brief["items"])


def test_other_sites_bots_and_bad_posts_are_refused(client):
    assert post(client, GOOD, origin="https://evil.example").status_code == 403
    assert post(client, {**GOOD, "website": "http://spam"}).status_code == 201  # honeypot: accepted, dropped
    assert post(client, {"name": "A", "message": "hi"}).status_code == 422
    assert post(client, {**GOOD, "email": None}).status_code == 422  # needs email or phone
    assert post(client, "not json").status_code == 422
    assert post(client, {**GOOD, "message": "x" * 20000}).status_code == 413
    with SessionLocal() as db:
        assert db.query(Enquiry).count() == 0


def test_founder_follows_up_and_makes_a_client_once(client, admin, team):
    admin_headers, member_headers = admin, team[1]
    post(client, GOOD)
    with SessionLocal() as db:
        eid = db.query(Enquiry).one().id
    assert client.get("/api/enquiries", headers=member_headers).status_code == 403
    assert client.patch(f"/api/enquiries/{eid}", json={"status": "converted"}, headers=admin_headers).status_code == 400
    assert (
        client.patch(f"/api/enquiries/{eid}", json={"status": "contacted"}, headers=admin_headers).json()["status"] == "contacted"
    )

    r = client.post(f"/api/enquiries/{eid}/client", headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "converted"
    with SessionLocal() as db:
        c = db.get(Client, r.json()["client_id"])
        got = (c.name, c.contact_name, c.kind, c.email)
    assert got == ("Glow Salon", "Thandi Mokoena", "company", "thandi@example.com")
    assert client.post(f"/api/enquiries/{eid}/client", headers=admin_headers).status_code == 409


def test_discord_alert_only_for_a_discord_webhook(monkeypatch):
    from app import emailer

    sent = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout: sent.append(json.loads(req.data)) or type("R", (), {"close": lambda s: None})(),
    )
    monkeypatch.setattr("threading.Thread", lambda target, daemon: type("T", (), {"start": lambda s: target()})())
    settings = get_settings()
    monkeypatch.setattr(settings, "discord_webhook_url", "https://attacker.example/hook")
    emailer.post_to_discord("Hello")
    assert sent == []
    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.com/api/webhooks/1/abc")
    emailer.post_to_discord("New website enquiry: Thandi", "/enquiries")
    assert sent[0]["content"].startswith("New website enquiry: Thandi\n") and sent[0]["content"].endswith("/enquiries")
    assert sent[0]["allowed_mentions"] == {"parse": []}
